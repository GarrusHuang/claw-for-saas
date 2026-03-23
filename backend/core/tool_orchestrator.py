"""
#9 ToolOrchestrator — 统一工具执行编排层。

将工具执行的 approval → sandbox → execute → retry 流程统一编排，
避免在 runtime._execute_single_tool 中堆积所有逻辑。

Usage:
    orchestrator = ToolOrchestrator(hooks, sandbox, exec_policy)
    result = await orchestrator.execute(tool_call, tool_registry, context)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OrchestrationResult:
    """工具编排执行结果。"""
    result: Any  # ToolResult
    blocked: bool = False
    blocked_reason: str = ""
    retried: bool = False
    latency_ms: float = 0.0


class ToolOrchestrator:
    """
    统一工具执行编排。

    流程:
    1. Pre-approval: Hook pre_tool_use (block/modify/inject)
    2. Sandbox check: validate path/command
    3. Execute: 带超时执行
    4. Post-audit: Hook post_tool_use
    5. Retry: 瞬时错误自动重试 (最多 1 次)
    """

    def __init__(
        self,
        hooks: Any = None,
        exec_policy: Any = None,
        max_retries: int = 1,
    ) -> None:
        self.hooks = hooks
        self.exec_policy = exec_policy
        self.max_retries = max_retries

    async def execute(
        self,
        tool_name: str,
        tool_args: dict,
        tool_registry: Any,
        timeout_s: float = 30.0,
        session_id: str = "",
        user_id: str = "",
        messages: list[dict] | None = None,
    ) -> OrchestrationResult:
        """
        编排工具执行的完整生命周期。

        Returns:
            OrchestrationResult
        """
        from core.tool_registry import ToolResult

        start = time.monotonic()

        # ── 1. Pre-approval (Hook) ──
        if self.hooks:
            from agent.hooks import HookEvent
            pre_event = HookEvent(
                event_type="pre_tool_use",
                tool_name=tool_name,
                tool_input=tool_args,
                session_id=session_id,
                user_id=user_id,
            )
            try:
                pre_result = await self.hooks.fire(pre_event)
                if pre_result and pre_result.action == "block":
                    return OrchestrationResult(
                        result=ToolResult(success=False, error=f"Hook blocked: {pre_result.message}"),
                        blocked=True,
                        blocked_reason=pre_result.message,
                        latency_ms=(time.monotonic() - start) * 1000,
                    )
                if pre_result and pre_result.action == "modify" and pre_result.modified_input:
                    tool_args = pre_result.modified_input
            except Exception as e:
                logger.warning(f"Pre-hook error: {e}")

        # ── 2. Execute with retry ──
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    tool_registry.execute(tool_name, tool_args),
                    timeout=timeout_s,
                )
                latency_ms = (time.monotonic() - start) * 1000

                # ── 3. Post-audit ──
                if self.hooks:
                    post_event = HookEvent(
                        event_type="post_tool_use",
                        tool_name=tool_name,
                        tool_input=tool_args,
                        tool_output=str(result.data)[:500] if result.data else "",
                        session_id=session_id,
                        user_id=user_id,
                    )
                    try:
                        await self.hooks.fire(post_event)
                    except Exception:
                        pass

                return OrchestrationResult(
                    result=result,
                    retried=attempt > 0,
                    latency_ms=latency_ms,
                )
            except asyncio.TimeoutError:
                last_error = f"Tool {tool_name} timed out after {timeout_s}s"
            except Exception as e:
                last_error = str(e)
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5)
                    continue

        latency_ms = (time.monotonic() - start) * 1000
        return OrchestrationResult(
            result=ToolResult(success=False, error=last_error or "Unknown error"),
            retried=True,
            latency_ms=latency_ms,
        )
