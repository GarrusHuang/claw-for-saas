"""
E2E tests for agent/gateway.py — AgentGateway.chat() with REAL LLM.

These tests call the real LLM at http://127.0.0.1:7225/v1.
They are slow by nature and require network access to the LLM server.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import asyncio

from core.event_bus import EventBus

pytestmark = pytest.mark.llm


@pytest.fixture
async def gateway(tmp_path):
    from core.llm_client import LLMGatewayClient, LLMClientConfig
    from core.runtime import RuntimeConfig
    from agent.gateway import AgentGateway
    from agent.session import SessionManager
    from agent.prompt import PromptBuilder
    from agent.subagent import SubagentRunner
    from agent.hooks import build_default_hooks
    from memory.markdown_store import MarkdownMemoryStore
    from skills.loader import SkillLoader
    from tools.registry_builder import build_full_registry, build_shared_registry, build_capability_registry

    config = LLMClientConfig(
        base_url="http://127.0.0.1:7225/v1",
        model="instruct_model",
        api_key="not-needed",
        timeout_s=60,
    )
    llm_client = LLMGatewayClient(config)

    tool_registry = build_full_registry()
    shared = build_shared_registry()
    capability = build_capability_registry()
    prompt_builder = PromptBuilder()
    session_manager = SessionManager(base_dir=str(tmp_path / "sessions"))
    memory_store = MarkdownMemoryStore(base_dir=str(tmp_path / "memory"))

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
        skill_loader=SkillLoader(skills_dir=str(tmp_path / "skills")),
        prompt_builder=prompt_builder,
        subagent_runner=subagent_runner,
        memory_store=memory_store,
        hooks=build_default_hooks(),
        runtime_config=RuntimeConfig(max_iterations=5, max_tokens_per_turn=2048),
    )

    yield gw
    await llm_client.close()


@pytest.mark.asyncio
async def test_simple_chat(gateway):
    """Send a simple greeting and expect a non-empty answer with session_id."""
    bus = EventBus(trace_id="test-e2e-simple")

    result = await gateway.chat(
        message="你好",
        business_type="general_chat",
        event_bus=bus,
    )

    assert result["session_id"], "session_id should be returned"
    assert result["answer"], "answer should be non-empty"
    assert len(result["answer"]) > 0


@pytest.mark.asyncio
async def test_arithmetic_tool_use(gateway):
    """Ask for 123 + 456 and expect the answer to contain 579."""
    bus = EventBus(trace_id="test-e2e-arithmetic")

    result = await gateway.chat(
        message="计算 123 + 456 的结果",
        business_type="general_chat",
        event_bus=bus,
    )

    assert result["session_id"]
    assert "579" in result["answer"], f"Expected '579' in answer, got: {result['answer']}"


@pytest.mark.asyncio
async def test_session_persistence(gateway):
    """Chat twice with the same session_id to verify session resumption."""
    bus1 = EventBus(trace_id="test-e2e-session-1")

    # First message
    result1 = await gateway.chat(
        message="我的名字是小明，请记住。",
        business_type="general_chat",
        event_bus=bus1,
    )

    session_id = result1["session_id"]
    assert session_id, "First call should return a session_id"

    # Second message, reusing session_id
    bus2 = EventBus(trace_id="test-e2e-session-2")

    result2 = await gateway.chat(
        message="我叫什么名字？",
        business_type="general_chat",
        session_id=session_id,
        event_bus=bus2,
    )

    assert result2["session_id"] == session_id, "Second call should reuse the same session_id"
    assert result2["answer"], "Second answer should be non-empty"
