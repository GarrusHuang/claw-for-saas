"""
Tests for AgentGateway._auto_save_memory().

Phase 3A: 自动记忆提取 — 对话结束后 LLM 提取跨会话信息。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.gateway import AgentGateway


def _make_gateway(memory_store=None, llm_client=None):
    """创建最小 Gateway 实例。"""
    gw = AgentGateway.__new__(AgentGateway)
    gw.memory_store = memory_store
    gw.llm_client = llm_client
    gw.secret_redactor = None
    return gw


class TestAutoSaveMemoryGuards:
    """前置条件检查 — 不满足时直接跳过。"""

    @pytest.mark.asyncio
    async def test_skip_when_disabled(self):
        """memory_auto_extract_enabled=False 时跳过。"""
        store = MagicMock()
        gw = _make_gateway(store, llm_client=MagicMock())
        with patch("config.settings") as mock_settings:
            mock_settings.memory_auto_extract_enabled = False
            await gw._auto_save_memory(
                tenant_id="t1", user_id="u1",
                message="我喜欢表格格式", answer="好的，我记住了",
            )
        store.append_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_without_store(self):
        """没有 memory_store 时跳过。"""
        gw = _make_gateway(memory_store=None, llm_client=MagicMock())
        with patch("config.settings") as mock_settings:
            mock_settings.memory_auto_extract_enabled = True
            await gw._auto_save_memory(
                tenant_id="t1", user_id="u1",
                message="hello", answer="hi",
            )

    @pytest.mark.asyncio
    async def test_skip_without_llm_client(self):
        """没有 llm_client 时跳过。"""
        store = MagicMock()
        gw = _make_gateway(store, llm_client=None)
        with patch("config.settings") as mock_settings:
            mock_settings.memory_auto_extract_enabled = True
            await gw._auto_save_memory(
                tenant_id="t1", user_id="u1",
                message="hello", answer="hi",
            )
        store.append_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_short_message(self):
        """消息太短时跳过。"""
        store = MagicMock()
        llm = MagicMock()
        gw = _make_gateway(store, llm_client=llm)
        with patch("config.settings") as mock_settings:
            mock_settings.memory_auto_extract_enabled = True
            await gw._auto_save_memory(
                tenant_id="t1", user_id="u1",
                message="hi", answer="hello",
            )
        store.append_memory.assert_not_called()


class TestAutoSaveMemoryExtraction:
    """LLM 提取逻辑。"""

    @pytest.mark.asyncio
    async def test_extracts_and_saves(self):
        """正常提取并保存到 auto-learning.md。"""
        store = MagicMock()
        store.build_memory_prompt.return_value = ("", {})
        store.append_memory.return_value = True

        llm_resp = MagicMock()
        llm_resp.content = "- [偏好] 用户偏好表格格式输出\n- [角色] 用户是数据分析师"

        llm = MagicMock()
        llm.chat_completion = AsyncMock(return_value=llm_resp)

        gw = _make_gateway(store, llm_client=llm)
        gw.secret_redactor = None
        with patch("config.settings") as mock_settings:
            mock_settings.memory_auto_extract_enabled = True
            mock_settings.memory_auto_extract_max_tokens = 300
            await gw._auto_save_memory(
                tenant_id="t1", user_id="u1",
                message="我是一个数据分析师，请帮我用表格格式来回复所有的数据内容",
                answer="好的，我记住了你的偏好，以后会用表格格式输出数据，满足你的数据分析需求",
            )

        store.append_memory.assert_called_once()
        call_kwargs = store.append_memory.call_args
        assert call_kwargs[1]["scope"] == "user"
        assert call_kwargs[1]["filename"] == "auto-learning.md"
        assert "偏好" in call_kwargs[1]["content"]

    @pytest.mark.asyncio
    async def test_none_response_skips(self):
        """LLM 返回 NONE 时不保存。"""
        store = MagicMock()
        store.build_memory_prompt.return_value = ("", {})

        llm_resp = MagicMock()
        llm_resp.content = "NONE"

        llm = MagicMock()
        llm.chat_completion = AsyncMock(return_value=llm_resp)

        gw = _make_gateway(store, llm_client=llm)
        with patch("config.settings") as mock_settings:
            mock_settings.memory_auto_extract_enabled = True
            mock_settings.memory_auto_extract_max_tokens = 300
            await gw._auto_save_memory(
                tenant_id="t1", user_id="u1",
                message="今天天气怎么样？一般的闲聊",
                answer="今天天气不错，适合出门散步。",
            )

        store.append_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_response_skips(self):
        """LLM 返回空内容时不保存。"""
        store = MagicMock()
        store.build_memory_prompt.return_value = ("", {})

        llm_resp = MagicMock()
        llm_resp.content = ""

        llm = MagicMock()
        llm.chat_completion = AsyncMock(return_value=llm_resp)

        gw = _make_gateway(store, llm_client=llm)
        with patch("config.settings") as mock_settings:
            mock_settings.memory_auto_extract_enabled = True
            mock_settings.memory_auto_extract_max_tokens = 300
            await gw._auto_save_memory(
                tenant_id="t1", user_id="u1",
                message="请帮我计算 1+1 等于多少",
                answer="1+1 等于 2。",
            )

        store.append_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_silent(self):
        """LLM 调用失败时静默跳过。"""
        store = MagicMock()
        store.build_memory_prompt.return_value = ("", {})

        llm = MagicMock()
        llm.chat_completion = AsyncMock(side_effect=Exception("LLM unavailable"))

        gw = _make_gateway(store, llm_client=llm)
        with patch("config.settings") as mock_settings:
            mock_settings.memory_auto_extract_enabled = True
            mock_settings.memory_auto_extract_max_tokens = 300
            # Should not raise
            await gw._auto_save_memory(
                tenant_id="t1", user_id="u1",
                message="我是前端开发工程师，使用 React",
                answer="好的",
            )

        store.append_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout_silent(self):
        """LLM 调用超时时静默跳过。"""
        store = MagicMock()
        store.build_memory_prompt.return_value = ("", {})

        async def slow_call(*args, **kwargs):
            await asyncio.sleep(100)

        llm = MagicMock()
        llm.chat_completion = slow_call

        gw = _make_gateway(store, llm_client=llm)
        with patch("config.settings") as mock_settings:
            mock_settings.memory_auto_extract_enabled = True
            mock_settings.memory_auto_extract_max_tokens = 300
            # Should not raise, timeout after 15s
            # We patch asyncio.wait_for timeout to be very short for testing
            with patch("agent.gateway.asyncio.wait_for", side_effect=asyncio.TimeoutError):
                await gw._auto_save_memory(
                    tenant_id="t1", user_id="u1",
                    message="请帮我做一些数据处理的工作",
                    answer="好的，我来帮你处理",
                )

        store.append_memory.assert_not_called()
