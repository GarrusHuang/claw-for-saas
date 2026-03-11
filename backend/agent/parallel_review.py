"""
多 Agent 并行审查编排器 — Phase 13。

用多个专业化子 Agent **并行**审查复杂产物 (合同、报销单)，
从不同角度发现问题。

使用 asyncio.gather 并行运行多个 SubagentRunner:
- 每个 Agent 使用不同的角色定义 (agents/*.md)
- 结果汇总采用保守策略 (任何失败 → 整体失败)
- 支持超时控制和异常隔离

Usage:
    orchestrator = ParallelReviewOrchestrator(subagent_runner)
    result = await orchestrator.parallel_review(
        content="报销单内容...",
        agent_roles=["data-validator", "compliance-reviewer"],
        context="附加上下文",
    )
    print(result.overall_status)  # "通过" | "警告" | "失败"
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentReviewResult:
    """单个 Agent 的审查结果"""
    agent_role: str
    conclusion: str = "未知"  # "通过" | "警告" | "失败" | "错误"
    confidence: int = 0      # 0-100
    details: str = ""        # 详细说明
    duration_ms: float = 0.0


@dataclass
class ParallelReviewResult:
    """并行审查汇总结果"""
    overall_status: str = "通过"     # "通过" | "警告" | "失败"
    overall_confidence: int = 100
    individual_results: list[AgentReviewResult] = field(default_factory=list)
    summary: str = ""
    duration_ms: float = 0.0


class ParallelReviewOrchestrator:
    """
    多 Agent 并行审查编排器。

    核心流程:
    1. 接收待审查内容 + 参与审查的角色列表
    2. 使用 asyncio.gather 并行运行所有 Agent
    3. 解析每个 Agent 的审查结论
    4. 汇总: 保守策略 (任何失败 → 整体失败, 任何警告 → 整体警告)
    """

    DEFAULT_TIMEOUT_S = 120  # 单个 Agent 超时

    def __init__(self, subagent_runner: Any) -> None:
        """
        Args:
            subagent_runner: SubagentRunner 实例
        """
        self.subagent_runner = subagent_runner

    async def parallel_review(
        self,
        content: str,
        agent_roles: list[str],
        context: str = "",
        timeout_s: float | None = None,
    ) -> ParallelReviewResult:
        """
        并行运行多个 Agent 进行审查。

        Args:
            content: 待审查的内容 (文档/报销单/合同文本)
            agent_roles: 参与审查的角色名称列表
            context: 附加业务上下文
            timeout_s: 单个 Agent 超时秒数

        Returns:
            ParallelReviewResult 汇总结果
        """
        if not agent_roles:
            return ParallelReviewResult(
                overall_status="通过",
                overall_confidence=100,
                summary="无审查角色，跳过审查",
            )

        timeout = timeout_s or self.DEFAULT_TIMEOUT_S
        start_time = time.time()

        logger.info(f"Starting parallel review with {len(agent_roles)} agents: {agent_roles}")

        # 并行运行所有 Agent
        tasks = [
            self._run_single_review(content, role, context, timeout)
            for role in agent_roles
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果
        individual_results: list[AgentReviewResult] = []
        for i, result in enumerate(results):
            role = agent_roles[i]
            if isinstance(result, Exception):
                logger.error(f"Agent '{role}' review failed with exception: {result}")
                individual_results.append(AgentReviewResult(
                    agent_role=role,
                    conclusion="错误",
                    confidence=0,
                    details=f"执行异常: {result}",
                ))
            elif isinstance(result, AgentReviewResult):
                individual_results.append(result)
            else:
                individual_results.append(AgentReviewResult(
                    agent_role=role,
                    conclusion="错误",
                    confidence=0,
                    details=f"未知返回类型: {type(result)}",
                ))

        # 汇总
        duration_ms = (time.time() - start_time) * 1000
        final = self._aggregate(individual_results)
        final.duration_ms = duration_ms

        logger.info(
            f"Parallel review completed in {duration_ms:.0f}ms: "
            f"status={final.overall_status}, confidence={final.overall_confidence}"
        )

        return final

    async def _run_single_review(
        self,
        content: str,
        agent_role: str,
        context: str,
        timeout_s: float,
    ) -> AgentReviewResult:
        """运行单个 Agent 的审查。"""
        start_time = time.time()

        # 构建审查任务描述
        task = (
            f"请审查以下内容，给出你的专业审查意见。\n\n"
            f"## 审查内容\n\n{content}\n\n"
            f"## 要求\n\n"
            f"1. 仔细检查内容中的问题\n"
            f"2. 在回答的**最后一行**使用以下格式给出结论:\n"
            f"   <review_result conclusion=\"通过/警告/失败\" confidence=\"0-100\" />\n"
            f"3. 结论说明:\n"
            f"   - 通过: 内容合规，无问题\n"
            f"   - 警告: 有轻微问题但不阻塞\n"
            f"   - 失败: 有严重问题，必须修改\n"
        )

        try:
            raw_result = await asyncio.wait_for(
                self.subagent_runner.run_subagent(
                    task=task,
                    agent_role=agent_role,
                    context=context,
                    inherit_context=True,
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            return AgentReviewResult(
                agent_role=agent_role,
                conclusion="错误",
                confidence=0,
                details=f"审查超时 ({timeout_s}s)",
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return AgentReviewResult(
                agent_role=agent_role,
                conclusion="错误",
                confidence=0,
                details=f"执行失败: {e}",
                duration_ms=(time.time() - start_time) * 1000,
            )

        duration_ms = (time.time() - start_time) * 1000

        # 解析结果
        conclusion, confidence = self._parse_review_result(raw_result)

        return AgentReviewResult(
            agent_role=agent_role,
            conclusion=conclusion,
            confidence=confidence,
            details=raw_result[:2000],
            duration_ms=duration_ms,
        )

    def _parse_review_result(self, raw_text: str) -> tuple[str, int]:
        """
        从 Agent 输出中解析审查结论。

        查找 <review_result conclusion="..." confidence="..." /> 标签。
        找不到标签时尝试从文本关键词推断。
        """
        # 尝试解析 XML 标签
        pattern = r'<review_result\s+conclusion=["\'](\S+?)["\'](?:\s+confidence=["\'](\d+)["\'])?\s*/>'
        match = re.search(pattern, raw_text, re.IGNORECASE)
        if match:
            conclusion = match.group(1)
            confidence = int(match.group(2)) if match.group(2) else 80
            # 归一化结论
            conclusion = self._normalize_conclusion(conclusion)
            return conclusion, min(confidence, 100)

        # 回退: 从文本关键词推断
        return self._infer_from_text(raw_text)

    def _normalize_conclusion(self, conclusion: str) -> str:
        """归一化审查结论。"""
        lower = conclusion.lower().strip()
        if lower in ("通过", "pass", "passed", "ok", "approve", "approved"):
            return "通过"
        elif lower in ("警告", "warning", "warn", "caution"):
            return "警告"
        elif lower in ("失败", "fail", "failed", "reject", "rejected"):
            return "失败"
        return conclusion

    def _infer_from_text(self, text: str) -> tuple[str, int]:
        """从文本中推断审查结论 (回退策略)。"""
        text_lower = text.lower()

        # 检查负面关键词
        fail_keywords = ["不合规", "不通过", "严重问题", "必须修改", "拒绝", "rejected", "failed"]
        warn_keywords = ["建议修改", "轻微问题", "注意", "建议关注", "warning"]
        pass_keywords = ["合规", "通过", "无问题", "approved", "passed"]

        has_fail = any(kw in text_lower for kw in fail_keywords)
        has_warn = any(kw in text_lower for kw in warn_keywords)
        has_pass = any(kw in text_lower for kw in pass_keywords)

        if has_fail:
            return "失败", 60
        elif has_warn and not has_pass:
            return "警告", 60
        elif has_pass:
            return "通过", 60
        else:
            # 无法确定，默认通过但低信心
            return "通过", 30

    def _aggregate(self, results: list[AgentReviewResult]) -> ParallelReviewResult:
        """
        汇总所有 Agent 的审查结果。

        保守策略:
        - 任何一个"失败" → 整体失败
        - 任何一个"警告" (无失败) → 整体警告
        - 全部"通过" → 整体通过
        - "错误"不影响其他结果，但会降低整体信心
        """
        if not results:
            return ParallelReviewResult(
                overall_status="通过",
                overall_confidence=100,
                summary="无审查结果",
            )

        has_fail = any(r.conclusion == "失败" for r in results)
        has_warning = any(r.conclusion == "警告" for r in results)
        has_error = any(r.conclusion == "错误" for r in results)

        if has_fail:
            overall_status = "失败"
        elif has_warning:
            overall_status = "警告"
        else:
            overall_status = "通过"

        # 计算整体信心 (加权平均, 错误项权重降低)
        valid_results = [r for r in results if r.conclusion != "错误"]
        if valid_results:
            avg_confidence = sum(r.confidence for r in valid_results) // len(valid_results)
        else:
            avg_confidence = 0

        # 有错误时降低信心
        if has_error:
            error_count = sum(1 for r in results if r.conclusion == "错误")
            avg_confidence = max(0, avg_confidence - error_count * 10)

        # 生成汇总文本
        summary_parts = []
        for r in results:
            summary_parts.append(f"- {r.agent_role}: {r.conclusion} (信心 {r.confidence}%)")
        summary = f"## 并行审查结果: {overall_status}\n\n" + "\n".join(summary_parts)

        return ParallelReviewResult(
            overall_status=overall_status,
            overall_confidence=avg_confidence,
            individual_results=results,
            summary=summary,
        )
