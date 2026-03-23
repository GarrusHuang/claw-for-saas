"""
Phase 5.3 — WorkflowAnalyzer (Skill 自动建议) 测试。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.skill_generator import WorkflowAnalyzer
from memory.markdown_store import MarkdownMemoryStore


@pytest.fixture
def store(tmp_path):
    return MarkdownMemoryStore(base_dir=str(tmp_path), max_prompt_chars=8000)


@pytest.fixture
def analyzer(store):
    return WorkflowAnalyzer(store, threshold=3)


class TestMakeFingerprint:

    def test_basic_sequence(self):
        fp = WorkflowAnalyzer.make_fingerprint(["read_uploaded_file", "arithmetic", "propose_plan"])
        assert fp == "read_uploaded_file|arithmetic|propose_plan"

    def test_dedup_consecutive(self):
        """连续相同工具名去重。"""
        fp = WorkflowAnalyzer.make_fingerprint(["read_uploaded_file", "read_uploaded_file", "arithmetic"])
        assert fp == "read_uploaded_file|arithmetic"

    def test_non_consecutive_duplicates_kept(self):
        """非连续重复保留。"""
        fp = WorkflowAnalyzer.make_fingerprint(["read_uploaded_file", "arithmetic", "read_uploaded_file"])
        assert fp == "read_uploaded_file|arithmetic|read_uploaded_file"

    def test_single_tool(self):
        fp = WorkflowAnalyzer.make_fingerprint(["arithmetic"])
        assert fp == "arithmetic"


class TestRecordWorkflow:

    def test_writes_to_log(self, analyzer):
        analyzer.record_workflow("T1", "U1", ["a", "b", "c"])
        log = analyzer._load_log("T1", "U1")
        assert len(log) == 1
        assert log[0]["fingerprint"] == "a|b|c"
        assert log[0]["tools"] == ["a", "b", "c"]
        assert log[0]["timestamp"]

    def test_less_than_3_tools_not_recorded(self, analyzer):
        """工具调用 < 3 不记录。"""
        analyzer.record_workflow("T1", "U1", ["a", "b"])
        log = analyzer._load_log("T1", "U1")
        assert len(log) == 0

    def test_max_100_entries(self, analyzer):
        """超过 100 条自动淘汰最旧。"""
        for i in range(110):
            analyzer.record_workflow("T1", "U1", ["a", "b", f"c{i}"])
        log = analyzer._load_log("T1", "U1")
        assert len(log) == 100
        # 最旧的应该被淘汰
        assert "c0" not in log[0]["fingerprint"]


class TestDetectRepeated:

    def test_3_times_detected(self, analyzer):
        """3 次相同 fingerprint 被检测到。"""
        for _ in range(3):
            analyzer.record_workflow("T1", "U1", ["read_uploaded_file", "arithmetic", "propose_plan"])
        result = analyzer.detect_repeated("T1", "U1")
        assert result is not None
        assert len(result) == 1
        assert result[0]["count"] == 3
        assert result[0]["fingerprint"] == "read_uploaded_file|arithmetic|propose_plan"

    def test_2_times_not_detected(self, analyzer):
        """2 次不触发 (threshold=3)。"""
        for _ in range(2):
            analyzer.record_workflow("T1", "U1", ["a", "b", "c"])
        result = analyzer.detect_repeated("T1", "U1")
        assert result is None

    def test_empty_log(self, analyzer):
        result = analyzer.detect_repeated("T1", "U1")
        assert result is None

    def test_mixed_fingerprints(self, analyzer):
        """不同 fingerprint 各自计数。"""
        for _ in range(3):
            analyzer.record_workflow("T1", "U1", ["a", "b", "c"])
        for _ in range(2):
            analyzer.record_workflow("T1", "U1", ["x", "y", "z"])
        result = analyzer.detect_repeated("T1", "U1")
        assert result is not None
        assert len(result) == 1
        assert result[0]["fingerprint"] == "a|b|c"


class TestGenerateSkillDraft:

    @pytest.mark.asyncio
    async def test_generate_success(self, analyzer):
        """LLM 返回合法 JSON → 解析成功。"""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = '{"name": "data_analysis", "description": "数据分析流程", "body": "# Steps\\n1. Read file"}'
        mock_client.chat_completion = AsyncMock(return_value=mock_resp)

        draft = await analyzer.generate_skill_draft(
            "read_uploaded_file|arithmetic|propose_plan",
            ["read_uploaded_file", "arithmetic", "propose_plan"],
            mock_client,
        )
        assert draft is not None
        assert draft["name"] == "data_analysis"
        assert draft["description"] == "数据分析流程"

    @pytest.mark.asyncio
    async def test_generate_with_code_block(self, analyzer):
        """LLM 返回 markdown code block 包裹的 JSON → 仍能解析。"""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = '```json\n{"name": "test_skill", "description": "test", "body": "body"}\n```'
        mock_client.chat_completion = AsyncMock(return_value=mock_resp)

        draft = await analyzer.generate_skill_draft("a|b|c", ["a", "b", "c"], mock_client)
        assert draft is not None
        assert draft["name"] == "test_skill"

    @pytest.mark.asyncio
    async def test_generate_failure_returns_none(self, analyzer):
        """LLM 调用失败 → 返回 None。"""
        mock_client = MagicMock()
        mock_client.chat_completion = AsyncMock(side_effect=Exception("timeout"))

        draft = await analyzer.generate_skill_draft("a|b|c", ["a", "b", "c"], mock_client)
        assert draft is None

    @pytest.mark.asyncio
    async def test_generate_empty_response(self, analyzer):
        """LLM 返回空 → 返回 None。"""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = ""
        mock_client.chat_completion = AsyncMock(return_value=mock_resp)

        draft = await analyzer.generate_skill_draft("a|b|c", ["a", "b", "c"], mock_client)
        assert draft is None
