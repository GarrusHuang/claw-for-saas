"""
#43: 语义质量检查测试。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.hooks import HookEvent, HookResult
from agent.quality_gate import semantic_quality_hook, reset_correction_count


_test_counter = 0

def _make_event(final_answer="详细的分析结果", tools=None):
    global _test_counter
    _test_counter += 1
    if tools is None:
        tools = [
            {"tool": "read_uploaded_file", "args": {"file_id": "f1"}, "result": "文件内容: 收入100万"},
            {"tool": "arithmetic", "args": {"expression": "100*1.1"}, "result": "110"},
        ]
    return HookEvent(
        event_type="agent_stop",
        user_id="U1",
        session_id=f"S_{_test_counter}",
        runtime_steps=tools,
        context={"final_answer": final_answer},
    )


class TestSkipConditions:
    """跳过检查的场景 → 全部放行。"""

    @pytest.mark.asyncio
    async def test_skip_short_answer(self):
        event = _make_event(final_answer="OK")
        result = await semantic_quality_hook(event)
        assert result.action == "allow"

    @pytest.mark.asyncio
    async def test_skip_no_tools(self):
        event = _make_event(tools=[])
        result = await semantic_quality_hook(event)
        assert result.action == "allow"

    @pytest.mark.asyncio
    async def test_skip_max_corrections_reached(self):
        from agent.quality_gate import _correction_counts, MAX_SELF_CORRECTIONS
        import time
        key = "U1:S1"
        _correction_counts[key] = (MAX_SELF_CORRECTIONS, time.time())
        try:
            event = _make_event()
            result = await semantic_quality_hook(event)
            assert result.action == "allow"
        finally:
            reset_correction_count(key)


class TestLLMIntegration:
    """LLM 调用场景。"""

    @pytest.mark.asyncio
    async def test_pass_response(self):
        """LLM 返回 PASS → 放行。"""
        mock_resp = MagicMock()
        mock_resp.content = "PASS"
        mock_llm = MagicMock()
        mock_llm.chat_completion = AsyncMock(return_value=mock_resp)

        with patch("dependencies.get_llm_client", return_value=mock_llm):
            event = _make_event(final_answer="根据文件内容，收入为100万，增长10%后为110万。")
            result = await semantic_quality_hook(event)
            assert result.action == "allow"

    @pytest.mark.asyncio
    async def test_fail_response_blocks(self):
        """LLM 返回 FAIL → block + 修正消息。"""
        # 清除可能的残留状态
        reset_correction_count("U1:S_fail")

        mock_resp = MagicMock()
        mock_resp.content = "FAIL|回复中提到利润200万但工具结果中没有利润数据|请只报告工具结果中存在的数据"
        mock_llm = MagicMock()
        mock_llm.chat_completion = AsyncMock(return_value=mock_resp)

        event = HookEvent(
            event_type="agent_stop", user_id="U1", session_id="S_fail",
            runtime_steps=[
                {"tool": "read_uploaded_file", "args": {}, "result": "收入100万"},
            ],
            context={"final_answer": "根据分析，收入100万，利润200万，增长率10%。" + "x" * 50},
        )

        with patch("dependencies.get_llm_client", return_value=mock_llm):
            result = await semantic_quality_hook(event)
            assert result.action == "block", f"Expected block but got {result.action}, msg={result.message}"
            assert "语义检查" in result.message

    @pytest.mark.asyncio
    async def test_llm_timeout_allows(self):
        """LLM 超时 → fail-open 放行。"""
        import asyncio
        mock_llm = MagicMock()
        mock_llm.chat_completion = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("dependencies.get_llm_client", return_value=mock_llm), \
             patch("config.settings") as mock_cfg:
            mock_cfg.guardian_enabled = True
            mock_cfg.guardian_model = ""
            mock_cfg.guardian_base_url = ""
            mock_cfg.guardian_api_key = ""
            mock_cfg.guardian_timeout_s = 1
            mock_cfg.llm_base_url = "http://localhost"
            mock_cfg.llm_model = "test"
            mock_cfg.llm_api_key = "key"

            event = _make_event()
            result = await semantic_quality_hook(event)
            assert result.action == "allow"

    @pytest.mark.asyncio
    async def test_llm_error_allows(self):
        """LLM 报错 → fail-open 放行。"""
        mock_llm = MagicMock()
        mock_llm.chat_completion = AsyncMock(side_effect=Exception("connection refused"))

        with patch("dependencies.get_llm_client", return_value=mock_llm), \
             patch("config.settings") as mock_cfg:
            mock_cfg.guardian_enabled = True
            mock_cfg.guardian_model = ""
            mock_cfg.guardian_base_url = ""
            mock_cfg.guardian_api_key = ""
            mock_cfg.guardian_timeout_s = 10
            mock_cfg.llm_base_url = "http://localhost"
            mock_cfg.llm_model = "test"
            mock_cfg.llm_api_key = "key"

            event = _make_event()
            result = await semantic_quality_hook(event)
            assert result.action == "allow"

    @pytest.mark.asyncio
    async def test_empty_llm_response_allows(self):
        """LLM 返回空 → 放行。"""
        mock_resp = MagicMock()
        mock_resp.content = ""
        mock_llm = MagicMock()
        mock_llm.chat_completion = AsyncMock(return_value=mock_resp)

        with patch("dependencies.get_llm_client", return_value=mock_llm), \
             patch("config.settings") as mock_cfg:
            mock_cfg.guardian_enabled = True
            mock_cfg.guardian_model = ""
            mock_cfg.guardian_base_url = ""
            mock_cfg.guardian_api_key = ""
            mock_cfg.guardian_timeout_s = 10
            mock_cfg.llm_base_url = "http://localhost"
            mock_cfg.llm_model = "test"
            mock_cfg.llm_api_key = "key"

            event = _make_event()
            result = await semantic_quality_hook(event)
            assert result.action == "allow"


class TestRegistration:
    """Hook 注册测试。"""

    def test_registered_when_guardian_enabled(self):
        """guardian_enabled=True 时，semantic_quality_hook 被注册到 agent_stop。"""
        with patch("config.settings") as mock_cfg:
            mock_cfg.guardian_enabled = True
            # Guardian hook builder 会失败 (没有真实 LLM)，但 semantic hook 应仍注册
            from agent.hooks import build_default_hooks
            hooks = build_default_hooks()
            # 检查 agent_stop handlers 中包含 semantic_quality_hook
            agent_stop_handlers = hooks._handlers.get("agent_stop", [])
            handler_names = [h.handler.__name__ for h in agent_stop_handlers]
            assert "semantic_quality_hook" in handler_names

    def test_not_registered_when_guardian_disabled(self):
        """guardian_enabled=False 时不注册。"""
        with patch("config.settings") as mock_cfg:
            mock_cfg.guardian_enabled = False
            from agent.hooks import build_default_hooks
            hooks = build_default_hooks()
            agent_stop_handlers = hooks._handlers.get("agent_stop", [])
            handler_names = [h.handler.__name__ for h in agent_stop_handlers]
            assert "semantic_quality_hook" not in handler_names
