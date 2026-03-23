"""
3.4 Guardian — AI 驱动的风险评估。

在 pre_tool_use hook 链中对高风险工具调用进行 LLM 风险评估。
规则 Hook 作为第一道防线 (零成本)，Guardian 作为第二道 (仅评估规则放行的高风险调用)。

特点:
- 非高风险工具 → 直接放行 (不调 LLM)
- 高风险工具 → 调 LLM 评估 risk_score (0-100)
- risk_score >= threshold → 阻止
- 任何异常 → 阻止 (fail closed)
- 独立 LLM client (可配置用更便宜的模型)
- 对话上下文: 注入最近几轮对话摘要，辅助风险判定
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from agent.hooks import HookEvent, HookResult

if TYPE_CHECKING:
    from core.llm_client import LLMGatewayClient

logger = logging.getLogger(__name__)

# 高风险工具: 需要 Guardian 评估
_HIGH_RISK_TOOLS = frozenset({"run_command", "write_source_file", "apply_patch"})

_GUARDIAN_PROMPT = """\
你是一个安全审查系统。评估以下工具调用的风险。

## 评估维度

1. **破坏性** — 操作是否会删除、覆盖或损坏数据/文件/系统配置？
2. **越权性** — 操作是否超出用户 workspace 的合理范围？(如修改系统文件、访问其他用户数据)
3. **数据泄露** — 操作是否可能导致敏感信息外泄？(如读取密钥并写入日志/发送到外部)
4. **系统影响** — 操作是否影响系统可用性？(如耗尽资源、启动后台进程、修改网络配置)

## 量化判定规则

- 0-20: 完全安全 — 读取文件、运行测试、写入临时文件、常见开发操作
- 21-50: 低风险 — 创建/修改普通项目文件、运行标准构建命令
- 51-79: 中风险 — 覆盖重要配置文件、执行有副作用但可信的命令
- 80-100: 高风险 — 删除文件/数据、修改系统配置、执行未知脚本、网络攻击、访问密钥

## 用户意图降分原则

如果对话上下文表明用户主动要求执行该操作 (如"帮我删除这个文件"、"运行这个脚本")，
风险评分可适当降低 10-20 分，因为这是用户知情的有意行为。
但涉及系统级操作 (sudo、rm -rf /、修改 /etc) 的降分上限为 5 分。

## 输出格式 (严格)

只输出 JSON，不要其他内容:
{"risk_score": 0-100, "reason": "简短原因"}
"""


class GuardianAssessor:
    """Guardian AI 风险评估器。"""

    def __init__(
        self,
        llm_client: LLMGatewayClient,
        threshold: int = 80,
        timeout_s: float = 30.0,
    ) -> None:
        self._llm_client = llm_client
        self._threshold = threshold
        self._timeout_s = timeout_s

    async def assess(self, event: HookEvent) -> HookResult:
        """
        评估工具调用的风险。

        非高风险工具 → allow (不调 LLM)。
        高风险工具 → 调 LLM 评估。
        异常 → block (fail closed)。
        """
        # 非高风险工具，直接放行
        if event.tool_name not in _HIGH_RISK_TOOLS:
            return HookResult(action="allow")

        # 构建评估 prompt
        tool_desc = f"工具: {event.tool_name}\n参数: {json.dumps(event.tool_input, ensure_ascii=False)[:500]}"

        # 注入对话上下文 (如果有)
        recent_context = event.context.get("recent_messages", "")
        if recent_context:
            tool_desc += f"\n\n最近对话上下文:\n{recent_context}"

        try:
            resp = await asyncio.wait_for(
                self._llm_client.chat_completion(
                    messages=[
                        {"role": "system", "content": _GUARDIAN_PROMPT},
                        {"role": "user", "content": tool_desc},
                    ],
                    max_tokens=200,
                    temperature=0.1,
                ),
                timeout=self._timeout_s,
            )

            if not resp.content:
                logger.warning("Guardian: LLM returned empty content, blocking (fail closed)")
                return HookResult(action="block", message="Guardian: 评估无响应，安全起见阻止执行")

            # 解析 JSON
            content = resp.content.strip()
            # 容忍 markdown code block
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]) if len(lines) > 2 else content

            result = json.loads(content)
            risk_score = int(result.get("risk_score", 100))
            reason = result.get("reason", "未知原因")

            logger.info(
                f"Guardian: {event.tool_name} → risk_score={risk_score}, reason={reason}"
            )

            if risk_score >= self._threshold:
                return HookResult(
                    action="block",
                    message=(
                        f"Guardian 阻止: 风险评分 {risk_score}/100 (阈值 {self._threshold})。"
                        f"原因: {reason}。"
                        f"如果确需执行，请先调用 request_permissions 工具获取用户授权。"
                    ),
                )

            return HookResult(action="allow")

        except asyncio.TimeoutError:
            logger.warning(f"Guardian: LLM timeout ({self._timeout_s}s), blocking (fail closed)")
            return HookResult(action="block", message=f"Guardian: LLM 评估超时 ({self._timeout_s}s)，安全起见阻止执行")

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Guardian: Failed to parse LLM response: {e}, blocking (fail closed)")
            return HookResult(action="block", message=f"Guardian: 评估响应解析失败，安全起见阻止执行")

        except Exception as e:
            logger.warning(f"Guardian: Unexpected error: {e}, blocking (fail closed)")
            return HookResult(action="block", message=f"Guardian: 评估异常 ({e})，安全起见阻止执行")


def build_guardian_hook(settings) -> callable | None:
    """
    构建 Guardian hook 函数。

    guardian_enabled=False → return None
    否则创建独立 LLM client + GuardianAssessor，返回 assess 方法。
    """
    if not settings.guardian_enabled:
        return None

    from core.llm_client import LLMGatewayClient, LLMClientConfig

    # Guardian 用独立的 LLM 配置 (可以用更便宜的模型)
    guardian_config = LLMClientConfig(
        base_url=settings.guardian_base_url or settings.llm_base_url,
        model=settings.guardian_model or settings.llm_model,
        api_key=settings.guardian_api_key or settings.llm_api_key,
        timeout_s=settings.guardian_timeout_s,
        max_retries=1,  # Guardian 不重试，快速 fail closed
    )

    client = LLMGatewayClient(config=guardian_config)
    assessor = GuardianAssessor(
        llm_client=client,
        threshold=settings.guardian_risk_threshold,
        timeout_s=settings.guardian_timeout_s,
    )

    logger.info(
        f"Guardian enabled: model={guardian_config.model}, "
        f"threshold={settings.guardian_risk_threshold}"
    )

    return assessor.assess
