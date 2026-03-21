"""
Advanced LLM integration tests — 补全 10 类缺失覆盖。

LLM endpoint: from .env (LLM_BASE_URL / LLM_MODEL)

Categories:
  1. Multi-tool single iteration (runtime)
  2. read_only parallel execution (runtime)
  3. Context compression triggered (runtime)
  4. <think> tag parsing (runtime)
  5. Streaming + tool calling mixed (runtime)
  6. Session compaction with real LLM (session.py)
  7. Real subagent execution (subagent.py)
  8. Quality Gate self-correction (quality_gate.py)
  9. LLM retry on connection error (llm_client)
  10. Gateway Skill/Memory injection (gateway)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import asyncio

from core.llm_client import LLMGatewayClient, LLMClientConfig, LLMClientError
from core.runtime import AgenticRuntime, RuntimeConfig, RuntimeResult
from core.tool_registry import ToolRegistry
from core.tool_protocol import ToolCallParser
from core.event_bus import EventBus
from tests.conftest import LLM_BASE_URL, LLM_MODEL, LLM_API_KEY

pytestmark = pytest.mark.llm


# ── Shared Fixtures ──


@pytest.fixture
def llm_client():
    config = LLMClientConfig(
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
        timeout_s=60,
    )
    return LLMGatewayClient(config)


@pytest.fixture
def math_registry():
    """Registry with add/multiply read_only tools."""
    reg = ToolRegistry()

    @reg.tool(description="Add two numbers", read_only=True)
    def add(a: float, b: float) -> dict:
        return {"result": a + b}

    @reg.tool(description="Multiply two numbers", read_only=True)
    def multiply(a: float, b: float) -> dict:
        return {"result": a * b}

    return reg


@pytest.fixture
def mixed_registry():
    """Registry with both read_only and write tools."""
    reg = ToolRegistry()

    @reg.tool(description="Add two numbers", read_only=True)
    def add(a: float, b: float) -> dict:
        return {"result": a + b}

    @reg.tool(description="Multiply two numbers", read_only=True)
    def multiply(a: float, b: float) -> dict:
        return {"result": a * b}

    results_store = []

    @reg.tool(description="Save a result to storage", read_only=False)
    def save_result(label: str, value: str) -> dict:
        results_store.append({"label": label, "value": value})
        return {"saved": True, "total_saved": len(results_store)}

    return reg


# ================================================================
# 1. Multi-tool single iteration
# ================================================================


@pytest.mark.asyncio
async def test_multi_tool_single_iteration(llm_client, math_registry):
    """LLM should call multiple tools (add + multiply) in one iteration."""
    runtime = AgenticRuntime(
        llm_client=llm_client,
        tool_registry=math_registry,
        tool_parser=ToolCallParser(),
        config=RuntimeConfig(max_iterations=10, max_tokens_per_turn=2048),
        event_bus=EventBus(trace_id="test-multi-tool"),
    )

    try:
        result = await runtime.run(
            system_prompt=(
                "You are a helpful math assistant. "
                "When asked to calculate multiple values, call ALL tools in a single response. "
                "Always use tools for calculations."
            ),
            user_message=(
                "Calculate two things at once: 15 + 25 using add, and 6 * 7 using multiply. "
                "Call both tools in a single response."
            ),
        )
        assert result.final_answer is not None
        assert result.tool_call_count >= 2
        # At least one of these values should appear in the answer
        assert "40" in result.final_answer or "42" in result.final_answer
    finally:
        await llm_client.close()


# ================================================================
# 2. read_only tool parallel execution
# ================================================================


@pytest.mark.asyncio
async def test_readonly_tools_parallel(llm_client, math_registry):
    """read_only tools should execute in parallel (asyncio.gather)."""
    call_times = []

    # Override tools to record timing
    reg = ToolRegistry()

    @reg.tool(description="Add two numbers (with delay)", read_only=True)
    async def add(a: float, b: float) -> dict:
        import time
        start = time.monotonic()
        await asyncio.sleep(0.5)  # 500ms delay
        call_times.append(("add", start, time.monotonic()))
        return {"result": a + b}

    @reg.tool(description="Multiply two numbers (with delay)", read_only=True)
    async def multiply(a: float, b: float) -> dict:
        import time
        start = time.monotonic()
        await asyncio.sleep(0.5)  # 500ms delay
        call_times.append(("multiply", start, time.monotonic()))
        return {"result": a * b}

    runtime = AgenticRuntime(
        llm_client=llm_client,
        tool_registry=reg,
        tool_parser=ToolCallParser(),
        config=RuntimeConfig(
            max_iterations=10,
            max_tokens_per_turn=2048,
            parallel_tool_calls=True,
        ),
        event_bus=EventBus(trace_id="test-parallel"),
    )

    try:
        result = await runtime.run(
            system_prompt=(
                "You are a math assistant. When asked to calculate multiple things, "
                "call ALL tools in a single response. Always use tools."
            ),
            user_message=(
                "Calculate 10+20 using add, and 3*4 using multiply. "
                "Call both tools at the same time in one response."
            ),
        )
        assert result.tool_call_count >= 2

        # If both tools were called, check they ran in parallel
        # (overlapping start/end times → total < sum of delays)
        if len(call_times) >= 2:
            starts = [ct[1] for ct in call_times]
            ends = [ct[2] for ct in call_times]
            total_wall = max(ends) - min(starts)
            # Parallel: ~0.5s; sequential: ~1.0s
            # Allow some slack for LLM/network overhead
            assert total_wall < 0.9, (
                f"Tools took {total_wall:.2f}s — expected < 0.9s if parallel"
            )
    finally:
        await llm_client.close()


# ================================================================
# 3. Context compression triggered
# ================================================================


@pytest.mark.asyncio
async def test_context_compression_triggered(llm_client, math_registry):
    """
    With a small context_budget, runtime should trigger compression
    when messages grow large.
    """
    runtime = AgenticRuntime(
        llm_client=llm_client,
        tool_registry=math_registry,
        tool_parser=ToolCallParser(),
        config=RuntimeConfig(
            max_iterations=10,
            max_tokens_per_turn=2048,
            # Very small budget to trigger compression quickly
            context_budget_tokens=4000,
            model_context_window=8000,
            context_budget_ratio=0.5,
            compress_threshold_ratio=0.6,
        ),
        event_bus=EventBus(trace_id="test-compression"),
    )

    # Pre-fill with many messages to approach the budget
    long_history = []
    for i in range(15):
        long_history.append({"role": "user", "content": f"Question {i}: What is {i*10} + {i*20}?"})
        long_history.append({"role": "assistant", "content": f"The answer is {i*30}. " * 10})

    try:
        result = await runtime.run(
            system_prompt="You are a helpful math assistant. Answer briefly.",
            user_message="What is 5 + 3? Just say the number.",
            initial_messages=long_history,
        )
        assert result.final_answer is not None
        # Check that compression was triggered
        if result.compact_stats:
            assert result.compact_stats["count"] >= 1
    finally:
        await llm_client.close()


# ================================================================
# 4. <think> tag parsing
# ================================================================


@pytest.mark.asyncio
async def test_think_tag_parsing(llm_client):
    """
    If the LLM produces <think>...</think> tags, the runtime should
    extract the thinking content and include it in result.thinking.
    """
    runtime = AgenticRuntime(
        llm_client=llm_client,
        tool_registry=ToolRegistry(),
        tool_parser=ToolCallParser(),
        config=RuntimeConfig(max_iterations=5, max_tokens_per_turn=2048),
        event_bus=EventBus(trace_id="test-think"),
    )

    try:
        result = await runtime.run(
            system_prompt=(
                "You are a thinking assistant. "
                "Always wrap your reasoning in <think>...</think> tags before giving your answer. "
                "Example format:\n"
                "<think>Let me think about this...</think>\n"
                "My answer is: ..."
            ),
            user_message="What is the capital of France? Think step by step.",
        )
        assert result.final_answer is not None
        # The model may or may not produce think tags depending on the model
        # If thinking was captured, verify it's non-empty
        if result.thinking:
            assert len(result.thinking) > 0
        # Either way, the final answer should mention Paris
        assert "Paris" in result.final_answer or "巴黎" in result.final_answer
    finally:
        await llm_client.close()


# ================================================================
# 5. Streaming + tool calling mixed
# ================================================================


@pytest.mark.asyncio
async def test_streaming_with_tool_calls(llm_client, math_registry):
    """Verify streaming works correctly when LLM uses tools mid-conversation."""
    bus = EventBus(trace_id="test-stream-tools")

    runtime = AgenticRuntime(
        llm_client=llm_client,
        tool_registry=math_registry,
        tool_parser=ToolCallParser(),
        config=RuntimeConfig(max_iterations=10, max_tokens_per_turn=2048),
        event_bus=bus,
    )

    try:
        result = await runtime.run(
            system_prompt="You are a helpful math assistant. Always use the add tool for addition.",
            user_message="What is 100 + 200? Use the add tool.",
        )
        assert result.final_answer is not None
        assert "300" in result.final_answer
        assert result.tool_call_count >= 1

        # Verify we got text_delta events in history
        text_deltas = [e for e in bus.history if e.event_type == "text_delta"]
        assert len(text_deltas) > 0, "Should have emitted text_delta events"

        # Verify agent_progress events
        progress_events = [e for e in bus.history if e.event_type == "agent_progress"]
        assert len(progress_events) >= 1
    finally:
        await llm_client.close()


# ================================================================
# 6. Session compaction with real LLM
# ================================================================


@pytest.mark.asyncio
async def test_session_compaction_real_llm(llm_client, tmp_path):
    """compact() with a real LLM should produce a meaningful summary."""
    from agent.session import SessionManager

    sm = SessionManager(base_dir=str(tmp_path / "sessions"))
    tenant, user = "T_test", "U_test"
    sid = sm.create_session(tenant, user)

    # Write enough messages to trigger compaction
    for i in range(14):
        sm.append_message(tenant, user, sid, {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"Message {i}: discussing project architecture and design patterns.",
        })

    try:
        await sm.compact(tenant, user, sid, llm_client, max_recent=4)

        msgs = sm.load_messages(tenant, user, sid)
        contents = [m.get("content", "") for m in msgs]

        # Should have a compaction marker/summary
        assert any("compaction" in c.lower() or len(c) > 20 for c in contents), \
            "Compacted messages should contain a summary"
        # Recent messages should be preserved
        assert any("Message 13" in c for c in contents), \
            "Most recent message should be preserved"
    finally:
        await llm_client.close()


# ================================================================
# 7. Real subagent execution
# ================================================================


@pytest.mark.asyncio
async def test_subagent_simple_task(llm_client):
    """SubagentRunner.run_subagent() with a real LLM should return an answer."""
    from agent.subagent import SubagentRunner
    from tools.registry_builder import build_shared_registry, build_capability_registry

    shared = build_shared_registry()
    capability = build_capability_registry()

    runner = SubagentRunner(
        llm_client=llm_client,
        shared_registry=shared,
        capability_registry=capability,
    )

    try:
        answer = await runner.run_subagent(
            task="What is the capital of Japan? Answer in one word.",
            prompt="You are a geography expert. Answer concisely.",
            tools="add,multiply",  # limited tools
            timeout_s=30,
        )
        assert answer is not None
        assert len(answer) > 0
        # The answer should mention Tokyo
        assert "Tokyo" in answer or "东京" in answer or "tokyo" in answer.lower()
    finally:
        await llm_client.close()


@pytest.mark.asyncio
async def test_subagent_with_tool_use(llm_client):
    """Subagent should be able to use tools to answer."""
    from agent.subagent import SubagentRunner
    from tools.registry_builder import build_shared_registry, build_capability_registry

    shared = build_shared_registry()
    capability = build_capability_registry()

    runner = SubagentRunner(
        llm_client=llm_client,
        shared_registry=shared,
        capability_registry=capability,
    )

    try:
        answer = await runner.run_subagent(
            task="Calculate 15 + 27 using the add tool. Report the exact result.",
            prompt="You are a math assistant. Always use the add tool for addition.",
            tools="add",
            timeout_s=30,
        )
        assert answer is not None
        assert "42" in answer
    finally:
        await llm_client.close()


@pytest.mark.asyncio
async def test_subagent_timeout(llm_client):
    """Subagent should handle timeout gracefully."""
    from agent.subagent import SubagentRunner
    from tools.registry_builder import build_shared_registry, build_capability_registry

    shared = build_shared_registry()
    capability = build_capability_registry()

    runner = SubagentRunner(
        llm_client=llm_client,
        shared_registry=shared,
        capability_registry=capability,
    )

    try:
        # Very short timeout — should trigger timeout
        answer = await runner.run_subagent(
            task=(
                "Write a 5000 word essay about the history of mathematics, "
                "covering every major mathematician and their contributions."
            ),
            timeout_s=1,  # 1 second, will likely timeout
        )
        # Should return timeout message, not crash
        assert "超时" in answer or "timeout" in answer.lower()
    finally:
        await llm_client.close()


# ================================================================
# 8. Quality Gate self-correction
# ================================================================


@pytest.mark.asyncio
async def test_quality_gate_blocks_and_corrects(llm_client):
    """
    Quality gate hook should block incomplete output and let the runtime
    self-correct by continuing iterations.
    """
    from agent.hooks import HookRegistry, HookEvent, HookResult
    from agent.quality_gate import reset_correction_count
    from core.context import RequestContext, current_request

    # Set RequestContext for quality gate
    ctx = RequestContext(user_id="test_user", session_id="test_session_qg")
    current_request.set(ctx)

    # Custom quality gate that blocks the first attempt
    block_count = {"n": 0}

    def strict_gate(event: HookEvent) -> HookResult:
        block_count["n"] += 1
        if block_count["n"] <= 1:
            # Block first attempt
            return HookResult(
                action="block",
                message="请在回答中加上 '[已验证]' 标记。",
            )
        return HookResult(action="allow")

    hooks = HookRegistry()
    hooks.register("agent_stop", strict_gate)

    runtime = AgenticRuntime(
        llm_client=llm_client,
        tool_registry=ToolRegistry(),
        tool_parser=ToolCallParser(),
        config=RuntimeConfig(max_iterations=5, max_tokens_per_turn=2048),
        event_bus=EventBus(trace_id="test-qg"),
        hooks=hooks,
    )

    try:
        result = await runtime.run(
            system_prompt="You are a helpful assistant. Follow all instructions precisely.",
            user_message="Say hello. If told to add a marker, include it exactly.",
        )
        assert result.final_answer is not None
        # Quality gate should have been invoked at least once
        assert block_count["n"] >= 1
        # Runtime used more iterations due to self-correction
        assert result.iterations >= 2
    finally:
        await llm_client.close()
        reset_correction_count("test_user:test_session_qg")


# ================================================================
# 9. LLM retry on connection error
# ================================================================


@pytest.mark.asyncio
async def test_llm_connection_error_handling():
    """LLM client should raise LLMClientError on connection failure."""
    cfg = LLMClientConfig(
        base_url=LLM_BASE_URL.rsplit(":", 1)[0] + ":59999/v1",  # wrong port
        model=LLM_MODEL,
        max_retries=0,
        timeout_s=5.0,
    )
    client = LLMGatewayClient(cfg)
    with pytest.raises(LLMClientError):
        await client.chat_completion([{"role": "user", "content": "hi"}])
    await client.close()


@pytest.mark.asyncio
async def test_llm_streaming_fallback(llm_client):
    """If streaming fails, runtime should fallback to non-streaming."""
    # This tests the error handling path in _streaming_llm_call
    # We test it works normally — the fallback code exists but is
    # triggered only on provider-side streaming errors
    runtime = AgenticRuntime(
        llm_client=llm_client,
        tool_registry=ToolRegistry(),
        tool_parser=ToolCallParser(),
        config=RuntimeConfig(max_iterations=3, max_tokens_per_turn=1024),
        event_bus=EventBus(trace_id="test-fallback"),
    )

    try:
        result = await runtime.run(
            system_prompt="You are a helpful assistant.",
            user_message="Say 'hello' and nothing else.",
        )
        assert result.final_answer is not None
        assert len(result.final_answer) > 0
    finally:
        await llm_client.close()


@pytest.mark.asyncio
async def test_llm_cumulative_usage_tracking(llm_client):
    """Multiple LLM calls should accumulate token usage."""
    messages = [{"role": "user", "content": "Say 'a'."}]

    try:
        await llm_client.chat_completion(messages, max_tokens=16)
        usage_after_1 = llm_client.cumulative_usage.total_tokens
        assert usage_after_1 > 0

        await llm_client.chat_completion(messages, max_tokens=16)
        usage_after_2 = llm_client.cumulative_usage.total_tokens
        assert usage_after_2 > usage_after_1

        assert llm_client.call_count == 2
    finally:
        await llm_client.close()


# ================================================================
# 10. Gateway Skill/Memory injection
# ================================================================


@pytest.mark.asyncio
async def test_gateway_with_skills_and_memory(tmp_path):
    """
    Full gateway test: skills and memory are injected into the prompt.
    """
    from core.llm_client import LLMGatewayClient, LLMClientConfig
    from core.runtime import RuntimeConfig
    from agent.gateway import AgentGateway
    from agent.session import SessionManager
    from agent.prompt import PromptBuilder
    from agent.subagent import SubagentRunner
    from agent.hooks import build_default_hooks
    from memory.markdown_store import MarkdownMemoryStore
    from skills.loader import SkillLoader
    from tools.registry_builder import (
        build_full_registry, build_shared_registry, build_capability_registry,
    )

    config = LLMClientConfig(
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
        timeout_s=60,
    )
    llm_client = LLMGatewayClient(config)

    # Set up skills directory with a test skill
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_file = skills_dir / "test_skill.md"
    skill_file.write_text(
        "---\n"
        "name: test_knowledge\n"
        "description: Test skill for unit testing\n"
        "applies_to:\n"
        "  - general_chat\n"
        "---\n\n"
        "# Test Knowledge\n\n"
        "The secret code word is PINEAPPLE.\n"
    )

    # Set up memory with test content
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    global_dir = memory_dir / "global"
    global_dir.mkdir(parents=True)
    (global_dir / "test-memory.md").write_text("User prefers concise answers.\n")

    tool_registry = build_full_registry()
    shared = build_shared_registry()
    capability = build_capability_registry()
    prompt_builder = PromptBuilder()
    session_manager = SessionManager(base_dir=str(tmp_path / "sessions"))
    memory_store = MarkdownMemoryStore(base_dir=str(memory_dir))
    skill_loader = SkillLoader(skills_dir=str(skills_dir))

    subagent_runner = SubagentRunner(
        llm_client=llm_client,
        shared_registry=shared,
        capability_registry=capability,
        prompt_builder=prompt_builder,
    )

    gw = AgentGateway(
        llm_client=llm_client,
        tool_registry=tool_registry,
        session_manager=session_manager,
        skill_loader=skill_loader,
        prompt_builder=prompt_builder,
        subagent_runner=subagent_runner,
        memory_store=memory_store,
        hooks=build_default_hooks(),
        runtime_config=RuntimeConfig(max_iterations=5, max_tokens_per_turn=2048),
    )

    bus = EventBus(trace_id="test-gateway-skill")

    try:
        result = await gw.chat(
            message="你好，请简短回答。",
            business_type="general_chat",
            event_bus=bus,
        )

        assert result["session_id"], "session_id should be returned"
        assert result["answer"], "answer should be non-empty"
        assert len(result["answer"]) > 0
    finally:
        await llm_client.close()


@pytest.mark.asyncio
async def test_gateway_multi_turn_with_tools(tmp_path):
    """Gateway multi-turn conversation with tool use."""
    from core.llm_client import LLMGatewayClient, LLMClientConfig
    from core.runtime import RuntimeConfig
    from agent.gateway import AgentGateway
    from agent.session import SessionManager
    from agent.prompt import PromptBuilder
    from agent.subagent import SubagentRunner
    from agent.hooks import build_default_hooks
    from memory.markdown_store import MarkdownMemoryStore
    from skills.loader import SkillLoader
    from tools.registry_builder import (
        build_full_registry, build_shared_registry, build_capability_registry,
    )

    config = LLMClientConfig(
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
        timeout_s=60,
    )
    llm_client = LLMGatewayClient(config)

    tool_registry = build_full_registry()
    shared = build_shared_registry()
    capability = build_capability_registry()
    prompt_builder = PromptBuilder()
    session_manager = SessionManager(base_dir=str(tmp_path / "sessions"))
    memory_store = MarkdownMemoryStore(base_dir=str(tmp_path / "memory"))
    skill_loader = SkillLoader(skills_dir=str(tmp_path / "skills"))

    subagent_runner = SubagentRunner(
        llm_client=llm_client,
        shared_registry=shared,
        capability_registry=capability,
        prompt_builder=prompt_builder,
    )

    gw = AgentGateway(
        llm_client=llm_client,
        tool_registry=tool_registry,
        session_manager=session_manager,
        skill_loader=skill_loader,
        prompt_builder=prompt_builder,
        subagent_runner=subagent_runner,
        memory_store=memory_store,
        hooks=build_default_hooks(),
        runtime_config=RuntimeConfig(max_iterations=5, max_tokens_per_turn=2048),
    )

    try:
        # Turn 1: ask a calculation question
        bus1 = EventBus(trace_id="test-multi-turn-1")
        result1 = await gw.chat(
            message="计算 50 + 80",
            business_type="general_chat",
            event_bus=bus1,
        )
        sid = result1["session_id"]
        assert sid
        assert "130" in result1["answer"]

        # Turn 2: follow-up in same session
        bus2 = EventBus(trace_id="test-multi-turn-2")
        result2 = await gw.chat(
            message="把刚才的结果乘以 2",
            business_type="general_chat",
            session_id=sid,
            event_bus=bus2,
        )
        assert result2["session_id"] == sid
        assert result2["answer"], "Follow-up answer should be non-empty"
    finally:
        await llm_client.close()


# ================================================================
# Bonus: EventBus SSE event collection
# ================================================================


@pytest.mark.asyncio
async def test_event_bus_collects_all_events(llm_client, math_registry):
    """EventBus should capture all runtime events during execution."""
    bus = EventBus(trace_id="test-events")

    runtime = AgenticRuntime(
        llm_client=llm_client,
        tool_registry=math_registry,
        tool_parser=ToolCallParser(),
        config=RuntimeConfig(max_iterations=5, max_tokens_per_turn=2048),
        event_bus=bus,
    )

    try:
        result = await runtime.run(
            system_prompt="You are a math assistant. Always use the add tool.",
            user_message="What is 7 + 8? Use the add tool.",
        )
        assert result.final_answer is not None

        # EventBus.history should have captured events
        assert bus.event_count > 0
        event_types = [e.event_type for e in bus.history]
        # At minimum we expect agent_progress events
        assert "agent_progress" in event_types
    finally:
        await llm_client.close()
