"""
AgenticRuntime: ReAct 风格 LLM+Tool 迭代循环引擎。

这是整个 Agent Harness 的核心组件，借鉴 agent-engine 的 AgenticRuntime 模式。

循环流程:
    1. 发送 system_prompt + user_message 到 LLM (流式)
    2. 解析响应中的 tool_calls（ToolCallParser 双模式）
    3. 执行工具（只读工具并行，写入工具串行）
    4. 将工具结果追加到 messages
    5. 重复直到 LLM 产出 final_answer 或达到 max_iterations

关键设计:
    - Runtime is domain-agnostic — no business logic
    - It is a pure Agent execution engine
    - Business logic is injected via system prompt and tools
    - 流式输出: 通过 EventBus 发射 text_delta 事件，前端逐字显示
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .event_bus import EventBus
from .llm_client import LLMGatewayClient, LLMResponse, TokenUsage
from .token_estimator import estimate_messages_tokens
from .tool_protocol import ParsedToolCall, ToolCallParser
from .tool_registry import ToolRegistry, ToolResult

logger = logging.getLogger(__name__)


class StepType(str, Enum):
    """Runtime 步骤类型"""
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    OBSERVATION = "observation"
    FINAL_ANSWER = "final_answer"
    ERROR = "error"


@dataclass
class RuntimeStep:
    """单步执行记录"""
    step_type: StepType
    content: str = ""
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_result: Any = None
    latency_ms: float = 0.0
    iteration: int = 0


@dataclass
class RuntimeConfig:
    """Runtime 配置"""
    max_iterations: int = 10
    max_tokens_per_turn: int = 4096
    tool_call_timeout_s: float = 30.0
    parallel_tool_calls: bool = True
    temperature: float | None = None  # 覆盖 LLM 默认值
    max_tool_result_chars: int = 3000  # 单个工具结果最大字符数 (0=不限制)
    context_budget_tokens: int = 28000  # messages 数组最大 token 预算


@dataclass
class RuntimeResult:
    """Runtime 执行结果"""
    final_answer: str
    steps: list[RuntimeStep] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    iterations: int = 0
    max_iterations_reached: bool = False
    error: str | None = None
    thinking: str = ""  # Qwen3 thinking 内容汇总

    @property
    def tool_call_count(self) -> int:
        return sum(1 for s in self.steps if s.step_type == StepType.TOOL_CALL)

    @property
    def tool_history(self) -> list[dict]:
        """返回工具调用历史（用于 Memory 系统经验提取）。"""
        return [
            {
                "tool": s.tool_name,
                "args": s.tool_args,
                "result": s.tool_result,
                "iteration": s.iteration,
            }
            for s in self.steps
            if s.step_type == StepType.TOOL_CALL
        ]


class AgenticRuntime:
    """
    ReAct 风格 LLM+Tool 迭代循环引擎。

    Usage:
        runtime = AgenticRuntime(
            llm_client=llm_client,
            tool_registry=registry,
            tool_parser=ToolCallParser(),
        )
        result = await runtime.run(system_prompt, user_message)
        print(result.final_answer)
        print(f"Used {result.iterations} iterations, {result.tool_call_count} tool calls")
    """

    def __init__(
        self,
        llm_client: LLMGatewayClient,
        tool_registry: ToolRegistry,
        tool_parser: ToolCallParser | None = None,
        config: RuntimeConfig | None = None,
        event_bus: EventBus | None = None,
        trace_id: str | None = None,
        hooks: Any | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.tool_parser = tool_parser or ToolCallParser()
        self.config = config or RuntimeConfig()
        self.event_bus = event_bus
        self.trace_id = trace_id or ""
        self.hooks = hooks  # Optional HookRegistry
        self._steps: list[RuntimeStep] = []
        self._accumulated_usage = TokenUsage()
        self._thinking_parts: list[str] = []

    async def run(
        self,
        system_prompt: str,
        user_message: str,
        initial_messages: list[dict] | None = None,
    ) -> RuntimeResult:
        """
        执行 ReAct 循环。

        Args:
            system_prompt: 系统提示（L1+L2+L3+L4 合并后）
            user_message: 用户任务消息
            initial_messages: 可选的初始对话历史（多轮场景）

        Returns:
            RuntimeResult 包含 final_answer、steps、token_usage 等
        """
        messages = self._build_initial_messages(system_prompt, user_message, initial_messages)

        self._emit("agent_progress", {"status": "started", "max_iterations": self.config.max_iterations})

        for iteration in range(self.config.max_iterations):
            logger.info(
                f"ReAct iteration {iteration + 1}/{self.config.max_iterations}",
                extra={"trace_id": self.trace_id},
            )

            # ─── 0. 上下文预算检查 + 中间压缩 ───
            messages = await self._compact_messages(messages)

            # ─── 1. 调用 LLM (流式) ───
            try:
                llm_response = await self._streaming_llm_call(
                    messages=messages,
                    iteration=iteration,
                )
            except Exception as e:
                logger.error(f"LLM call failed at iteration {iteration + 1}: {e}")
                self._steps.append(RuntimeStep(
                    step_type=StepType.ERROR,
                    content=str(e),
                    iteration=iteration,
                ))
                return self._build_result(
                    final_answer=f"[LLM Error] {e}",
                    iterations=iteration + 1,
                    error=str(e),
                )

            # 更新 token 用量
            self._accumulated_usage.prompt_tokens += llm_response.usage.prompt_tokens
            self._accumulated_usage.completion_tokens += llm_response.usage.completion_tokens
            self._accumulated_usage.total_tokens += llm_response.usage.total_tokens

            # 记录 LLM 步骤
            self._steps.append(RuntimeStep(
                step_type=StepType.LLM_CALL,
                content=llm_response.content or "",
                latency_ms=llm_response.latency_ms,
                iteration=iteration,
            ))

            # ─── 2. 解析工具调用 ───
            parsed = self.tool_parser.parse(llm_response.to_message_dict())

            # 收集 thinking
            if parsed.thinking:
                self._thinking_parts.append(parsed.thinking)
                # 发射 thinking 事件让前端显示 Agent 思考过程
                self._emit("thinking", {"content": parsed.thinking, "iteration": iteration + 1})

            # ─── 3. 判断是否为 final answer ───
            if parsed.is_final_answer:
                logger.info(
                    f"Final answer at iteration {iteration + 1}",
                    extra={"trace_id": self.trace_id},
                )

                # ── Phase 11: Quality Gate (Stop Hook) ──
                if self.hooks:
                    from agent.hooks import HookEvent
                    from core.context import current_user_id, current_session_id
                    stop_event = HookEvent(
                        event_type="agent_stop",
                        session_id=current_session_id.get(""),
                        user_id=current_user_id.get("anonymous"),
                        runtime_steps=[
                            {"tool": s.tool_name, "args": s.tool_args, "result": s.tool_result}
                            for s in self._steps if s.tool_name
                        ],
                        context={
                            "final_answer": parsed.content,
                            "iterations": iteration + 1,
                        },
                    )
                    stop_result = await self.hooks.fire(stop_event)
                    if stop_result.action == "block":
                        # Ralph Wiggum: 注入修正提示，继续迭代
                        logger.info(
                            f"Quality gate blocked at iteration {iteration + 1}, self-correcting",
                            extra={"trace_id": self.trace_id},
                        )
                        messages.append({
                            "role": "user",
                            "content": stop_result.message,
                        })
                        self._emit("agent_progress", {
                            "status": "self_correction",
                            "iteration": iteration + 1,
                            "reason": stop_result.message[:200],
                        })
                        continue  # 继续 ReAct 循环

                self._steps.append(RuntimeStep(
                    step_type=StepType.FINAL_ANSWER,
                    content=parsed.content,
                    iteration=iteration,
                ))
                self._emit("agent_progress", {
                    "status": "completed",
                    "iterations": iteration + 1,
                    "tool_calls": self._count_tool_calls(),
                })
                return self._build_result(
                    final_answer=parsed.content,
                    iterations=iteration + 1,
                )

            # ─── 4. 执行工具调用 ───
            if parsed.tool_calls:
                self._emit("agent_progress", {
                    "status": "calling_tools",
                    "iteration": iteration + 1,
                    "tools": [tc.name for tc in parsed.tool_calls],
                })

                observations = await self._execute_tool_calls(parsed.tool_calls, iteration)

                # ─── 5. 构建消息追加 ───
                # 追加 assistant 消息（含 tool_calls）
                assistant_msg = self._build_assistant_message(llm_response, parsed)
                messages.append(assistant_msg)

                # 追加每个工具的结果 (截断过长内容)
                for tc, obs in zip(parsed.tool_calls, observations):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": obs.to_json(max_chars=self.config.max_tool_result_chars),
                    })

                continue

            # 没有 tool calls 也不是 final answer（异常情况）
            logger.warning(f"No tool calls and no final answer at iteration {iteration + 1}")
            return self._build_result(
                final_answer=parsed.content or llm_response.content or "",
                iterations=iteration + 1,
            )

        # ─── Max iterations 达到 ───
        logger.warning(
            f"Max iterations ({self.config.max_iterations}) reached",
            extra={"trace_id": self.trace_id},
        )
        last_content = self._steps[-1].content if self._steps else ""
        self._emit("agent_progress", {
            "status": "max_iterations_reached",
            "iterations": self.config.max_iterations,
        })
        return self._build_result(
            final_answer=last_content,
            iterations=self.config.max_iterations,
            max_iterations_reached=True,
        )

    async def _streaming_llm_call(
        self,
        messages: list[dict],
        iteration: int,
    ) -> LLMResponse:
        """
        流式调用 LLM，逐 chunk 发射 text_delta 事件。

        对于包含工具调用的响应，文本部分也会流式发射。
        完成后组装成完整的 LLMResponse 返回给 ReAct 循环解析。
        """
        import json as _json

        start = time.monotonic()

        # 累积缓冲
        content_parts: list[str] = []
        tool_calls_buf: dict[int, dict] = {}  # index → {id, name, arguments_parts}
        finish_reason = None
        usage_data: dict = {}

        # 是否为 final answer 迭代（无工具调用）— 控制流式粒度
        has_tool_calls = False

        # 用于 text_delta 去抖的小缓冲
        _text_buf = ""
        _FLUSH_THRESHOLD = 2  # 每 N 个字符刷新一次

        async def _flush_text(force: bool = False) -> None:
            nonlocal _text_buf
            if _text_buf and (force or len(_text_buf) >= _FLUSH_THRESHOLD):
                self._emit("text_delta", {
                    "content": _text_buf,
                    "iteration": iteration + 1,
                })
                _text_buf = ""

        try:
            async for chunk in self.llm_client.chat_completion_stream(
                messages=messages,
                tools=self.tool_registry.get_schemas() or None,
                max_tokens=self.config.max_tokens_per_turn,
                temperature=self.config.temperature,
            ):
                choices = chunk.get("choices", [])
                if not choices:
                    # 可能是 usage-only 的最后一个 chunk
                    if "usage" in chunk:
                        usage_data = chunk["usage"]
                    continue

                delta = choices[0].get("delta", {})
                fr = choices[0].get("finish_reason")
                if fr:
                    finish_reason = fr

                # Usage 在某些 API 的最后 chunk 里
                if "usage" in chunk:
                    usage_data = chunk["usage"]

                # ── 文本内容 ──
                text = delta.get("content", "")
                if text:
                    content_parts.append(text)
                    # 流式发射文本 (不在工具调用迭代中也发)
                    if not has_tool_calls:
                        _text_buf += text
                        await _flush_text()

                # ── 工具调用 (流式累积) ──
                tc_deltas = delta.get("tool_calls", [])
                if tc_deltas:
                    has_tool_calls = True
                    for tc_delta in tc_deltas:
                        idx = tc_delta.get("index", 0)
                        if idx not in tool_calls_buf:
                            tool_calls_buf[idx] = {
                                "id": tc_delta.get("id", f"call_{idx}"),
                                "name": "",
                                "arguments_parts": [],
                            }
                        buf = tool_calls_buf[idx]
                        if tc_delta.get("id"):
                            buf["id"] = tc_delta["id"]
                        func = tc_delta.get("function", {})
                        if func.get("name"):
                            buf["name"] = func["name"]
                        if func.get("arguments"):
                            buf["arguments_parts"].append(func["arguments"])

            # 刷新剩余文本
            await _flush_text(force=True)

        except Exception as e:
            error_msg = str(e).lower()

            # 检测上下文溢出错误
            overflow_keywords = [
                "context length", "token limit", "input too long",
                "maximum context", "too many tokens", "context_length",
                "max_tokens", "exceeds the model", "prompt is too long",
            ]
            is_overflow = any(kw in error_msg for kw in overflow_keywords)

            if is_overflow:
                logger.warning(
                    f"Context overflow detected at iteration {iteration + 1}, "
                    f"compacting and retrying: {e}"
                )
                # 强制压缩
                compacted = await self._compact_messages(messages)
                if len(compacted) < len(messages):
                    # 压缩成功，用非流式重试一次
                    try:
                        return await self.llm_client.chat_completion(
                            messages=compacted,
                            tools=self.tool_registry.get_schemas() or None,
                            max_tokens=self.config.max_tokens_per_turn,
                            temperature=self.config.temperature,
                        )
                    except Exception as retry_e:
                        logger.error(f"Retry after compaction also failed: {retry_e}")
                        raise retry_e
                else:
                    # 无法进一步压缩
                    raise

            # 非溢出错误: 回退到非流式调用
            logger.warning(f"Streaming failed at iteration {iteration + 1}, falling back: {e}")
            return await self.llm_client.chat_completion(
                messages=messages,
                tools=self.tool_registry.get_schemas() or None,
                max_tokens=self.config.max_tokens_per_turn,
                temperature=self.config.temperature,
            )

        latency_ms = (time.monotonic() - start) * 1000

        # ── 组装完整响应 ──
        full_content = "".join(content_parts)

        # 组装 tool_calls
        assembled_tool_calls = None
        if tool_calls_buf:
            assembled_tool_calls = []
            for idx in sorted(tool_calls_buf.keys()):
                buf = tool_calls_buf[idx]
                args_str = "".join(buf["arguments_parts"])
                assembled_tool_calls.append({
                    "id": buf["id"],
                    "type": "function",
                    "function": {
                        "name": buf["name"],
                        "arguments": args_str,
                    },
                })

        return LLMResponse(
            content=full_content or None,
            tool_calls=assembled_tool_calls,
            finish_reason=finish_reason,
            usage=TokenUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            ),
            model=self.llm_client.config.model,
            latency_ms=latency_ms,
        )

    async def _execute_tool_calls(
        self,
        tool_calls: list[ParsedToolCall],
        iteration: int,
    ) -> list[ToolResult]:
        """
        执行工具调用。只读工具并行，写入工具串行。
        """
        results: list[ToolResult] = []

        if self.config.parallel_tool_calls:
            # 分离只读和写入工具
            read_only_calls = [tc for tc in tool_calls if self.tool_registry.is_read_only(tc.name)]
            write_calls = [tc for tc in tool_calls if not self.tool_registry.is_read_only(tc.name)]

            # 并行执行只读工具
            if read_only_calls:
                parallel_tasks = [
                    self._execute_single_tool(tc, iteration) for tc in read_only_calls
                ]
                parallel_results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
                for tc, result in zip(read_only_calls, parallel_results):
                    if isinstance(result, Exception):
                        result = ToolResult(success=False, error=str(result))
                    results.append(result)

            # 串行执行写入工具
            for tc in write_calls:
                result = await self._execute_single_tool(tc, iteration)
                results.append(result)
        else:
            # 全部串行
            for tc in tool_calls:
                result = await self._execute_single_tool(tc, iteration)
                results.append(result)

        return results

    async def _execute_single_tool(
        self,
        tool_call: ParsedToolCall,
        iteration: int,
    ) -> ToolResult:
        """执行单个工具调用（带超时 + Hook 集成）。"""
        from core.context import current_user_id, current_session_id

        start = time.monotonic()

        # ── PRE hook: 工具调用前检查 ──
        if self.hooks:
            from agent.hooks import HookEvent
            pre_event = HookEvent(
                event_type="pre_tool_use",
                tool_name=tool_call.name,
                tool_input=tool_call.arguments,
                session_id=current_session_id.get(""),
                user_id=current_user_id.get("anonymous"),
            )
            try:
                pre_result = await self.hooks.fire(pre_event)
            except Exception as e:
                logger.warning(f"Pre-hook error for {tool_call.name}: {e}")
                pre_result = None

            if pre_result and pre_result.action == "block":
                result = ToolResult(
                    success=False,
                    error=f"Hook blocked: {pre_result.message}",
                )
                latency_ms = (time.monotonic() - start) * 1000
                self._steps.append(RuntimeStep(
                    step_type=StepType.TOOL_CALL,
                    content=result.to_json(),
                    tool_name=tool_call.name,
                    tool_args=tool_call.arguments,
                    tool_result=result.error,
                    latency_ms=latency_ms,
                    iteration=iteration,
                ))
                self._emit("tool_executed", {
                    "tool": tool_call.name,
                    "success": False,
                    "blocked": True,
                    "latency_ms": round(latency_ms, 1),
                    "args_summary": self._summarize_args(tool_call.arguments),
                    "result_summary": f"Hook blocked: {pre_result.message}"[:300],
                })
                # Plan step tracking
                from core.context import current_plan_tracker
                tracker = current_plan_tracker.get(None)
                if tracker:
                    tracker.on_tool_executed(tool_call.name, success=False)
                logger.info(f"Tool blocked by hook: {tool_call.name} — {pre_result.message}")
                return result

            if pre_result and pre_result.action == "modify" and pre_result.modified_input:
                tool_call = ParsedToolCall(
                    id=tool_call.id,
                    name=tool_call.name,
                    arguments=pre_result.modified_input,
                )

        # ── 执行工具 ──
        try:
            result = await asyncio.wait_for(
                self.tool_registry.execute(tool_call.name, tool_call.arguments),
                timeout=self.config.tool_call_timeout_s,
            )
        except asyncio.TimeoutError:
            result = ToolResult(
                success=False,
                error=f"Tool {tool_call.name} timed out after {self.config.tool_call_timeout_s}s",
            )
        except Exception as e:
            result = ToolResult(success=False, error=str(e))

        latency_ms = (time.monotonic() - start) * 1000

        # ── POST hook: 工具调用后审计 ──
        if self.hooks:
            from agent.hooks import HookEvent
            post_event = HookEvent(
                event_type="post_tool_use",
                tool_name=tool_call.name,
                tool_input=tool_call.arguments,
                tool_output=result.to_json()[:500],
                session_id=current_session_id.get(""),
                user_id=current_user_id.get("anonymous"),
            )
            try:
                await self.hooks.fire(post_event)
            except Exception as e:
                logger.warning(f"Post-hook error for {tool_call.name}: {e}")

        # 记录步骤
        self._steps.append(RuntimeStep(
            step_type=StepType.TOOL_CALL,
            content=result.to_json(),
            tool_name=tool_call.name,
            tool_args=tool_call.arguments,
            tool_result=result.data if result.success else result.error,
            latency_ms=latency_ms,
            iteration=iteration,
        ))

        # 发射事件
        self._emit("tool_executed", {
            "tool": tool_call.name,
            "success": result.success,
            "latency_ms": round(latency_ms, 1),
            "args_summary": self._summarize_args(tool_call.arguments),
            "result_summary": self._summarize_result(result),
        })

        # Plan step tracking
        from core.context import current_plan_tracker
        tracker = current_plan_tracker.get(None)
        if tracker:
            tracker.on_tool_executed(tool_call.name, success=result.success)

        logger.info(
            f"Tool executed: {tool_call.name}",
            extra={
                "success": result.success,
                "latency_ms": f"{latency_ms:.0f}",
                "trace_id": self.trace_id,
            },
        )

        return result

    async def _compact_messages(self, messages: list[dict]) -> list[dict]:
        """
        上下文预算检查 + 中间消息压缩。

        策略:
        - 用 estimate_messages_tokens() 检查是否超预算
        - 未超 → 原样返回
        - 超出 → 保留 system(index 0) + user(index 1) + 最近 6 条消息
                  中间消息压缩为工具名摘要
        - Phase 15: 压缩前触发 pre_compact hook 保护关键信息
        """
        budget = self.config.context_budget_tokens
        if budget <= 0:
            return messages

        estimated = estimate_messages_tokens(
            messages,
            tools=self.tool_registry.get_schemas() or None,
        )

        if estimated <= budget:
            return messages

        # 需要压缩
        logger.warning(
            f"Context budget exceeded: {estimated} > {budget} tokens, compacting messages",
            extra={"trace_id": self.trace_id},
        )

        if len(messages) <= 8:
            # 消息太少，无法压缩
            return messages

        # 保留: system(0) + user(1) + 最近 6 条
        head = messages[:2]  # system + user
        tail = messages[-6:]  # 最近 6 条

        # 中间消息压缩为摘要
        middle = messages[2:-6]

        # ── Phase 15: PreCompact Hook — 保护关键信息 ──
        preserved_prefix = ""
        if self.hooks:
            from agent.hooks import HookEvent
            pre_compact_event = HookEvent(
                event_type="pre_compact",
                context={
                    "messages_to_compact": middle,
                    "budget": budget,
                    "estimated": estimated,
                },
            )
            pc_result = await self.hooks.fire(pre_compact_event)
            if pc_result.action == "modify" and pc_result.message:
                preserved_prefix = pc_result.message + "\n"

        summary_parts = []
        for msg in middle:
            role = msg.get("role", "unknown")
            if role == "tool":
                tool_call_id = msg.get("tool_call_id", "?")
                content_preview = str(msg.get("content", ""))[:80]
                summary_parts.append(f"[tool result: {tool_call_id}] {content_preview}")
            elif role == "assistant":
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    tool_names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                    summary_parts.append(f"[assistant called: {', '.join(tool_names)}]")
                else:
                    content_preview = str(msg.get("content", ""))[:100]
                    summary_parts.append(f"[assistant: {content_preview}]")
            else:
                content_preview = str(msg.get("content", ""))[:100]
                summary_parts.append(f"[{role}: {content_preview}]")

        summary_text = (
            preserved_prefix
            + "[Context Compacted — 以下是之前对话的摘要]\n"
            + "\n".join(summary_parts)
        )

        compacted = head + [{"role": "user", "content": summary_text}] + tail

        new_estimated = estimate_messages_tokens(
            compacted,
            tools=self.tool_registry.get_schemas() or None,
        )

        logger.info(
            f"Context compacted: {len(messages)} → {len(compacted)} messages, "
            f"{estimated} → {new_estimated} estimated tokens",
            extra={"trace_id": self.trace_id},
        )

        self._emit("agent_progress", {
            "status": "context_compacted",
            "original_messages": len(messages),
            "compacted_messages": len(compacted),
            "original_tokens": estimated,
            "compacted_tokens": new_estimated,
        })

        return compacted

    def _build_initial_messages(
        self,
        system_prompt: str,
        user_message: str,
        initial_messages: list[dict] | None,
    ) -> list[dict]:
        """构建初始消息列表。"""
        messages = [{"role": "system", "content": system_prompt}]

        if initial_messages:
            messages.extend(initial_messages)

        messages.append({"role": "user", "content": user_message})
        return messages

    def _build_assistant_message(
        self,
        llm_response: LLMResponse,
        parsed: Any,
    ) -> dict:
        """
        构建 assistant 消息（含 tool_calls）。

        关键: 使用 parsed.tool_calls 的 arguments（已由 _safe_parse_arguments 修复），
        而非 llm_response.tool_calls 的原始 arguments 字符串。
        vLLM 在下一轮会验证对话历史中的 JSON，畸形参数会导致 400 Bad Request。
        """
        import json as _json

        msg: dict[str, Any] = {"role": "assistant"}

        if llm_response.tool_calls and parsed.tool_calls:
            msg["content"] = llm_response.content or ""
            # 使用 parsed 的 arguments（已修复畸形 JSON），重建 tool_calls
            normalized_calls = []
            for i, tc_raw in enumerate(llm_response.tool_calls):
                if i < len(parsed.tool_calls):
                    # 使用已修复的 arguments dict → 序列化为合法 JSON
                    normalized_args = _json.dumps(
                        parsed.tool_calls[i].arguments, ensure_ascii=False
                    )
                else:
                    # 兜底: 多余的原始 tool call
                    normalized_args = tc_raw.get("function", {}).get("arguments", "{}")
                normalized_calls.append({
                    "id": tc_raw.get("id", parsed.tool_calls[i].id if i < len(parsed.tool_calls) else f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name": tc_raw.get("function", {}).get("name", ""),
                        "arguments": normalized_args,
                    },
                })
            msg["tool_calls"] = normalized_calls
        elif llm_response.tool_calls:
            # 有原生 tool_calls 但 parsed 为空（不应发生，兜底）
            msg["content"] = llm_response.content or ""
            msg["tool_calls"] = llm_response.tool_calls
        else:
            # Hermes XML 模式：需要构造 tool_calls 格式
            msg["content"] = parsed.raw_content or ""
            if parsed.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": _json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in parsed.tool_calls
                ]

        return msg

    def _build_result(
        self,
        final_answer: str,
        iterations: int,
        max_iterations_reached: bool = False,
        error: str | None = None,
    ) -> RuntimeResult:
        """构建最终结果。"""
        return RuntimeResult(
            final_answer=final_answer,
            steps=list(self._steps),
            token_usage=self._accumulated_usage,
            iterations=iterations,
            max_iterations_reached=max_iterations_reached,
            error=error,
            thinking="\n\n".join(self._thinking_parts) if self._thinking_parts else "",
        )

    def _count_tool_calls(self) -> int:
        return sum(1 for s in self._steps if s.step_type == StepType.TOOL_CALL)

    @staticmethod
    def _summarize_args(args: dict | None) -> dict[str, str]:
        """截断长参数值 (>200 字符) 用于 SSE 可视化。"""
        if not args:
            return {}
        summary: dict[str, str] = {}
        for k, v in args.items():
            s = str(v)
            summary[k] = s[:200] + "..." if len(s) > 200 else s
        return summary

    @staticmethod
    def _summarize_result(result: ToolResult) -> str:
        """截断结果文本 (>300 字符) 用于 SSE 可视化。"""
        if not result.success:
            text = result.error or "unknown error"
        else:
            text = str(result.data) if result.data is not None else ""
        return text[:300] + "..." if len(text) > 300 else text

    def _emit(self, event_type: str, data: dict) -> None:
        """通过 EventBus 发射事件。"""
        if self.event_bus:
            self.event_bus.emit(event_type, data)
