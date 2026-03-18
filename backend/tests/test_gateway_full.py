"""
T6: Gateway 全流程测试 (真实 LLM)。

使用真实 LLM 验证 Gateway.chat() 完整链路。
"""
from __future__ import annotations

import os
import tempfile

import pytest

from tests.conftest import LLM_BASE_URL, LLM_MODEL, LLM_API_KEY


def _build_gateway(tmp_dir: str):
    """构建最小化 Gateway (真实 LLM，临时存储)。"""
    from agent.gateway import AgentGateway
    from agent.hooks import build_default_hooks
    from agent.prompt import PromptBuilder
    from agent.session import SessionManager
    from agent.subagent import SubagentRunner
    from core.llm_client import LLMGatewayClient, LLMClientConfig
    from core.runtime import RuntimeConfig
    from core.tool_registry import ToolRegistry
    from memory.markdown_store import MarkdownMemoryStore
    from tools.registry_builder import build_shared_registry, build_capability_registry

    llm_config = LLMClientConfig(
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        api_key=LLM_API_KEY or "not-needed",
        timeout_s=60,
    )
    llm_client = LLMGatewayClient(llm_config)

    shared = build_shared_registry()
    capability = build_capability_registry()
    tool_registry = shared.merge(capability)

    session_dir = os.path.join(tmp_dir, "sessions")
    memory_dir = os.path.join(tmp_dir, "memory")

    session_manager = SessionManager(base_dir=session_dir)
    memory_store = MarkdownMemoryStore(base_dir=memory_dir)
    prompt_builder = PromptBuilder()
    hooks = build_default_hooks()

    subagent_runner = SubagentRunner(
        llm_client=llm_client,
        shared_registry=shared,
        capability_registry=capability,
        prompt_builder=prompt_builder,
        hooks=hooks,
    )

    runtime_config = RuntimeConfig(
        max_iterations=5,
        max_tokens_per_turn=1024,
    )

    return AgentGateway(
        llm_client=llm_client,
        tool_registry=tool_registry,
        session_manager=session_manager,
        skill_loader=None,
        prompt_builder=prompt_builder,
        subagent_runner=subagent_runner,
        memory_store=memory_store,
        hooks=hooks,
        runtime_config=runtime_config,
    )


@pytest.mark.llm
class TestGatewayFullFlow:
    """Gateway.chat() 完整流程 (真实 LLM)。"""

    @pytest.mark.asyncio
    async def test_simple_chat(self, tmp_path):
        """发送简单消息，验证返回结构。"""
        gw = _build_gateway(str(tmp_path))
        result = await gw.chat(
            tenant_id="T1",
            user_id="U1",
            message="你好，请用一句话回答：1+1等于几？",
            business_type="general_chat",
        )

        assert "session_id" in result
        assert result["session_id"].startswith("sess-")
        assert "answer" in result
        assert len(result["answer"]) > 0
        assert result["iterations"] >= 1
        assert "duration_ms" in result

    @pytest.mark.asyncio
    async def test_session_continuity(self, tmp_path):
        """验证会话续接。"""
        gw = _build_gateway(str(tmp_path))

        # 第一次对话
        r1 = await gw.chat(
            tenant_id="T1",
            user_id="U1",
            message="请记住：我的名字是测试用户。",
            business_type="general_chat",
        )
        session_id = r1["session_id"]

        # 续接同一会话
        r2 = await gw.chat(
            tenant_id="T1",
            user_id="U1",
            session_id=session_id,
            message="我叫什么名字？",
            business_type="general_chat",
        )

        assert r2["session_id"] == session_id
        assert len(r2["answer"]) > 0

    @pytest.mark.asyncio
    async def test_result_has_no_error(self, tmp_path):
        """正常对话不应有 error 字段。"""
        gw = _build_gateway(str(tmp_path))
        result = await gw.chat(
            tenant_id="T1",
            user_id="U1",
            message="简单回答：天空是什么颜色？",
            business_type="general_chat",
        )
        assert "error" not in result
