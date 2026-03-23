"""
3.4 Guardian — AI 风险评估测试套件。

覆盖:
- 非高风险工具 → 跳过 (不调 LLM)
- risk_score < threshold → allow
- risk_score >= threshold → block
- LLM 超时 → block (fail closed)
- LLM 返回非法 JSON → block
- guardian_enabled=False → build_guardian_hook 返回 None
"""

from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from agent.guardian import GuardianAssessor, build_guardian_hook, _HIGH_RISK_TOOLS
from agent.hooks import HookEvent


# ── Fixtures ──

@dataclass
class FakeLLMResponse:
    content: str | None = None


def _make_assessor(threshold=80, timeout_s=30.0):
    """创建 GuardianAssessor with mock LLM client."""
    mock_client = AsyncMock()
    return GuardianAssessor(
        llm_client=mock_client,
        threshold=threshold,
        timeout_s=timeout_s,
    ), mock_client


def _make_event(tool_name="run_command", tool_input=None):
    """创建测试 HookEvent。"""
    return HookEvent(
        event_type="pre_tool_use",
        tool_name=tool_name,
        tool_input=tool_input or {"command": "ls -la"},
    )


# ── Tests ──


class TestGuardianAssessor:

    @pytest.mark.asyncio
    async def test_non_high_risk_tool_skipped(self):
        """非高风险工具直接放行，不调 LLM。"""
        assessor, mock_client = _make_assessor()

        event = _make_event(tool_name="arithmetic", tool_input={"expression": "1+1"})
        result = await assessor.assess(event)

        assert result.action == "allow"
        mock_client.chat_completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_low_risk_allows(self):
        """risk_score < threshold → allow。"""
        assessor, mock_client = _make_assessor(threshold=80)
        mock_client.chat_completion.return_value = FakeLLMResponse(
            content='{"risk_score": 20, "reason": "safe operation"}'
        )

        event = _make_event(tool_name="run_command", tool_input={"command": "ls -la"})
        result = await assessor.assess(event)

        assert result.action == "allow"
        mock_client.chat_completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_high_risk_blocks(self):
        """risk_score >= threshold → block。"""
        assessor, mock_client = _make_assessor(threshold=80)
        mock_client.chat_completion.return_value = FakeLLMResponse(
            content='{"risk_score": 90, "reason": "dangerous command"}'
        )

        event = _make_event(tool_name="run_command", tool_input={"command": "rm -rf /"})
        result = await assessor.assess(event)

        assert result.action == "block"
        assert "90" in result.message
        assert "dangerous command" in result.message

    @pytest.mark.asyncio
    async def test_exact_threshold_blocks(self):
        """risk_score == threshold → block。"""
        assessor, mock_client = _make_assessor(threshold=80)
        mock_client.chat_completion.return_value = FakeLLMResponse(
            content='{"risk_score": 80, "reason": "borderline"}'
        )

        event = _make_event()
        result = await assessor.assess(event)

        assert result.action == "block"

    @pytest.mark.asyncio
    async def test_timeout_blocks(self):
        """LLM 超时 → block (fail closed)。"""
        assessor, mock_client = _make_assessor(timeout_s=0.1)
        mock_client.chat_completion.side_effect = asyncio.TimeoutError()

        event = _make_event()
        result = await assessor.assess(event)

        assert result.action == "block"
        assert "超时" in result.message

    @pytest.mark.asyncio
    async def test_invalid_json_blocks(self):
        """LLM 返回非法 JSON → block (fail closed)。"""
        assessor, mock_client = _make_assessor()
        mock_client.chat_completion.return_value = FakeLLMResponse(
            content="This is not JSON"
        )

        event = _make_event()
        result = await assessor.assess(event)

        assert result.action == "block"
        assert "解析失败" in result.message

    @pytest.mark.asyncio
    async def test_empty_response_blocks(self):
        """LLM 返回空内容 → block (fail closed)。"""
        assessor, mock_client = _make_assessor()
        mock_client.chat_completion.return_value = FakeLLMResponse(content=None)

        event = _make_event()
        result = await assessor.assess(event)

        assert result.action == "block"

    @pytest.mark.asyncio
    async def test_unexpected_error_blocks(self):
        """LLM 未知异常 → block (fail closed)。"""
        assessor, mock_client = _make_assessor()
        mock_client.chat_completion.side_effect = RuntimeError("connection refused")

        event = _make_event()
        result = await assessor.assess(event)

        assert result.action == "block"
        assert "异常" in result.message

    @pytest.mark.asyncio
    async def test_write_source_file_assessed(self):
        """write_source_file 是高风险工具，需要评估。"""
        assessor, mock_client = _make_assessor()
        mock_client.chat_completion.return_value = FakeLLMResponse(
            content='{"risk_score": 30, "reason": "writing temp file"}'
        )

        event = _make_event(
            tool_name="write_source_file",
            tool_input={"path": "/tmp/test.py", "content": "print('hello')"},
        )
        result = await assessor.assess(event)

        assert result.action == "allow"
        mock_client.chat_completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_patch_assessed(self):
        """apply_patch 是高风险工具，需要评估。"""
        assessor, mock_client = _make_assessor()
        mock_client.chat_completion.return_value = FakeLLMResponse(
            content='{"risk_score": 50, "reason": "code modification"}'
        )

        event = _make_event(
            tool_name="apply_patch",
            tool_input={"patch": "some patch content"},
        )
        result = await assessor.assess(event)

        assert result.action == "allow"

    @pytest.mark.asyncio
    async def test_markdown_code_block_response(self):
        """LLM 返回 markdown 包裹的 JSON。"""
        assessor, mock_client = _make_assessor()
        mock_client.chat_completion.return_value = FakeLLMResponse(
            content='```json\n{"risk_score": 25, "reason": "safe"}\n```'
        )

        event = _make_event()
        result = await assessor.assess(event)

        assert result.action == "allow"


class TestBuildGuardianHook:

    def test_disabled_returns_none(self):
        """guardian_enabled=False → None。"""
        mock_settings = MagicMock()
        mock_settings.guardian_enabled = False
        result = build_guardian_hook(mock_settings)
        assert result is None

    def test_enabled_returns_callable(self):
        """guardian_enabled=True → callable。"""
        mock_settings = MagicMock()
        mock_settings.guardian_enabled = True
        mock_settings.guardian_model = "test-model"
        mock_settings.guardian_base_url = "http://localhost:8080/v1"
        mock_settings.guardian_api_key = "test-key"
        mock_settings.guardian_risk_threshold = 80
        mock_settings.guardian_timeout_s = 10.0
        mock_settings.llm_base_url = "http://localhost:11434/v1"
        mock_settings.llm_model = "fallback-model"
        mock_settings.llm_api_key = "fallback-key"

        result = build_guardian_hook(mock_settings)
        assert callable(result)

    def test_enabled_uses_fallback_config(self):
        """guardian_model 为空时复用主模型配置。"""
        mock_settings = MagicMock()
        mock_settings.guardian_enabled = True
        mock_settings.guardian_model = ""  # 空=复用
        mock_settings.guardian_base_url = ""
        mock_settings.guardian_api_key = ""
        mock_settings.guardian_risk_threshold = 70
        mock_settings.guardian_timeout_s = 15.0
        mock_settings.llm_base_url = "http://main:11434/v1"
        mock_settings.llm_model = "main-model"
        mock_settings.llm_api_key = "main-key"

        result = build_guardian_hook(mock_settings)
        assert callable(result)


class TestHighRiskTools:
    """验证高风险工具列表。"""

    def test_contains_expected_tools(self):
        assert "run_command" in _HIGH_RISK_TOOLS
        assert "write_source_file" in _HIGH_RISK_TOOLS
        assert "apply_patch" in _HIGH_RISK_TOOLS

    def test_does_not_contain_read_tools(self):
        assert "read_source_file" not in _HIGH_RISK_TOOLS
        assert "arithmetic" not in _HIGH_RISK_TOOLS
