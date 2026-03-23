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
from pathlib import Path
from typing import Any, Optional

from .event_bus import EventBus
from .llm_client import LLMGatewayClient, LLMResponse, TokenUsage
from .token_estimator import estimate_messages_tokens
from .tool_protocol import ParsedToolCall, ToolCallParser
from .tool_registry import ToolRegistry, ToolResult
from .tracing import get_tracer

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
    """Runtime 配置 (A4: 动态上下文预算)"""
    max_iterations: int = 10
    max_tokens_per_turn: int = 4096
    tool_call_timeout_s: float = 30.0
    parallel_tool_calls: bool = True
    temperature: float | None = None  # 覆盖 LLM 默认值
    max_tool_result_chars: int = 0     # 单个工具结果最大字符数 (0=动态计算)
    context_budget_tokens: int = 0     # 0 = 动态计算 (A4: 4c)
    model_context_window: int = 32000  # 模型上下文窗口
    context_budget_ratio: float = 0.8  # 预算占窗口比例
    compress_threshold_ratio: float = 0.70  # 压缩触发阈值 (前移以留多阶段操作空间)
    context_budget_min: int = 16000    # 最低预算硬下限
    stream: bool = True                # 是否流式输出

    def get_effective_budget(self) -> int:
        """计算实际上下文预算 (4c: 动态预算)。"""
        if self.context_budget_tokens > 0:
            return self.context_budget_tokens
        ratio = max(0.1, min(1.0, self.context_budget_ratio))
        budget = int(self.model_context_window * ratio)
        return max(budget, self.context_budget_min)

    def get_effective_tool_result_chars(self) -> int:
        """
        计算实际工具结果字符上限。

        0 → 动态: 30% 上下文窗口 (chars ≈ tokens × 4), 最低 3000
        > 0 → 使用显式配置值

        对标 OpenClaw MAX_TOOL_RESULT_CONTEXT_SHARE = 0.3
        """
        if self.max_tool_result_chars > 0:
            return self.max_tool_result_chars
        # ~4 chars per token, 30% of context window
        dynamic = int(self.model_context_window * 4 * 0.3)
        return max(dynamic, 3000)


@dataclass
class RuntimeResult:
    """Runtime 执行结果"""
    final_answer: str
    steps: list[RuntimeStep] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    iterations: int = 0
    max_iterations_reached: bool = False
    error: str | None = None
    thinking: str = ""  # thinking 内容汇总
    compact_stats: dict | None = None  # 压缩累计统计 (4j)

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
        secret_redactor: Any | None = None,
        llm_tool_registry: ToolRegistry | None = None,
        message_inbox: asyncio.Queue | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self._llm_tool_registry = llm_tool_registry
        self.tool_parser = tool_parser or ToolCallParser()
        self.config = config or RuntimeConfig()
        self.event_bus = event_bus
        self.trace_id = trace_id or ""
        self.hooks = hooks  # Optional HookRegistry
        self._secret_redactor = secret_redactor  # Optional SecretRedactor
        self._steps: list[RuntimeStep] = []
        self._accumulated_usage = TokenUsage()
        self._thinking_parts: list[str] = []
        self._compact_stats: dict = {
            "count": 0,
            "total_ratio": 0.0,
            "stages": {1: 0, 2: 0, 3: 0},
            "overflow_retries": 0,
        }
        # ── 压缩 checkpoint: 压缩前消息快照 ──
        self._compaction_checkpoint: list[dict] | None = None
        # ── 中止标志: 客户端断开时停止循环 ──
        self._abort_requested = False
        # ── 重复检测: 防止 Agent 陷入工具调用死循环 ──
        self._tool_call_history: list[str] = []  # 每轮工具调用签名
        self._repetition_warned: bool = False
        # ── 工具结果缓存: 同一 run 内相同调用直接返回缓存 ──
        self._tool_result_cache: dict[str, ToolResult] = {}
        # ── 5A: 外层 overflow 重试计数 (最多 2 次) ──
        self._overflow_retries: int = 0
        # ── 5C: 连续无意义输出计数 + checkpoint 回退标志 ──
        self._consecutive_empty_count: int = 0
        self._checkpoint_rolled_back: bool = False
        # ── 3.3: 外部消息收件箱 (子 Agent send_to_subagent) ──
        self._message_inbox = message_inbox

    def request_abort(self) -> None:
        """Request the runtime to abort the ReAct loop at the next iteration."""
        self._abort_requested = True
        logger.info("Abort requested for runtime", extra={"trace_id": self.trace_id})

    def _get_llm_schemas(self) -> list[dict] | None:
        """返回发给 LLM 的工具 schema (延迟模式下只含核心工具)。"""
        reg = self._llm_tool_registry or self.tool_registry
        return reg.get_schemas() or None

    async def run(
        self,
        system_prompt: str,
        user_message: str | list,
        initial_messages: list[dict] | None = None,
    ) -> RuntimeResult:
        """
        执行 ReAct 循环。

        Args:
            system_prompt: 系统提示（L1+L2+L3+L4 合并后）
            user_message: 用户任务消息 (str 纯文本 | list 多模态 content blocks)
            initial_messages: 可选的初始对话历史（多轮场景）

        Returns:
            RuntimeResult 包含 final_answer、steps、token_usage 等
        """
        messages = self._build_initial_messages(system_prompt, user_message, initial_messages)

        self._emit("agent_progress", {"status": "started", "max_iterations": self.config.max_iterations})

        tracer = get_tracer()
        with tracer.start_as_current_span("runtime.react_loop") as span:
            span.set_attribute("max_iterations", self.config.max_iterations)

        for iteration in range(self.config.max_iterations):
            # ─── Abort check ───
            if self._abort_requested:
                logger.info("Abort requested, stopping ReAct loop", extra={"trace_id": self.trace_id})
                break

            # Also check EventBus abort flag
            if self.event_bus and getattr(self.event_bus, 'abort_requested', False):
                logger.info("EventBus abort requested, stopping ReAct loop", extra={"trace_id": self.trace_id})
                self._abort_requested = True
                break

            # ─── Check for injected messages ───
            if self.event_bus:
                injected = self.event_bus.drain_injected_messages()
                if injected:
                    for msg in injected:
                        messages.append({"role": "user", "content": msg["message"]})
                        logger.info(
                            f"Injected user message into ReAct loop at iteration {iteration + 1}",
                            extra={"trace_id": self.trace_id},
                        )
                        self._emit("agent_progress", {
                            "status": "message_injected",
                            "iteration": iteration + 1,
                        })

            # ─── 3.3: Check message_inbox (子 Agent send_to_subagent) ───
            if self._message_inbox:
                while not self._message_inbox.empty():
                    try:
                        inbox_msg = self._message_inbox.get_nowait()
                        messages.append({"role": "user", "content": inbox_msg})
                        logger.info(
                            f"Inbox message injected at iteration {iteration + 1}",
                            extra={"trace_id": self.trace_id},
                        )
                    except asyncio.QueueEmpty:
                        break

            logger.info(
                f"ReAct iteration {iteration + 1}/{self.config.max_iterations}",
                extra={"trace_id": self.trace_id},
            )

            # ─── 0. 上下文预算检查 + 中间压缩 ───
            messages = await self._compact_messages(messages)

            # ─── 1. 调用 LLM (流式) + 瞬时错误重试 ───
            llm_response = None
            llm_error = None
            for attempt in range(3):  # 最多 2 次重试 (共 3 次尝试)
                try:
                    llm_response = await self._streaming_llm_call(
                        messages=messages,
                        iteration=iteration,
                    )
                    break
                except Exception as e:
                    llm_error = e
                    if attempt < 2:
                        # 检查是否为可重试的瞬时错误
                        from core.errors import classify_error, ErrorCategory
                        category = classify_error(error_msg=str(e), exception=e)
                        retriable = category in (
                            ErrorCategory.RATE_LIMIT, ErrorCategory.OVERLOADED,
                            ErrorCategory.NETWORK,
                        )
                        if retriable:
                            wait = 2 ** attempt  # 1s, 2s
                            logger.warning(
                                f"LLM call failed (attempt {attempt + 1}/3, "
                                f"category={category.value}), retrying in {wait}s: {e}"
                            )
                            self._emit("agent_progress", {
                                "status": "llm_retry",
                                "attempt": attempt + 1,
                                "category": category.value,
                                "wait_s": wait,
                            })
                            await asyncio.sleep(wait)
                            continue
                    # Non-retriable or max attempts exhausted
                    break

            if llm_response is None:
                # ── 5A: overflow 特判 → 强制压缩后重试当前迭代 ──
                if llm_error is not None:
                    from core.errors import classify_error, ErrorCategory
                    category = classify_error(error_msg=str(llm_error), exception=llm_error)
                    if category == ErrorCategory.CONTEXT_OVERFLOW and self._overflow_retries < 2:
                        self._overflow_retries += 1
                        logger.warning(
                            f"Overflow detected at iteration {iteration + 1}, "
                            f"forcing compaction (retry {self._overflow_retries}/2)"
                        )
                        original_len = len(messages)
                        messages = await self._compact_messages(messages)
                        if len(messages) < original_len:
                            self._emit("agent_progress", {
                                "status": "overflow_compacted",
                                "iteration": iteration + 1,
                                "retry": self._overflow_retries,
                            })
                            continue  # 重试当前迭代 (不消耗 iteration 计数)

                logger.error(f"LLM call failed at iteration {iteration + 1}: {llm_error}")
                self._steps.append(RuntimeStep(
                    step_type=StepType.ERROR,
                    content=str(llm_error),
                    iteration=iteration,
                ))
                return self._build_result(
                    final_answer=f"[LLM Error] {llm_error}",
                    iterations=iteration + 1,
                    error=str(llm_error),
                )

            # 更新 token 用量
            self._accumulated_usage.prompt_tokens += llm_response.usage.prompt_tokens
            self._accumulated_usage.completion_tokens += llm_response.usage.completion_tokens
            self._accumulated_usage.total_tokens += llm_response.usage.total_tokens

            # ── 日志: 每轮 LLM 返回摘要 ──
            think_total = sum(len(p) for p in self._thinking_parts)
            content_len = len(llm_response.content or "")
            has_tc = bool(llm_response.tool_calls)
            logger.info(
                f"LLM response iter={iteration+1}: content={content_len}chars, "
                f"thinking={think_total}chars, tool_calls={has_tc}, "
                f"tokens={llm_response.usage.total_tokens}",
                extra={"trace_id": self.trace_id},
            )

            # 记录 LLM 步骤
            self._steps.append(RuntimeStep(
                step_type=StepType.LLM_CALL,
                content=llm_response.content or "",
                latency_ms=llm_response.latency_ms,
                iteration=iteration,
            ))

            # ─── 2. 解析工具调用 ───
            parsed = self.tool_parser.parse(llm_response.to_message_dict())

            # 收集 thinking (流式模式下已在流中处理，跳过重复)
            if parsed.thinking and not self.config.stream:
                self._thinking_parts.append(parsed.thinking)
                self._emit("thinking", {"content": parsed.thinking, "iteration": iteration + 1})

            # ─── 3. 判断是否为 final answer ───
            if parsed.is_final_answer:
                # ── 5C: 无意义输出检测 + checkpoint 回退 ──
                answer_text = (parsed.content or "").strip()
                is_meaningless = len(answer_text) < 5 and not parsed.tool_calls
                if is_meaningless:
                    self._consecutive_empty_count += 1
                    logger.warning(
                        f"Meaningless output at iteration {iteration + 1} "
                        f"(consecutive={self._consecutive_empty_count}): '{answer_text[:50]}'"
                    )
                    if (
                        self._consecutive_empty_count >= 3
                        and self._compaction_checkpoint
                        and not self._checkpoint_rolled_back
                    ):
                        self._checkpoint_rolled_back = True
                        messages = [msg.copy() for msg in self._compaction_checkpoint]
                        messages.append({
                            "role": "user",
                            "content": (
                                "[系统提示] 上下文被压缩导致部分信息丢失。"
                                "请基于当前可见的信息尽力回答用户的问题。"
                                "如果无法完整回答，请说明哪些信息不足。"
                            ),
                        })
                        logger.info(
                            f"Checkpoint rollback at iteration {iteration + 1}, "
                            f"restored {len(self._compaction_checkpoint)} messages"
                        )
                        self._emit("agent_progress", {
                            "status": "checkpoint_rollback",
                            "iteration": iteration + 1,
                        })
                        continue  # 使用 checkpoint 消息重试
                else:
                    self._consecutive_empty_count = 0

                logger.info(
                    f"Final answer at iteration {iteration + 1}",
                    extra={"trace_id": self.trace_id},
                )

                # ── Phase 11: Quality Gate (Stop Hook) ──
                if self.hooks:
                    from agent.hooks import HookEvent
                    from core.context import current_request
                    _ctx = current_request.get()
                    stop_event = HookEvent(
                        event_type="agent_stop",
                        session_id=_ctx.session_id if _ctx else "",
                        user_id=_ctx.user_id if _ctx else "anonymous",
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
                    content=parsed.content or "",
                    iteration=iteration,
                ))
                self._emit("agent_progress", {
                    "status": "completed",
                    "iterations": iteration + 1,
                    "tool_calls": self._count_tool_calls(),
                })
                return self._build_result(
                    final_answer=parsed.content or "",
                    iterations=iteration + 1,
                )

            # ─── 4. 执行工具调用 ───
            if parsed.tool_calls:
                # ── 4a. 重复检测: 检查是否陷入工具调用死循环 ──
                repetition = self._detect_repetition(parsed.tool_calls)
                if repetition == "force_stop":
                    logger.warning(
                        f"Repetition detected after warning at iteration {iteration + 1}, force stopping",
                        extra={"trace_id": self.trace_id},
                    )
                    self._emit("agent_progress", {
                        "status": "repetition_stopped",
                        "iterations": iteration + 1,
                    })
                    last_content = parsed.content or ""
                    if not last_content:
                        last_content = self._steps[-1].content if self._steps else ""
                    return self._build_result(
                        final_answer=last_content,
                        iterations=iteration + 1,
                        error="agent_repetition_detected",
                    )

                # 如果流式中已经逐个通知了工具名 (pending)，不重复发 calling_tools
                # 如果是非流式或没有提前通知过，则在此发出
                if not self._stream_tools_notified:
                    self._emit("agent_progress", {
                        "status": "calling_tools",
                        "iteration": iteration + 1,
                        "tools": [tc.name for tc in parsed.tool_calls],
                        "tool_details": [
                            {"name": tc.name,
                             "args": self._summarize_args(tc.arguments)}
                            for tc in parsed.tool_calls
                        ],
                    })
                    await asyncio.sleep(0)

                observations = await self._execute_tool_calls(parsed.tool_calls, iteration)

                # ─── 5. 构建消息追加 ───
                # 追加 assistant 消息（含 tool_calls）
                assistant_msg = self._build_assistant_message(llm_response, parsed)
                messages.append(assistant_msg)

                # 追加每个工具的结果 (A4-4a: 按比例分配总预算)
                per_tool_budgets = self._allocate_tool_budgets(
                    observations, self.config.get_effective_tool_result_chars(),
                )
                for tc, obs, budget in zip(parsed.tool_calls, observations, per_tool_budgets):
                    content = obs.to_json(max_chars=budget)
                    if self._secret_redactor:
                        content = self._secret_redactor.redact(content)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": content,
                    })

                # ── 4b. 重复警告: 注入提示让 Agent 停止重复 ──
                if repetition == "warn":
                    self._repetition_warned = True
                    logger.warning(
                        f"Tool call repetition detected at iteration {iteration + 1}, injecting warning",
                        extra={"trace_id": self.trace_id},
                    )
                    messages.append({
                        "role": "user",
                        "content": (
                            "[系统提示] 检测到你在重复调用相同的工具并获得相同的结果。"
                            "请不要再重复读取相同的文件或调用相同的工具。"
                            "请基于你已经获取到的信息，直接给出最终回复。"
                            "如果信息不完整，请说明缺少什么信息，而不是重复读取。"
                        ),
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
        self._stream_tools_notified = False  # 流式中是否已发过 calling_tools
        finish_reason = None
        usage_data: dict = {}

        # ── 流式文本/思考重复检测 ──
        _repetition_check_interval = 300  # 每累积 N 字检测一次
        _last_check_len = 0
        _last_think_check_len = 0
        _think_parts_local: list[str] = []  # 本次调用的 thinking 累积
        _stream_aborted = False

        # 是否为 final answer 迭代（无工具调用）— 控制流式粒度
        has_tool_calls = False

        # 用于 text_delta 去抖的小缓冲
        _text_buf = ""
        _FLUSH_THRESHOLD = 2  # 每 N 个字符刷新一次

        # <think> 标签流式拦截
        # vLLM thinking 模式: 省略 <think> 开始标签，直接流式输出思考内容，
        # 某个 chunk 中出现 </think> 后切换为正常文本。
        _in_think = self.llm_client.config.enable_thinking

        def _record_thinking(part: str) -> bool:
            """累积 thinking 内容并检测重复。返回 True 表示需要中断流。"""
            nonlocal _last_think_check_len, _stream_aborted
            _think_parts_local.append(part)
            self._thinking_parts.append(part)
            self._emit("thinking", {"content": part, "iteration": iteration + 1})

            total_think_len = sum(len(p) for p in _think_parts_local)
            if total_think_len - _last_think_check_len >= _repetition_check_interval:
                _last_think_check_len = total_think_len
                if total_think_len > 600:
                    full_think = "".join(_think_parts_local)
                    if self._detect_text_repetition(full_think):
                        logger.warning(
                            f"Thinking stream repetition detected at {total_think_len} chars, aborting",
                            extra={"trace_id": self.trace_id},
                        )
                        _stream_aborted = True
                        return True
            return False

        async def _flush_text(force: bool = False) -> None:
            """将缓冲文本通过 text_delta 事件实时流式发射给前端。"""
            nonlocal _text_buf
            if not _text_buf:
                return
            if not force and len(_text_buf) < _FLUSH_THRESHOLD:
                return
            self._emit("text_delta", {"content": _text_buf, "iteration": iteration + 1})
            _text_buf = ""

        try:
            async for chunk in self.llm_client.chat_completion_stream(
                messages=messages,
                tools=self._get_llm_schemas(),
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
                # DEBUG: 记录 delta 结构以排查 think 标签来源
                fr = choices[0].get("finish_reason")
                if fr:
                    finish_reason = fr

                # Usage 在某些 API 的最后 chunk 里
                if "usage" in chunk:
                    usage_data = chunk["usage"]

                # ── 文本内容 (含 <think> 标签拦截) ──
                text = delta.get("content", "")
                if text:
                    if not has_tool_calls:
                        if _in_think:
                            # 检测 </think> 结束标签
                            if "</think>" in text:
                                parts = text.split("</think>", 1)
                                think_part = parts[0]
                                if think_part:
                                    if _record_thinking(think_part):
                                        break
                                _in_think = False
                                # </think> 之后的正常文本
                                normal_text = parts[1].lstrip("\n")
                                if normal_text:
                                    content_parts.append(normal_text)
                                    _text_buf += normal_text
                                    await _flush_text()
                            else:
                                # 仍在 think 中
                                clean = text.replace("<think>", "")
                                if clean:
                                    if _record_thinking(clean):
                                        break
                        else:
                            # 正常文本，检测 <think> 开始标签
                            if "<think>" in text:
                                parts = text.split("<think>", 1)
                                if parts[0]:
                                    content_parts.append(parts[0])
                                    _text_buf += parts[0]
                                    await _flush_text(force=True)
                                _in_think = True
                                think_text = parts[1]
                                if "</think>" in think_text:
                                    tp = think_text.split("</think>", 1)
                                    if tp[0]:
                                        if _record_thinking(tp[0]):
                                            break
                                    _in_think = False
                                    normal = tp[1].lstrip("\n")
                                    if normal:
                                        content_parts.append(normal)
                                        _text_buf += normal
                                        await _flush_text()
                                elif think_text:
                                    if _record_thinking(think_text):
                                        break
                            else:
                                content_parts.append(text)
                                _text_buf += text
                                await _flush_text()
                    else:
                        content_parts.append(text)

                    # ── 流式文本重复检测 ──
                    total_len = sum(len(p) for p in content_parts)
                    if total_len - _last_check_len >= _repetition_check_interval:
                        _last_check_len = total_len
                        if total_len > 800:
                            full_text = "".join(content_parts)
                            if self._detect_text_repetition(full_text):
                                logger.warning(
                                    f"Streaming text repetition detected at {total_len} chars, aborting stream",
                                    extra={"trace_id": self.trace_id},
                                )
                                _stream_aborted = True
                                await _flush_text(force=True)
                                break

                # ── 工具调用 (流式累积) ──
                tc_deltas = delta.get("tool_calls", [])
                if tc_deltas:
                    if not has_tool_calls:
                        has_tool_calls = True
                        # 流式文本结束，flush 残余文本
                        await _flush_text(force=True)
                    for tc_delta in tc_deltas:
                        idx = tc_delta.get("index", 0)
                        if idx not in tool_calls_buf:
                            tool_calls_buf[idx] = {
                                "id": tc_delta.get("id", f"call_{idx}"),
                                "name": "",
                                "arguments_parts": [],
                                "_notified": False,
                            }
                        buf = tool_calls_buf[idx]
                        if tc_delta.get("id"):
                            buf["id"] = tc_delta["id"]
                        func = tc_delta.get("function", {})
                        if func.get("name"):
                            buf["name"] = func["name"]
                        if func.get("arguments"):
                            buf["arguments_parts"].append(func["arguments"])

                        # 一旦拿到工具名，立即通知前端显示 pending 状态
                        if buf["name"] and not buf["_notified"]:
                            buf["_notified"] = True
                            self._stream_tools_notified = True
                            self._emit("agent_progress", {
                                "status": "calling_tools",
                                "iteration": iteration + 1,
                                "tools": [buf["name"]],
                                "tool_details": [{"name": buf["name"], "args": {}}],
                            })

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
                self._compact_stats["overflow_retries"] += 1
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
                            tools=self._get_llm_schemas(),
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
                tools=self._get_llm_schemas(),
                max_tokens=self.config.max_tokens_per_turn,
                temperature=self.config.temperature,
            )

        latency_ms = (time.monotonic() - start) * 1000

        # ── 组装完整响应 ──
        full_content = "".join(content_parts)

        # 如果流被中断（文本/思考重复检测），截断到第一次重复之前的内容
        if _stream_aborted:
            if full_content:
                full_content = self._truncate_at_repetition(full_content)
                full_content += "\n\n[由于输出内容出现重复，已自动截断]"
            elif _think_parts_local:
                # thinking 流重复但没有正文内容 → 生成一个简短的结束回复
                full_content = "[思考过程出现重复，已自动中断。请基于已有信息回答。]"
                logger.warning(
                    "Thinking repetition forced early stop — injecting fallback answer",
                    extra={"trace_id": self.trace_id},
                )

        # 组装 tool_calls (流中断时丢弃，避免执行截断的参数)
        assembled_tool_calls = None
        if tool_calls_buf and not _stream_aborted:
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
        result_map: dict[str, ToolResult] = {}

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
                    result_map[tc.id] = result

            # 串行执行写入工具
            for tc in write_calls:
                result = await self._execute_single_tool(tc, iteration)
                result_map[tc.id] = result
        else:
            # 全部串行
            for tc in tool_calls:
                result = await self._execute_single_tool(tc, iteration)
                result_map[tc.id] = result

        # 按原始 tool_calls 顺序返回结果
        return [result_map[tc.id] for tc in tool_calls]

    def _tool_cache_key(self, tool_call: ParsedToolCall) -> str:
        """生成工具调用的缓存 key。"""
        import json as _json
        args_str = _json.dumps(tool_call.arguments, sort_keys=True, ensure_ascii=False)
        return f"{tool_call.name}::{args_str}"

    async def _execute_single_tool(
        self,
        tool_call: ParsedToolCall,
        iteration: int,
    ) -> ToolResult:
        """执行单个工具调用（带超时 + Hook 集成 + 只读缓存）。"""
        # ── 只读工具结果缓存: 相同调用不重复执行 ──
        is_read_only = self.tool_registry.is_read_only(tool_call.name)
        if is_read_only:
            cache_key = self._tool_cache_key(tool_call)
            cached = self._tool_result_cache.get(cache_key)
            if cached is not None:
                logger.info(
                    f"Tool cache hit: {tool_call.name} (returning cached result)",
                    extra={"trace_id": self.trace_id},
                )
                # 构造带提示的缓存结果
                hint = (
                    "[注意] 你已经调用过此工具且参数完全相同，结果不会改变。"
                    "请直接基于已有信息作答，不要重复调用。"
                )
                cache_result = ToolResult(
                    success=cached.success,
                    data={
                        "_cache_hit": True,
                        "_hint": hint,
                        **(cached.data if isinstance(cached.data, dict) else {"result": cached.data}),
                    } if cached.data else {"_cache_hit": True, "_hint": hint},
                    error=cached.error,
                )
                self._steps.append(RuntimeStep(
                    step_type=StepType.TOOL_CALL,
                    content="(cached)",
                    tool_name=tool_call.name,
                    tool_args=tool_call.arguments,
                    tool_result="(cached)",
                    latency_ms=0,
                    iteration=iteration,
                ))
                self._emit("tool_executed", {
                    "tool": tool_call.name,
                    "success": cached.success,
                    "cached": True,
                    "latency_ms": 0,
                    "args_summary": self._summarize_args(tool_call.arguments),
                    "result_summary": "(cached) " + (str(cached.data)[:200] if cached.data else ""),
                })
                return cache_result

        start = time.monotonic()
        tracer = get_tracer()
        _tool_span = tracer.start_as_current_span("runtime.tool_call")
        _tool_span_ctx = _tool_span.__enter__()
        _tool_span_ctx.set_attribute("tool.name", tool_call.name)
        _tool_span_ctx.set_attribute("tool.read_only", is_read_only)

        from core.context import current_request
        _ctx = current_request.get()

        # ── PRE hook: 工具调用前检查 ──
        if self.hooks:
            from agent.hooks import HookEvent
            pre_event = HookEvent(
                event_type="pre_tool_use",
                tool_name=tool_call.name,
                tool_input=tool_call.arguments,
                session_id=_ctx.session_id if _ctx else "",
                user_id=_ctx.user_id if _ctx else "anonymous",
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
                tracker = _ctx.plan_tracker if _ctx else None
                if tracker:
                    tracker.fail_current()
                logger.info(f"Tool blocked by hook: {tool_call.name} — {pre_result.message}")
                return result

            if pre_result and pre_result.action == "modify" and pre_result.modified_input:
                tool_call = ParsedToolCall(
                    id=tool_call.id,
                    name=tool_call.name,
                    arguments=pre_result.modified_input,
                )

        # ── 截断自动分段: write_source_file 有 path + 部分 content → 先写入再让 LLM 续写 ──
        if (
            tool_call.name == "write_source_file"
            and tool_call.arguments.get("path")
            and tool_call.arguments.get("content")
            and tool_call.arguments["content"].endswith(("...", '"'))
            and len(tool_call.arguments["content"]) > 500
        ):
            partial_content = tool_call.arguments["content"].rstrip('."')
            path = tool_call.arguments["path"]
            logger.info(
                f"Auto-chunking truncated write_source_file: path={path}, partial_len={len(partial_content)}",
                extra={"trace_id": self.trace_id},
            )
            # 写入已有部分
            chunk_args = {"path": path, "content": partial_content, "mode": "create"}
            try:
                await self.tool_registry.execute("write_source_file", chunk_args)
            except Exception as e:
                logger.warning(f"Auto-chunk write failed: {e}")
            result = ToolResult(
                success=True,
                data={
                    "auto_chunked": True,
                    "path": path,
                    "written_chars": len(partial_content),
                    "message": (
                        f"文件 {path} 已写入前 {len(partial_content)} 字符 (内容被截断)。"
                        f"请用 write_source_file(path='{path}', content='...剩余内容...', mode='patch') "
                        f"继续追加剩余内容。不要重复已写入的部分。"
                    ),
                },
            )
        else:
            # ── 正常执行工具 ──
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

        # ── 缓存只读工具的成功结果 ──
        if is_read_only and result.success:
            cache_key = self._tool_cache_key(tool_call)
            self._tool_result_cache[cache_key] = result

        # ── POST hook: 工具调用后审计 ──
        if self.hooks:
            from agent.hooks import HookEvent
            post_event = HookEvent(
                event_type="post_tool_use",
                tool_name=tool_call.name,
                tool_input=tool_call.arguments,
                tool_output=result.to_json()[:500],
                session_id=_ctx.session_id if _ctx else "",
                user_id=_ctx.user_id if _ctx else "anonymous",
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
            "result_summary": (
                self._secret_redactor.redact(self._summarize_result(result))
                if self._secret_redactor
                else self._summarize_result(result)
            ),
        })

        logger.info(
            f"Tool executed: {tool_call.name}",
            extra={
                "success": result.success,
                "latency_ms": f"{latency_ms:.0f}",
                "trace_id": self.trace_id,
            },
        )

        _tool_span_ctx.set_attribute("tool.success", result.success)
        _tool_span_ctx.set_attribute("tool.latency_ms", round(latency_ms, 1))
        _tool_span.__exit__(None, None, None)

        return result

    async def _compact_messages(self, messages: list[dict]) -> list[dict]:
        """
        A4: 多阶段渐进压缩 + 动态上下文预算。

        三阶段渐进降级:
        阶段 1 — 工具结果压缩: 截断旧的工具结果 (保留工具名+状态+关键数值)
        阶段 2 — 对话摘要: 窗口外的对话压缩为摘要
        阶段 3 — 元数据模式: 只保留 system + 最近 4 条 + 摘要 (最后兜底)
        """
        budget = self.config.get_effective_budget()
        if budget <= 0:
            return messages

        tools_schema = self._get_llm_schemas()
        estimated = estimate_messages_tokens(messages, tools=tools_schema)

        # 压缩阈值 = 预算 × compress_threshold_ratio (提前触发)
        compress_threshold = int(budget * self.config.compress_threshold_ratio)

        if estimated <= compress_threshold:
            return messages

        logger.warning(
            f"Context budget pressure: {estimated} > {compress_threshold} "
            f"(budget={budget}), starting compression",
            extra={"trace_id": self.trace_id},
        )

        original_estimated = estimated
        original_count = len(messages)
        stage_used = 0

        # 保存压缩前快照 (checkpoint) — 用于异常回退
        self._compaction_checkpoint = [msg.copy() for msg in messages]

        # 分类压缩触发原因
        reason = self._classify_compaction_reason(messages, original_estimated, budget)

        # ── 阶段 1: 工具结果压缩 (轻量) ──
        messages = self._stage1_truncate_tool_results(messages)
        estimated = estimate_messages_tokens(messages, tools=tools_schema)
        if estimated <= compress_threshold:
            stage_used = 1
            self._emit_compaction_event(
                stage_used, original_count, len(messages),
                original_estimated, estimated, reason=reason,
            )
            return messages

        # ── 阶段 2: 对话摘要 (中度) ──
        if len(messages) > 8:
            messages = await self._stage2_summarize_middle(
                messages, budget, estimated,
            )
            # 修复工具对
            messages = self._repair_tool_pairs(messages)
            estimated = estimate_messages_tokens(messages, tools=tools_schema)
            if estimated <= budget:
                stage_used = 2
                self._emit_compaction_event(
                    stage_used, original_count, len(messages),
                    original_estimated, estimated, reason=reason,
                )
                return messages

        # ── 阶段 3: 元数据模式 (重度兜底) ──
        messages = self._stage3_metadata_mode(messages)
        messages = self._repair_tool_pairs(messages)
        estimated = estimate_messages_tokens(messages, tools=tools_schema)
        if estimated <= budget:
            stage_used = 3
            self._emit_compaction_event(
                stage_used, original_count, len(messages),
                original_estimated, estimated, reason=reason,
            )
            return messages

        # ── 阶段 4: 逐条删最旧非系统消息 (最终兜底) ──
        # 对标 Codex: 逐条删最旧直到 fit
        # 保留 system[0] + 最后 2 条消息
        messages = self._stage4_drop_oldest(messages, budget, tools_schema)
        estimated = estimate_messages_tokens(messages, tools=tools_schema)
        stage_used = 4
        self._compact_stats["stages"][4] = self._compact_stats["stages"].get(4, 0) + 1

        self._emit_compaction_event(
            stage_used, original_count, len(messages),
            original_estimated, estimated, reason=reason,
        )
        return messages

    def _stage1_truncate_tool_results(self, messages: list[dict]) -> list[dict]:
        """
        阶段 1: 语义压缩旧的工具结果。

        保留最近 4 条 tool 消息不动，更早的 tool 消息替换为语义摘要。
        摘要保留: 工具名、参数、执行状态、关键结论。
        明确标注"此工具已执行过，重复调用返回相同结果"，防止模型重复调用。
        """
        result = []
        # 找出所有 tool 消息的索引
        tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        # 保护最近 4 条 tool 消息
        protected = set(tool_indices[-4:]) if len(tool_indices) > 4 else set(tool_indices)

        # 构建 tool_call_id → (tool_name, args) 的映射
        tool_call_map: dict[str, tuple[str, dict]] = {}
        for msg in messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    tc_id = tc.get("id", "")
                    name = fn.get("name", "unknown")
                    try:
                        import json as _json
                        args = _json.loads(fn.get("arguments", "{}"))
                    except Exception:
                        args = {}
                    tool_call_map[tc_id] = (name, args)

        for i, msg in enumerate(messages):
            if msg.get("role") == "tool" and i not in protected:
                content = str(msg.get("content", ""))
                if len(content) > 300:
                    tc_id = msg.get("tool_call_id", "")
                    tool_name, tool_args = tool_call_map.get(tc_id, ("unknown", {}))
                    summary = self._summarize_tool_result_for_compaction(
                        tool_name, tool_args, content,
                    )
                    msg = {**msg, "content": summary}
            result.append(msg)
        return result

    def _summarize_tool_result_for_compaction(
        self, tool_name: str, tool_args: dict, content: str,
    ) -> str:
        """
        为上下文压缩生成工具结果的语义摘要。

        保留关键信息 (文件名、类型、状态)，丢弃原始内容，
        并明确告知模型此工具已执行过、重复调用结果不变。
        """
        import json as _json
        original_len = len(content)

        # 尝试解析 JSON 内容提取关键字段
        meta_parts: list[str] = []
        try:
            data = _json.loads(content)
            if isinstance(data, dict):
                for key in ("filename", "file_id", "content_type", "size_bytes",
                            "title", "url", "status", "error"):
                    if key in data:
                        meta_parts.append(f"{key}={data[key]}")
                # 对于文件内容，取前 150 字作为预览
                text_val = data.get("text") or data.get("content") or ""
                if isinstance(text_val, str) and len(text_val) > 20:
                    meta_parts.append(f"内容预览={text_val[:150]}...")
            elif isinstance(data, list):
                meta_parts.append(f"返回列表({len(data)}项)")
                if data and isinstance(data[0], dict):
                    meta_parts.append(f"首项字段={list(data[0].keys())[:5]}")
        except Exception:
            # 非 JSON，取前 150 字
            meta_parts.append(f"内容预览={content[:150]}...")

        args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items()) if tool_args else ""
        meta_str = "; ".join(meta_parts) if meta_parts else "无额外信息"

        # 判断执行状态：检查内容是否包含错误标识
        has_error = any(k in content[:200].lower() for k in ('"error"', '"success": false', '"success":false'))
        status = "失败" if has_error else "成功"

        return (
            f"[已压缩的工具结果] {tool_name}({args_str})\n"
            f"执行状态: {status} | 原始长度: {original_len}字\n"
            f"摘要: {meta_str}\n"
            f"⚠ 此工具已执行过。重复调用相同参数将返回完全相同的结果，请勿重复调用。"
        )

    async def _stage2_summarize_middle(
        self,
        messages: list[dict],
        budget: int,
        estimated: int,
    ) -> list[dict]:
        """
        阶段 2: 中间消息压缩为摘要。

        保留 system(0) + user(1) + 最近 6 条，中间消息变摘要。
        触发 pre_compact hook 保护关键信息。
        """
        head = messages[:2]   # system + first user
        tail = messages[-6:]  # 最近 6 条
        middle = messages[2:-6]

        if not middle:
            return messages

        # ── PreCompact Hook: 保护关键信息 ──
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

        # 用 LLM 生成摘要 (4d)，失败则 fallback 到启发式
        summary_text = await self._generate_summary(middle, preserved_prefix)

        return head + [{"role": "user", "content": summary_text}] + tail

    # ── 压缩 prompt 缓存 ──
    _compact_prompt_cache: str | None = None
    _compact_prefix_cache: str | None = None

    @classmethod
    def _load_compact_prompt(cls) -> str:
        """加载交接摘要压缩指令 (带缓存)。"""
        if cls._compact_prompt_cache is None:
            path = Path(__file__).parent.parent / "prompts" / "compact_prompt.md"
            try:
                cls._compact_prompt_cache = path.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                logger.warning(f"compact_prompt.md not found: {path}")
                cls._compact_prompt_cache = "请用简洁的中文总结以下对话历史的关键信息。"
        return cls._compact_prompt_cache

    @classmethod
    def _load_compact_prefix(cls) -> str:
        """加载摘要前缀 (带缓存)。"""
        if cls._compact_prefix_cache is None:
            path = Path(__file__).parent.parent / "prompts" / "compact_prefix.md"
            try:
                cls._compact_prefix_cache = path.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                logger.warning(f"compact_prefix.md not found: {path}")
                cls._compact_prefix_cache = "[以下是上下文压缩前的交接摘要。]"
        return cls._compact_prefix_cache

    async def _generate_summary(
        self, middle: list[dict], preserved_prefix: str,
    ) -> str:
        """
        A4 (4d): 用 LLM 生成中间消息的交接摘要。

        有 llm_client 时调 LLM 做结构化交接文档，超时/失败则 fallback 到启发式截取。
        prompt 从 prompts/compact_prompt.md 加载，摘要前缀从 prompts/compact_prefix.md 加载。
        """
        # 先构建启发式 fallback
        heuristic_parts = []
        user_messages = []
        for msg in middle:
            role = msg.get("role", "unknown")
            if role == "tool":
                tool_call_id = msg.get("tool_call_id", "?")
                content_preview = str(msg.get("content", ""))[:80]
                heuristic_parts.append(f"[tool result: {tool_call_id}] {content_preview}")
            elif role == "assistant":
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    tool_names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                    heuristic_parts.append(f"[assistant called: {', '.join(tool_names)}]")
                else:
                    content_preview = str(msg.get("content", ""))[:100]
                    heuristic_parts.append(f"[assistant: {content_preview}]")
            else:
                content_preview = str(msg.get("content", ""))[:100]
                heuristic_parts.append(f"[{role}: {content_preview}]")
                if role == "user":
                    user_messages.append(str(msg.get("content", ""))[:200])

        heuristic_text = "\n".join(heuristic_parts)

        # 尝试 LLM 摘要
        if self.llm_client is not None:
            try:
                compact_prompt = self._load_compact_prompt()
                compact_prefix = self._load_compact_prefix()

                # 构建输入: 用户原始消息 + 对话历史摘要
                input_parts = []
                if user_messages:
                    input_parts.append("用户消息:\n" + "\n".join(user_messages[:5]))
                input_parts.append("对话历史:\n" + heuristic_text[:3000])
                user_input = "\n\n".join(input_parts)

                llm_resp = await asyncio.wait_for(
                    self.llm_client.chat_completion(
                        messages=[
                            {"role": "system", "content": compact_prompt},
                            {"role": "user", "content": user_input},
                        ],
                        max_tokens=500,
                        temperature=0.3,
                    ),
                    timeout=10.0,  # 摘要不能耗时太久
                )
                if llm_resp.content and len(llm_resp.content.strip()) > 10:
                    logger.info("Stage2: LLM summary generated successfully")
                    return (
                        preserved_prefix
                        + compact_prefix + "\n"
                        + llm_resp.content.strip()
                    )
            except Exception as e:
                logger.warning(f"Stage2: LLM summary failed, falling back to heuristic: {e}")

        # Fallback: 启发式截取
        return (
            preserved_prefix
            + f"[Context Compacted — {len(middle)} messages summarized]\n"
            + heuristic_text
        )

    def _stage3_metadata_mode(self, messages: list[dict]) -> list[dict]:
        """
        阶段 3: 元数据模式 — 只保留 system + 最近 4 条 + 简短摘要。
        """
        head = messages[:1]  # system only
        tail_count = min(4, len(messages) - 1)
        tail = messages[-tail_count:] if tail_count > 0 else []
        compacted_count = len(messages) - 1 - tail_count

        summary = {
            "role": "user",
            "content": f"[{compacted_count} earlier messages compacted to save context. Continue from here.]",
        }
        return head + [summary] + tail

    def _stage4_drop_oldest(
        self,
        messages: list[dict],
        budget: int,
        tools_schema: list[dict] | None,
    ) -> list[dict]:
        """
        阶段 4: 逐条删最旧非系统消息直到 fit。

        对标 Codex 逐条删最旧 fallback。
        保留 system[0] + 最后 2 条消息。
        """
        # 分离 system, middle, tail
        system = [messages[0]] if messages and messages[0].get("role") == "system" else []
        tail_count = min(2, len(messages) - len(system))
        tail = messages[-tail_count:] if tail_count > 0 else []
        middle = messages[len(system):-tail_count] if tail_count > 0 else messages[len(system):]

        dropped = 0
        while middle:
            candidate = system + middle + tail
            candidate = self._repair_tool_pairs(candidate)
            estimated = estimate_messages_tokens(candidate, tools=tools_schema)
            if estimated <= budget:
                logger.info(
                    f"Stage4: dropped {dropped} oldest messages to fit budget",
                    extra={"trace_id": self.trace_id},
                )
                return candidate
            # Drop the oldest non-system message
            middle.pop(0)
            dropped += 1

        # Even after dropping everything, return system + tail
        result = system + tail
        logger.warning(
            f"Stage4: dropped ALL middle messages ({dropped}), only system+tail remain",
            extra={"trace_id": self.trace_id},
        )
        return self._repair_tool_pairs(result)

    @staticmethod
    def _repair_tool_pairs(messages: list[dict]) -> list[dict]:
        """
        A4 (4f): 修复压缩后的 tool_calls/tool 消息配对。

        规则:
        - 每个 role=tool 消息必须有对应的 assistant(tool_calls) 在前
        - 孤立的 tool 消息 → 删除
        - 孤立的 assistant(tool_calls) → 补一个 "[result compacted]" 的 tool 消息
        """
        # 收集所有 assistant 消息中声明的 tool_call IDs
        declared_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls", []):
                    tc_id = tc.get("id", "")
                    if tc_id:
                        declared_ids.add(tc_id)

        # 收集所有 tool 消息的 tool_call_id
        responded_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") == "tool":
                tc_id = msg.get("tool_call_id", "")
                if tc_id:
                    responded_ids.add(tc_id)

        # 1. 删除孤立的 tool 消息 + 去重
        seen_tool_ids: set[str] = set()
        result = []
        for msg in messages:
            if msg.get("role") == "tool":
                tc_id = msg.get("tool_call_id", "")
                if tc_id and tc_id not in declared_ids:
                    continue  # 删除孤立 tool 消息
                if tc_id and tc_id in seen_tool_ids:
                    continue  # 跳过重复的 tool 响应
                if tc_id:
                    seen_tool_ids.add(tc_id)
            result.append(msg)

        # 2. 为孤立的 assistant tool_calls 补充 tool 响应
        patched = []
        for msg in result:
            patched.append(msg)
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls", []):
                    tc_id = tc.get("id", "")
                    if tc_id and tc_id not in responded_ids:
                        patched.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": "[result compacted]",
                        })
                        responded_ids.add(tc_id)

        return patched

    def _classify_compaction_reason(
        self,
        messages: list[dict],
        original_tokens: int,
        budget: int,
    ) -> str:
        """
        分类压缩触发原因 (4j 可观测性增强)。

        Returns:
            reason 字符串:
            - "too_few_messages": 消息太少但 token 超限 (说明单条消息过长或 system 太大)
            - "large_system_prompt": system prompt 占预算超 50%
            - "long_single_message": 存在单条消息超过预算 30% 的情况
            - "accumulated_context": 正常累积导致超限
        """
        if len(messages) <= 4:
            return "too_few_messages"

        # 检查 system prompt 大小
        system_msgs = [m for m in messages if m.get("role") == "system"]
        if system_msgs:
            sys_tokens = estimate_messages_tokens(system_msgs)
            if sys_tokens > budget * 0.5:
                return "large_system_prompt"

        # 检查是否有单条消息过大
        threshold_per_msg = budget * 0.3
        for msg in messages:
            single_tokens = estimate_messages_tokens([msg])
            if single_tokens > threshold_per_msg:
                return "long_single_message"

        return "accumulated_context"

    def _emit_compaction_event(
        self,
        stage: int,
        original_count: int,
        compacted_count: int,
        original_tokens: int,
        compacted_tokens: int,
        reason: str = "accumulated_context",
    ) -> None:
        """发射压缩可观测性事件 (4j)。"""
        ratio = compacted_tokens / original_tokens if original_tokens > 0 else 1.0

        # 更新累计统计
        self._compact_stats["count"] += 1
        self._compact_stats["total_ratio"] += ratio
        self._compact_stats["stages"][stage] = self._compact_stats["stages"].get(stage, 0) + 1

        logger.info(
            f"Context compacted (stage {stage}, reason={reason}): "
            f"{original_count} → {compacted_count} messages, "
            f"{original_tokens} → {compacted_tokens} tokens "
            f"(ratio={ratio:.2f})",
            extra={"trace_id": self.trace_id},
        )
        self._emit("agent_progress", {
            "status": "context_compacted",
            "stage": stage,
            "reason": reason,
            "original_messages": original_count,
            "compacted_messages": compacted_count,
            "original_tokens": original_tokens,
            "compacted_tokens": compacted_tokens,
            "compression_ratio": round(ratio, 3),
        })

    @staticmethod
    def _allocate_tool_budgets(
        observations: list[ToolResult],
        max_per_tool: int,
    ) -> list[int]:
        """
        A4-4a: 多个工具结果按比例分配总预算。

        单个工具时，直接使用 max_per_tool。
        多个工具时:
        - 总预算 = max_per_tool × len × 1.5 系数（防止总量过大）
        - 每个工具按原始大小占比分配
        - 每个工具最低保留 MIN_BUDGET 字符
        - 如果 max_per_tool <= 0（不限制），返回全 0
        """
        MIN_BUDGET = 2000
        n = len(observations)

        # 不限制或空列表
        if max_per_tool <= 0 or n == 0:
            return [max_per_tool] * n

        # 单工具: 直接用 max_per_tool
        if n == 1:
            return [max_per_tool]

        # 多工具: 按比例分配
        import json as _json

        # 计算每个工具结果的原始大小
        raw_sizes = []
        for obs in observations:
            if obs.success:
                raw = _json.dumps(obs.data, ensure_ascii=False, default=str)
            else:
                raw = _json.dumps({"error": obs.error}, ensure_ascii=False)
            raw_sizes.append(len(raw))

        total_raw = sum(raw_sizes)
        total_budget = int(max_per_tool * n * 1.5)

        # 所有结果都很小，无需分配
        if total_raw <= total_budget:
            return [max_per_tool] * n

        # 按比例分配，保证最低 MIN_BUDGET
        budgets: list[int] = []
        if total_raw == 0:
            # 全空结果
            return [max_per_tool] * n

        # 第一轮: 按比例分配
        for size in raw_sizes:
            ratio = size / total_raw
            allocated = int(total_budget * ratio)
            budgets.append(max(allocated, MIN_BUDGET))

        # 第二轮: 如果最低保留导致总量超出，按比例缩放非最低的部分
        budget_sum = sum(budgets)
        if budget_sum > total_budget:
            # 找出已经在最低值的和可以缩减的
            min_count = sum(1 for b in budgets if b <= MIN_BUDGET)
            min_total = min_count * MIN_BUDGET
            remaining_budget = total_budget - min_total

            if remaining_budget > 0:
                non_min_total = sum(b for b in budgets if b > MIN_BUDGET)
                if non_min_total > 0:
                    scale = remaining_budget / non_min_total
                    budgets = [
                        max(int(b * scale), MIN_BUDGET) if b > MIN_BUDGET else b
                        for b in budgets
                    ]

        return budgets

    def _build_initial_messages(
        self,
        system_prompt: str,
        user_message: str | list,
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
                    # 优化: 如果原始 arguments 解析后与 parsed 一致，直接复用原始字符串
                    raw_args_str = tc_raw.get("function", {}).get("arguments", "{}")
                    try:
                        raw_parsed = _json.loads(raw_args_str) if isinstance(raw_args_str, str) else raw_args_str
                        if raw_parsed == parsed.tool_calls[i].arguments:
                            normalized_args = raw_args_str if isinstance(raw_args_str, str) else _json.dumps(raw_args_str, ensure_ascii=False)
                        else:
                            normalized_args = _json.dumps(parsed.tool_calls[i].arguments, ensure_ascii=False)
                    except (ValueError, TypeError):
                        normalized_args = _json.dumps(parsed.tool_calls[i].arguments, ensure_ascii=False)
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
        # 构建压缩统计 (仅在发生过压缩时附加)
        compact_stats = None
        if self._compact_stats["count"] > 0:
            count = self._compact_stats["count"]
            compact_stats = {
                **self._compact_stats,
                "avg_ratio": round(self._compact_stats["total_ratio"] / count, 3),
            }

        return RuntimeResult(
            final_answer=final_answer,
            steps=list(self._steps),
            token_usage=self._accumulated_usage,
            iterations=iterations,
            max_iterations_reached=max_iterations_reached,
            error=error,
            thinking="\n\n".join(self._thinking_parts) if self._thinking_parts else "",
            compact_stats=compact_stats,
        )

    def _count_tool_calls(self) -> int:
        return sum(1 for s in self._steps if s.step_type == StepType.TOOL_CALL)

    _HIGH_LIMIT_KEYS = frozenset({"content", "command"})

    @staticmethod
    def _summarize_args(args: dict | None) -> dict[str, str]:
        """截断长参数值用于 SSE 可视化。content/command 使用 50000 限制，其他 2000。"""
        if not args:
            return {}
        summary: dict[str, str] = {}
        for k, v in args.items():
            s = str(v)
            limit = 50_000 if k in AgenticRuntime._HIGH_LIMIT_KEYS else 2000
            summary[k] = s[:limit] + "..." if len(s) > limit else s
        return summary

    @staticmethod
    def _summarize_result(result: ToolResult) -> str:
        """截断结果文本 (>5000 字符) 用于 SSE 可视化。"""
        if not result.success:
            text = result.error or "unknown error"
        else:
            text = str(result.data) if result.data is not None else ""
        return text[:5000] + "..." if len(text) > 5000 else text

    @staticmethod
    def _tool_call_signature(tool_calls: list[ParsedToolCall]) -> str:
        """生成一组工具调用的指纹，用于检测重复模式。"""
        import json as _json
        parts = []
        for tc in sorted(tool_calls, key=lambda t: t.name):
            args_str = _json.dumps(tc.arguments, sort_keys=True, ensure_ascii=False)
            parts.append(f"{tc.name}({args_str})")
        return "|".join(parts)

    def _detect_repetition(self, tool_calls: list[ParsedToolCall]) -> str | None:
        """
        检测 Agent 是否陷入工具调用死循环。

        返回:
            None — 无重复
            "warn" — 连续 3 次相同调用，需注入警告
            "force_stop" — 警告后仍重复，强制终止
        """
        sig = self._tool_call_signature(tool_calls)
        self._tool_call_history.append(sig)

        # 至少需要 3 轮才能判定重复
        if len(self._tool_call_history) < 3:
            return None

        last_3 = self._tool_call_history[-3:]
        if last_3[0] == last_3[1] == last_3[2]:
            if self._repetition_warned:
                return "force_stop"
            return "warn"

        return None

    @staticmethod
    def _truncate_at_repetition(text: str) -> str:
        """截断文本到第一次出现重复的位置，保留有意义的前半部分。"""
        if len(text) < 400:
            return text

        # 尝试用 60 字的探针找到第二次出现的位置
        normalized = "".join(text.split())
        best_cut = len(text)

        for probe_len in (60, 40):
            tail_probe = normalized[-probe_len:]
            # 在前半部分找第一次出现的位置
            first_pos = normalized.find(tail_probe)
            if first_pos >= 0 and first_pos < len(normalized) - probe_len - 20:
                # 找到重复，第二次出现的位置就是截断点
                second_pos = normalized.find(tail_probe, first_pos + probe_len)
                if second_pos >= 0 and second_pos < best_cut:
                    best_cut = second_pos
                    break

        if best_cut < len(text):
            # 在原始文本中找对应位置（考虑空白差异，取约同比例位置）
            ratio = best_cut / len(normalized)
            cut_in_original = int(len(text) * ratio)
            # 往前找自然断点
            for j in range(cut_in_original, max(cut_in_original - 200, 0), -1):
                if text[j] in "\n。.！!？?":
                    return text[:j + 1].rstrip()
            return text[:cut_in_original].rstrip()

        return text

    @staticmethod
    def _detect_text_repetition(text: str) -> bool:
        """
        检测流式文本是否陷入重复生成。

        策略: 取最近一段文本，检查它是否在更早的文本中出现过。
        仅扫描最近 2KB 的前缀文本（避免 O(n²) 全文扫描拖慢流式输出）。
        """
        if len(text) < 400:
            return False

        # 取最后 150 字（去空白），在前面的文本中查找
        tail = "".join(text[-150:].split())
        if len(tail) < 40:
            return False

        # 用 60 字的滑动窗口搜索 — 仅扫描最近 2KB 前缀（排除最后 150 字）
        probe = tail[-60:]
        scan_end = max(len(text) - 150, 0)
        scan_start = max(scan_end - 2048, 0)
        head = "".join(text[scan_start:scan_end].split())

        # 计算 probe 在 head 中出现的次数
        count = 0
        start = 0
        while True:
            pos = head.find(probe, start)
            if pos == -1:
                break
            count += 1
            start = pos + 30  # 避免重叠计数
            if count >= 2:
                return True

        return False

    def _emit(self, event_type: str, data: dict) -> None:
        """通过 EventBus 发射事件。"""
        if self.event_bus:
            self.event_bus.emit(event_type, data)
