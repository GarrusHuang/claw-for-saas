"""
自验证与反思机制 — Phase 11。

Quality Gate: 在 Agent 产出 final_answer 前进行质量检查。
通过 agent_stop hook 实现自迭代 (Ralph Wiggum 模式):
- 检查表单完整性
- 检查审计结果一致性
- 检查数值计算是否使用了 calculator
- 不通过则 block + 返回修正提示让 Agent 继续迭代

Usage:
    hooks.register("agent_stop", quality_gate_hook)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from agent.hooks import HookEvent, HookResult

logger = logging.getLogger(__name__)

# 最大自迭代次数 (防止无限循环)
MAX_SELF_CORRECTIONS = 2


@dataclass
class QualityCheckResult:
    """质量检查结果。"""
    passed: bool = True
    issues: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)  # 注入给 Agent 的修正提示


class QualityGate:
    """
    Agent 输出质量门。

    在 agent_stop 事件中评估 Agent 的工具调用历史和最终输出，
    判断是否需要自迭代修正。
    """

    def __init__(
        self,
        checks: list[Callable[[HookEvent], tuple[bool, str, str]]] | None = None,
    ) -> None:
        # 默认空检查列表 — SaaS 集成方通过传入自定义 checks 激活。
        # 内置的 check_form_completeness / check_audit_consistency 仍可用，
        # 但不再默认启用，因为它们依赖 HRP 特定的 business_context 字段
        # (form_fields, check_audit_rule, submit_all_audit_results)，
        # 通用 SaaS 场景中这些字段不存在会导致检查空转。
        self.checks = checks if checks is not None else []

    def evaluate(self, event: HookEvent) -> QualityCheckResult:
        """
        评估 Agent 输出质量。

        Args:
            event: agent_stop HookEvent (含 runtime_steps, context)

        Returns:
            QualityCheckResult
        """
        result = QualityCheckResult()

        for check_fn in self.checks:
            try:
                passed, issue, correction = check_fn(event)
                if not passed:
                    result.passed = False
                    result.issues.append(issue)
                    if correction:
                        result.corrections.append(correction)
            except Exception as e:
                logger.warning(f"Quality check {check_fn.__name__} error: {e}")
                # 检查函数出错不影响整体 → 视为通过
                continue

        return result


# ── 内置检查函数 ──


def check_form_completeness(event: HookEvent) -> tuple[bool, str, str]:
    """
    检查表单填写完整性。

    规则: 如果 business_context 中有 form_fields，
    则 runtime_steps 中的 update_form_field 调用应覆盖所有必填字段。
    """
    context = event.context or {}
    business_type = context.get("business_type", "")

    # 只在创建/起草场景下检查
    if not any(kw in business_type for kw in ("create", "draft")):
        return True, "", ""

    form_fields = context.get("form_fields", [])
    if not form_fields:
        return True, "", ""

    # 提取必填字段
    required_fields = set()
    for f in form_fields:
        if isinstance(f, dict):
            field_id = f.get("field_id") or f.get("id", "")
            if f.get("required", False) and field_id:
                required_fields.add(field_id)

    if not required_fields:
        return True, "", ""

    # 检查 runtime_steps 中哪些字段已填写
    filled_fields = set()
    steps = event.runtime_steps or []
    for step in steps:
        if isinstance(step, dict) and step.get("tool") == "update_form_field":
            args = step.get("args", {})
            field_id = args.get("field_id", "")
            if field_id:
                filled_fields.add(field_id)

    missing = required_fields - filled_fields
    if missing:
        issue = f"必填字段未填写: {', '.join(sorted(missing))}"
        correction = (
            f"请继续填写以下必填字段: {', '.join(sorted(missing))}。"
            "使用 update_form_field 工具逐一填写。"
        )
        return False, issue, correction

    return True, "", ""


def check_audit_consistency(event: HookEvent) -> tuple[bool, str, str]:
    """
    检查审计结果一致性。

    规则: 如果有 check_audit_rule 调用，检查是否有矛盾结论。
    """
    steps = event.runtime_steps or []

    audit_results = []
    for step in steps:
        if isinstance(step, dict) and step.get("tool") == "check_audit_rule":
            result = step.get("result", "")
            if isinstance(result, str):
                audit_results.append(result)

    if not audit_results:
        return True, "", ""

    # 简单一致性检查: 是否同时出现 "通过" 和 "不通过"
    has_pass = any("通过" in r and "不通过" not in r for r in audit_results)
    has_fail = any("不通过" in r for r in audit_results)

    # 如果有审计结果但没有调用 submit_all_audit_results
    has_submit = any(
        isinstance(step, dict) and step.get("tool") == "submit_all_audit_results"
        for step in steps
    )

    if audit_results and not has_submit:
        return (
            False,
            "审计检查完成但未提交汇总结果",
            "请使用 submit_all_audit_results 工具提交审计汇总结果。",
        )

    return True, "", ""


def check_calculation_verified(event: HookEvent) -> tuple[bool, str, str]:
    """
    检查数值计算是否使用了 calculator 工具。

    规则: 如果最终答案中包含数值比较 (> < = ≥ ≤)，
    检查 runtime_steps 是否使用了 calculator 系列工具。
    """
    context = event.context or {}
    final_answer = context.get("final_answer", "")

    # 检查最终答案中是否有数值比较/计算描述
    numeric_indicators = ["超出", "不足", "合计", "差额", "超标", "节余", "超过预算"]
    has_numeric = any(ind in final_answer for ind in numeric_indicators)

    if not has_numeric:
        return True, "", ""

    # 检查是否使用了 calculator 工具
    steps = event.runtime_steps or []
    calculator_tools = {"arithmetic", "numeric_compare", "sum_values",
                        "calculate_ratio", "date_diff"}
    used_calculator = any(
        isinstance(step, dict) and step.get("tool") in calculator_tools
        for step in steps
    )

    if not used_calculator:
        return (
            False,
            "最终答案包含数值比较但未使用 calculator 工具验证",
            "请使用 calculator 系列工具 (arithmetic/numeric_compare/sum_values) 验证数值计算结果的准确性。",
        )

    return True, "", ""


def check_memory_compliance(event: HookEvent) -> tuple[bool, str, str]:
    """
    检查 Agent 回复是否违反记忆中的用户显式偏好。

    可选检查 — 默认不启用 (不在 QualityGate 默认 checks 中)。
    SaaS 集成方可通过 QualityGate(checks=[check_memory_compliance]) 启用。

    逻辑: 从 ContextVar 读取当前记忆内容，
    检查 final_answer 是否违反显式偏好 (关键词匹配)。

    支持的偏好模式:
    - "使用表格格式" / "用表格" → 回复应包含 "|" (Markdown 表格)
    - "使用中文" / "用中文回复" → 回复不应全是 ASCII
    - "不要" + 关键词 → 回复不应包含该关键词
    """
    context = event.context or {}
    final_answer = context.get("final_answer", "")
    if not final_answer:
        return True, "", ""

    # 从 RequestContext 读取记忆
    try:
        from core.context import current_request
        ctx = current_request.get()
        if not ctx or not ctx.memory_store:
            return True, "", ""

        memory_content, _ = ctx.memory_store.build_memory_prompt(ctx.tenant_id, ctx.user_id)
    except Exception:
        return True, "", ""

    if not memory_content:
        return True, "", ""

    issues: list[str] = []

    # 偏好: 表格格式
    table_keywords = ["使用表格格式", "用表格", "以表格形式", "表格输出"]
    wants_table = any(kw in memory_content for kw in table_keywords)
    if wants_table and "|" not in final_answer:
        issues.append("记忆中要求使用表格格式，但回复中未包含表格")

    # 偏好: 中文回复
    chinese_keywords = ["使用中文", "用中文回复", "中文回答"]
    wants_chinese = any(kw in memory_content for kw in chinese_keywords)
    if wants_chinese and final_answer.isascii() and len(final_answer) > 20:
        issues.append("记忆中要求使用中文回复，但回复全为英文")

    # 偏好: "不要" 禁止模式
    import re
    deny_patterns = re.findall(r"不要(?:使用|用)?(.{2,10}?)(?:[，。,.\s]|$)", memory_content)
    for denied in deny_patterns:
        denied = denied.strip()
        if denied and denied in final_answer:
            issues.append(f"记忆中要求不要使用「{denied}」，但回复中包含该内容")

    if issues:
        correction = (
            "请根据用户偏好修改回复:\n"
            + "\n".join(f"- {issue}" for issue in issues)
        )
        return False, "; ".join(issues), correction

    return True, "", ""


# ── Quality Gate Hook ──

# 用于追踪自迭代次数 (per-session)
# 格式: {session_key: (count, last_access_time)}
_correction_counts: dict[str, tuple[int, float]] = {}
_CORRECTION_TTL_S = 3600  # 1 小时后过期


def quality_gate_hook(event: HookEvent) -> HookResult:
    """
    agent_stop hook: 质量门。

    - 通过 → allow (Agent 正常结束)
    - 不通过 + 未超限 → block + 修正消息 (Agent 继续迭代)
    - 不通过 + 已超限 → allow (降级放行，避免无限循环)
    """
    import time as _time

    now = _time.time()

    # 安全清理: 过期条目 + 超限裁剪
    if len(_correction_counts) > 50:
        # 先清过期条目，再 LRU 裁剪
        expired = [k for k, (_, ts) in _correction_counts.items() if now - ts > _CORRECTION_TTL_S]
        for k in expired:
            _correction_counts.pop(k, None)
        if len(_correction_counts) > 50:
            keys = list(_correction_counts.keys())
            for k in keys[:-50]:
                _correction_counts.pop(k, None)

    session_key = f"{event.user_id}:{event.session_id}"

    # 检查自迭代次数 (含 TTL 过期检查)
    entry = _correction_counts.get(session_key)
    current_count = 0
    if entry:
        count, ts = entry
        if now - ts > _CORRECTION_TTL_S:
            _correction_counts.pop(session_key, None)
        else:
            current_count = count
    if current_count >= MAX_SELF_CORRECTIONS:
        logger.warning(
            f"Quality gate: max corrections ({MAX_SELF_CORRECTIONS}) reached, "
            f"allowing despite issues"
        )
        # 清理计数
        _correction_counts.pop(session_key, None)
        return HookResult(action="allow")

    gate = QualityGate()
    result = gate.evaluate(event)

    if result.passed:
        # 清理计数
        _correction_counts.pop(session_key, None)
        return HookResult(action="allow")

    # 不通过 → block + 修正提示
    _correction_counts[session_key] = (current_count + 1, now)

    correction_msg = (
        "[质量检查未通过]\n"
        "发现以下问题:\n"
        + "\n".join(f"- {issue}" for issue in result.issues)
        + "\n\n请进行以下修正:\n"
        + "\n".join(f"- {corr}" for corr in result.corrections)
    )

    logger.info(
        f"Quality gate blocked: {len(result.issues)} issues, "
        f"correction #{current_count + 1}/{MAX_SELF_CORRECTIONS}"
    )

    return HookResult(action="block", message=correction_msg)


def reset_correction_count(session_key: str) -> None:
    """重置自迭代计数 (用于测试或会话结束时清理)。"""
    _correction_counts.pop(session_key, None)


# ── #43: 语义质量检查 (独立 async hook，guardian_enabled 时注册) ──

# 复用 quality_gate_hook 的自迭代计数器，避免两个 hook 各自计数导致双倍修正
_SEMANTIC_CHECK_MIN_ANSWER_LEN = 50
_SEMANTIC_CHECK_MIN_TOOLS = 1


async def semantic_quality_hook(event: HookEvent) -> HookResult:
    """
    agent_stop async hook: LLM 语义质量检查。

    检查 Agent 回复是否与工具结果一致，检测幻觉。
    仅在 guardian_enabled=True 时注册，fail-open (出错则放行)。
    """
    import asyncio
    import time as _time

    final_answer = event.context.get("final_answer", "")
    if not final_answer or len(final_answer) < _SEMANTIC_CHECK_MIN_ANSWER_LEN:
        return HookResult(action="allow")

    # 提取工具调用历史
    tool_steps = [s for s in event.runtime_steps if s.get("tool")]
    if len(tool_steps) < _SEMANTIC_CHECK_MIN_TOOLS:
        return HookResult(action="allow")

    # 自迭代超限检查 (复用同一计数器)
    session_key = f"{event.user_id}:{event.session_id}"
    entry = _correction_counts.get(session_key)
    if entry:
        count, ts = entry
        if _time.time() - ts < _CORRECTION_TTL_S and count >= MAX_SELF_CORRECTIONS:
            return HookResult(action="allow")

    # 构建工具结果摘要 (最近 5 个)
    tool_summaries = []
    for step in tool_steps[-5:]:
        result_preview = str(step.get("result", ""))[:150]
        tool_summaries.append(f"- {step['tool']}: {result_preview}")

    try:
        from dependencies import get_llm_client
        from config import settings

        # 使用 Guardian LLM 配置 (可能是更便宜的模型)
        llm = get_llm_client()
        # 如果有独立 Guardian 配置，构建专用 client
        if settings.guardian_model and settings.guardian_base_url:
            from core.llm_client import LLMGatewayClient, LLMClientConfig
            llm = LLMGatewayClient(LLMClientConfig(
                base_url=settings.guardian_base_url or settings.llm_base_url,
                model=settings.guardian_model or settings.llm_model,
                api_key=settings.guardian_api_key or settings.llm_api_key,
                max_retries=0,
            ))

        prompt = (
            "检查 AI 回复的事实准确性。只关注以下两点:\n"
            "1. 回复中的具体数据/结论是否能在工具结果中找到依据？\n"
            "2. 回复中是否有工具结果中不存在的捏造信息？\n\n"
            f"工具返回的结果:\n{''.join(tool_summaries)}\n\n"
            f"AI 回复:\n{final_answer[:500]}\n\n"
            "如果回复准确，只输出: PASS\n"
            "如果发现问题，输出: FAIL|具体哪句话有问题|应该如何修正"
        )

        resp = await asyncio.wait_for(
            llm.chat_completion(
                messages=[
                    {"role": "system", "content": "你是事实核查器。只判断回复是否与工具结果一致。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=150,
                temperature=0.2,
            ),
            timeout=float(settings.guardian_timeout_s),
        )

        if not resp.content:
            return HookResult(action="allow")

        text = resp.content.strip()
        if text.upper().startswith("PASS"):
            return HookResult(action="allow")

        # FAIL — 提取修正建议
        parts = text.split("|", 2)
        if len(parts) >= 3:
            issue = parts[1].strip()
            correction = parts[2].strip()
        elif len(parts) == 2:
            issue = parts[1].strip()
            correction = "请检查回复中的事实准确性"
        else:
            issue = text[:200]
            correction = "请核对工具返回的结果，确保回复内容有据可查"

        logger.info(f"Semantic check failed: {issue[:100]}")
        return HookResult(
            action="block",
            message=f"[语义检查] 发现事实性问题: {issue}\n修正建议: {correction}",
        )

    except Exception as e:
        # fail-open: 出错放行
        logger.debug(f"Semantic quality check skipped (fail-open): {e}")
        return HookResult(action="allow")
