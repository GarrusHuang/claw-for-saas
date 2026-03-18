"""
Integration tests for core/runtime.py — AgenticRuntime with REAL LLM.

LLM endpoint: from .env (LLM_BASE_URL / LLM_MODEL)
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from core.llm_client import LLMGatewayClient, LLMClientConfig
from core.runtime import AgenticRuntime, RuntimeConfig, RuntimeResult
from core.tool_registry import ToolRegistry
from core.tool_protocol import ToolCallParser
from core.event_bus import EventBus
from tests.conftest import LLM_BASE_URL, LLM_MODEL, LLM_API_KEY


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
def tool_registry():
    reg = ToolRegistry()

    @reg.tool(description="Add two numbers", read_only=True)
    def add(a: float, b: float) -> dict:
        return {"result": a + b}

    @reg.tool(description="Multiply two numbers", read_only=True)
    def multiply(a: float, b: float) -> dict:
        return {"result": a * b}

    return reg


@pytest.mark.llm
@pytest.mark.asyncio
async def test_simple_response(llm_client, tool_registry):
    """No tools needed — simple text response."""
    runtime = AgenticRuntime(
        llm_client=llm_client,
        tool_registry=ToolRegistry(),  # empty registry, no tools
        tool_parser=ToolCallParser(),
        config=RuntimeConfig(max_iterations=10, max_tokens_per_turn=2048),
        event_bus=EventBus(trace_id="test-simple"),
    )

    try:
        result = await runtime.run(
            system_prompt="You are a helpful assistant.",
            user_message="Say hello in one word.",
        )
        assert result.final_answer is not None
        assert len(result.final_answer) > 0
        assert result.iterations >= 1
    finally:
        await llm_client.close()


@pytest.mark.llm
@pytest.mark.asyncio
async def test_tool_use(llm_client, tool_registry):
    """LLM should use the add tool to compute a sum."""
    runtime = AgenticRuntime(
        llm_client=llm_client,
        tool_registry=tool_registry,
        tool_parser=ToolCallParser(),
        config=RuntimeConfig(max_iterations=10, max_tokens_per_turn=2048),
        event_bus=EventBus(trace_id="test-tool-use"),
    )

    try:
        result = await runtime.run(
            system_prompt="You are a helpful assistant. Use the add tool to compute sums. Always use tools when asked to calculate.",
            user_message="What is 10 + 20? Use the add tool to calculate this.",
        )
        assert "30" in result.final_answer
        assert result.tool_call_count >= 1
    finally:
        await llm_client.close()


@pytest.mark.llm
@pytest.mark.asyncio
async def test_max_iterations(llm_client, tool_registry):
    """With max_iterations=1, the runtime should stop after 1 iteration."""
    runtime = AgenticRuntime(
        llm_client=llm_client,
        tool_registry=tool_registry,
        tool_parser=ToolCallParser(),
        config=RuntimeConfig(max_iterations=1, max_tokens_per_turn=2048),
        event_bus=EventBus(trace_id="test-max-iter"),
    )

    try:
        result = await runtime.run(
            system_prompt="You are a helpful assistant. Always use tools for calculations. Use the add tool first, then the multiply tool.",
            user_message="First add 1+2 using the add tool, then multiply the result by 5 using the multiply tool. You must call both tools.",
        )
        # Either max_iterations_reached is True, or we stopped at 1 iteration
        assert result.max_iterations_reached is True or result.iterations == 1
    finally:
        await llm_client.close()


def test_runtime_config_defaults():
    """Unit test: RuntimeConfig has correct defaults."""
    config = RuntimeConfig()
    assert config.max_iterations == 10
    assert config.max_tokens_per_turn == 4096
    assert config.tool_call_timeout_s == 30.0
    assert config.parallel_tool_calls is True
    assert config.temperature is None
    assert config.max_tool_result_chars == 0  # 0 = dynamic calculation
    assert config.context_budget_tokens == 0  # A4: 默认动态计算
    assert config.model_context_window == 32000
    assert config.context_budget_ratio == 0.8
    assert config.compress_threshold_ratio == 0.70
    assert config.context_budget_min == 16000
    # 动态预算: 32000 * 0.8 = 25600
    assert config.get_effective_budget() == 25600


def test_runtime_result_defaults():
    """Unit test: RuntimeResult has correct defaults."""
    result = RuntimeResult(final_answer="test")
    assert result.final_answer == "test"
    assert result.steps == []
    assert result.iterations == 0
    assert result.max_iterations_reached is False
    assert result.error is None
    assert result.thinking == ""
    assert result.tool_call_count == 0
    assert result.tool_history == []
