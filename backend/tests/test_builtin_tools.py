"""
Tests for 6 builtin tool modules:
- calculator, code_tools, file_tools, browser_tools, skill_reference, subagent_tools
"""

import sys
import os
import json
import asyncio
import tempfile
from unittest.mock import MagicMock, AsyncMock, patch
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from core.context import (
    current_event_bus,
    current_sandbox,
    current_tenant_id,
    current_user_id,
    current_session_id,
    current_file_service,
    current_browser_service,
)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _set_ctx(**kwargs):
    """Set contextvars, return list of (var, token) for cleanup."""
    tokens = []
    mapping = {
        "event_bus": current_event_bus,
        "sandbox": current_sandbox,
        "tenant_id": current_tenant_id,
        "user_id": current_user_id,
        "session_id": current_session_id,
        "file_service": current_file_service,
        "browser_service": current_browser_service,
    }
    for key, val in kwargs.items():
        var = mapping[key]
        tokens.append((var, var.set(val)))
    return tokens


def _reset_ctx(tokens):
    for var, tok in tokens:
        var.reset(tok)


# ══════════════════════════════════════════════
# Calculator Tools
# ══════════════════════════════════════════════

from tools.builtin.calculator import (
    numeric_compare,
    sum_values,
    calculate_ratio,
    date_diff,
    arithmetic,
)


class TestNumericCompare:
    def test_equal(self):
        r = numeric_compare(5.0, 5.0, "eq")
        assert r["pass"] is True
        assert r["diff"] == 0.0

    def test_not_equal(self):
        r = numeric_compare(5.0, 5.0, "ne")
        assert r["pass"] is False

    def test_greater(self):
        r = numeric_compare(10.0, 5.0, "gt")
        assert r["pass"] is True

    def test_less(self):
        r = numeric_compare(3.0, 5.0, "lt")
        assert r["pass"] is True

    def test_lte_equal(self):
        r = numeric_compare(5.0, 5.0, "lte")
        assert r["pass"] is True

    def test_gte_equal(self):
        r = numeric_compare(5.0, 5.0, "gte")
        assert r["pass"] is True

    def test_floats(self):
        r = numeric_compare(0.1 + 0.2, 0.3, "lte")
        # 0.1+0.2 = 0.30000000000000004 > 0.3
        assert r["pass"] is False

    def test_negative(self):
        r = numeric_compare(-10.0, -5.0, "lt")
        assert r["pass"] is True

    def test_unknown_operator(self):
        r = numeric_compare(1.0, 2.0, "invalid")
        assert "error" in r


class TestSumValues:
    def test_normal(self):
        r = sum_values([1, 2, 3])
        assert r["total"] == 6.0
        assert r["count"] == 3

    def test_with_labels(self):
        r = sum_values([10, 20], labels=["a", "b"])
        assert r["total"] == 30.0
        assert r["breakdown"][0]["label"] == "a"

    def test_empty_list(self):
        r = sum_values([])
        assert r["total"] == 0.0
        assert r["count"] == 0

    def test_mixed_types(self):
        r = sum_values([1, "2.5", 3])
        assert r["total"] == 6.5

    def test_invalid_value(self):
        r = sum_values([1, "abc", 3])
        assert "error" in r


class TestCalculateRatio:
    def test_normal(self):
        r = calculate_ratio(1.0, 4.0)
        assert r["ratio"] == 0.25
        assert r["percentage"] == 25.0

    def test_division_by_zero(self):
        r = calculate_ratio(1.0, 0.0)
        assert r["error"] == "Division by zero"


class TestDateDiff:
    def test_same_day(self):
        r = date_diff("2024-01-01", "2024-01-01")
        assert r["days"] == 0

    def test_different_days(self):
        r = date_diff("2024-01-01", "2024-01-10")
        assert r["days"] == 9
        assert r["absolute_days"] == 9

    def test_reverse_order(self):
        r = date_diff("2024-01-10", "2024-01-01")
        assert r["days"] == -9
        assert r["absolute_days"] == 9

    def test_invalid_format(self):
        r = date_diff("not-a-date", "2024-01-01")
        assert "error" in r


class TestArithmetic:
    def test_add(self):
        r = arithmetic(3.0, 4.0, "add")
        assert r["result"] == 7.0

    def test_subtract(self):
        r = arithmetic(10.0, 3.0, "subtract")
        assert r["result"] == 7.0

    def test_multiply(self):
        r = arithmetic(3.0, 4.0, "multiply")
        assert r["result"] == 12.0

    def test_divide(self):
        r = arithmetic(10.0, 4.0, "divide")
        assert r["result"] == 2.5

    def test_divide_by_zero(self):
        r = arithmetic(10.0, 0.0, "divide")
        assert r["error"] == "Division by zero"

    def test_unknown_operation(self):
        r = arithmetic(1.0, 2.0, "modulo")
        assert "error" in r

    def test_expression_field(self):
        r = arithmetic(2.0, 3.0, "add")
        assert "2.0 + 3.0 = 5.0" in r["expression"]


# ══════════════════════════════════════════════
# Code Tools
# ══════════════════════════════════════════════

from tools.builtin.code_tools import (
    read_source_file,
    write_source_file,
    run_command,
)


class TestReadSourceFile:
    def test_file_exists(self, tmp_path):
        f = tmp_path / "hello.py"
        f.write_text("print('hello')\nline2\n", encoding="utf-8")

        mock_sandbox = MagicMock()
        mock_sandbox.get_workspace.return_value = str(tmp_path)
        mock_sandbox.validate_path.return_value = str(f)

        tokens = _set_ctx(sandbox=mock_sandbox, tenant_id="T1", user_id="U1", session_id="S1")
        try:
            r = read_source_file(str(f))
            assert r["content"].startswith("print('hello')")
            assert r["line_count"] == 3  # trailing newline creates empty last line
        finally:
            _reset_ctx(tokens)

    def test_file_not_found(self, tmp_path):
        mock_sandbox = MagicMock()
        mock_sandbox.get_workspace.return_value = str(tmp_path)
        mock_sandbox.validate_path.return_value = str(tmp_path / "nope.txt")

        tokens = _set_ctx(sandbox=mock_sandbox, tenant_id="T1", user_id="U1", session_id="S1")
        try:
            r = read_source_file(str(tmp_path / "nope.txt"))
            assert "error" in r
            assert "不存在" in r["error"]
        finally:
            _reset_ctx(tokens)

    def test_path_traversal_blocked(self, tmp_path):
        mock_sandbox = MagicMock()
        mock_sandbox.get_workspace.return_value = str(tmp_path)
        mock_sandbox.validate_path.side_effect = PermissionError("不在工作空间内")

        tokens = _set_ctx(sandbox=mock_sandbox, tenant_id="T1", user_id="U1", session_id="S1")
        try:
            r = read_source_file("/etc/passwd")
            assert "error" in r
            assert "不在工作空间内" in r["error"]
        finally:
            _reset_ctx(tokens)


class TestWriteSourceFile:
    def test_create_file(self, tmp_path):
        target = tmp_path / "new_file.txt"
        mock_sandbox = MagicMock()
        mock_sandbox.get_workspace.return_value = str(tmp_path)
        mock_sandbox.validate_path.return_value = str(target)
        mock_sandbox.check_disk_quota.return_value = {"exceeded": False, "used_mb": 0, "quota_mb": 500}

        mock_bus = MagicMock()
        tokens = _set_ctx(sandbox=mock_sandbox, event_bus=mock_bus, tenant_id="T1", user_id="U1", session_id="S1")
        try:
            r = write_source_file(str(target), "hello world", mode="create")
            assert "error" not in r
            assert r["mode"] == "create"
            assert target.read_text() == "hello world"
        finally:
            _reset_ctx(tokens)

    def test_quota_exceeded(self, tmp_path):
        mock_sandbox = MagicMock()
        mock_sandbox.get_workspace.return_value = str(tmp_path)
        mock_sandbox.validate_path.return_value = str(tmp_path / "file.txt")
        mock_sandbox.check_disk_quota.return_value = {"exceeded": True, "used_mb": 600, "quota_mb": 500}

        tokens = _set_ctx(sandbox=mock_sandbox, tenant_id="T1", user_id="U1", session_id="S1")
        try:
            r = write_source_file(str(tmp_path / "file.txt"), "data")
            assert "error" in r
            assert "配额" in r["error"]
        finally:
            _reset_ctx(tokens)


class TestRunCommand:
    def test_normal_command(self, tmp_path):
        """Run a simple echo command without sandbox (fallback mode)."""
        mock_bus = MagicMock()
        tokens = _set_ctx(sandbox=None, event_bus=mock_bus)
        try:
            # Use CODE_ALLOWED_PATHS to allow cwd
            with patch.dict(os.environ, {"CODE_ALLOWED_PATHS": str(tmp_path)}):
                r = run_command("echo hello", timeout=10)
                assert r["exit_code"] == 0
                assert "hello" in r["stdout"]
        finally:
            _reset_ctx(tokens)

    def test_command_with_sandbox_blacklist(self, tmp_path):
        """When sandbox blocks a command, it should return the sandbox result."""
        mock_sandbox = MagicMock()
        mock_sandbox.get_workspace.return_value = str(tmp_path)
        mock_sandbox.run_command.return_value = {
            "exit_code": -1,
            "error": "命令被拒绝: rm -rf 在黑名单中",
            "blocked": True,
        }
        mock_bus = MagicMock()
        tokens = _set_ctx(sandbox=mock_sandbox, event_bus=mock_bus, tenant_id="T1", user_id="U1", session_id="S1")
        try:
            r = run_command("rm -rf /")
            assert r.get("blocked") or r.get("error")
        finally:
            _reset_ctx(tokens)

    def test_timeout(self, tmp_path):
        """Command that exceeds timeout should report timed_out."""
        tokens = _set_ctx(sandbox=None, event_bus=None)
        try:
            with patch.dict(os.environ, {"CODE_ALLOWED_PATHS": str(tmp_path)}):
                r = run_command("sleep 10", timeout=1)
                assert r.get("timed_out") is True or r["exit_code"] == -1
        finally:
            _reset_ctx(tokens)


# ══════════════════════════════════════════════
# File Tools
# ══════════════════════════════════════════════

from tools.builtin.file_tools import (
    read_uploaded_file,
    list_user_files,
    analyze_file,
)


def _make_file_metadata(filename="test.txt", content_type="text/plain", size_bytes=100, sha256="abc123"):
    return SimpleNamespace(
        file_id="f1",
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        sha256=sha256,
    )


class TestReadUploadedFile:
    def test_read_full_file(self):
        mock_service = MagicMock()
        mock_service.extract_text.return_value = "Hello world content"
        meta = _make_file_metadata()
        mock_service.get_file.return_value = (meta, b"Hello world content")

        tokens = _set_ctx(file_service=mock_service, tenant_id="T1", user_id="U1")
        try:
            with patch("config.settings", SimpleNamespace(agent_model_context_window=32000)):
                r = read_uploaded_file("f1")
                assert r["text"] == "Hello world content"
                assert r["filename"] == "test.txt"
        finally:
            _reset_ctx(tokens)

    def test_file_not_found(self):
        mock_service = MagicMock()
        mock_service.extract_text.side_effect = FileNotFoundError("not found")

        tokens = _set_ctx(file_service=mock_service, tenant_id="T1", user_id="U1")
        try:
            r = read_uploaded_file("missing")
            assert "error" in r
            assert "not found" in r["error"].lower()
        finally:
            _reset_ctx(tokens)

    def test_pagination(self):
        long_text = "line1\nline2\nline3\nline4\nline5\n" * 20000  # >50K chars
        mock_service = MagicMock()
        mock_service.extract_text.return_value = long_text
        meta = _make_file_metadata(size_bytes=len(long_text))
        mock_service.get_file.return_value = (meta, long_text.encode())

        tokens = _set_ctx(file_service=mock_service, tenant_id="T1", user_id="U1")
        try:
            # Use a small context window to force pagination
            with patch("config.settings", SimpleNamespace(agent_model_context_window=32000)):
                r = read_uploaded_file("f1", offset=0, limit=100)
                assert "pagination" in r
                assert r["pagination"]["has_more"] is True
                assert len(r["text"]) <= 100
        finally:
            _reset_ctx(tokens)


class TestListUserFiles:
    def test_with_files(self):
        mock_service = MagicMock()
        mock_service.list_files.return_value = [
            SimpleNamespace(file_id="f1", filename="a.txt", content_type="text/plain", size_bytes=10),
            SimpleNamespace(file_id="f2", filename="b.pdf", content_type="application/pdf", size_bytes=200),
        ]
        tokens = _set_ctx(file_service=mock_service, tenant_id="T1", user_id="U1")
        try:
            r = list_user_files()
            assert r["file_count"] == 2
            assert r["files"][0]["file_id"] == "f1"
        finally:
            _reset_ctx(tokens)

    def test_empty(self):
        mock_service = MagicMock()
        mock_service.list_files.return_value = []
        tokens = _set_ctx(file_service=mock_service, tenant_id="T1", user_id="U1")
        try:
            r = list_user_files()
            assert r["file_count"] == 0
            assert r["files"] == []
        finally:
            _reset_ctx(tokens)


class TestAnalyzeFile:
    def test_basic_metadata(self):
        meta = _make_file_metadata(filename="data.csv", content_type="text/csv", size_bytes=500, sha256="deadbeef")
        content = b"col1,col2\nval1,val2\nval3,val4"
        mock_service = MagicMock()
        mock_service.get_file.return_value = (meta, content)

        tokens = _set_ctx(file_service=mock_service, tenant_id="T1", user_id="U1")
        try:
            r = analyze_file("f1")
            assert r["filename"] == "data.csv"
            assert r["size_bytes"] == 500
            assert r["sha256"] == "deadbeef"
            assert r["line_count"] == 3
            assert r["format"] == "CSV"
        finally:
            _reset_ctx(tokens)

    def test_file_not_found(self):
        mock_service = MagicMock()
        mock_service.get_file.side_effect = FileNotFoundError("nope")

        tokens = _set_ctx(file_service=mock_service, tenant_id="T1", user_id="U1")
        try:
            r = analyze_file("missing")
            assert "error" in r
        finally:
            _reset_ctx(tokens)


# ══════════════════════════════════════════════
# Browser Tools
# ══════════════════════════════════════════════

from tools.builtin.browser_tools import _validate_url, open_url


class TestValidateUrl:
    def test_no_sandbox_allows(self):
        tokens = _set_ctx(sandbox=None)
        try:
            assert _validate_url("https://example.com") is None
        finally:
            _reset_ctx(tokens)

    def test_sandbox_allows(self):
        mock_sandbox = MagicMock()
        mock_sandbox.validate_url.return_value = None
        tokens = _set_ctx(sandbox=mock_sandbox)
        try:
            assert _validate_url("https://example.com") is None
        finally:
            _reset_ctx(tokens)

    def test_sandbox_blocks_private(self):
        mock_sandbox = MagicMock()
        mock_sandbox.validate_url.return_value = "私有网络地址被阻止"
        tokens = _set_ctx(sandbox=mock_sandbox)
        try:
            result = _validate_url("http://192.168.1.1")
            assert result is not None
            assert "阻止" in result
        finally:
            _reset_ctx(tokens)

    def test_sandbox_whitelist_reject(self):
        mock_sandbox = MagicMock()
        mock_sandbox.validate_url.return_value = "URL 不在白名单中"
        tokens = _set_ctx(sandbox=mock_sandbox)
        try:
            result = _validate_url("https://evil.com")
            assert result is not None
        finally:
            _reset_ctx(tokens)


class TestOpenUrl:
    @pytest.mark.asyncio
    async def test_with_sandbox_allowed(self):
        mock_sandbox = MagicMock()
        mock_sandbox.validate_url.return_value = None

        mock_browser = AsyncMock()
        mock_browser.open_page.return_value = {
            "url": "https://example.com",
            "title": "Example",
            "status": 200,
        }
        mock_bus = MagicMock()

        tokens = _set_ctx(sandbox=mock_sandbox, browser_service=mock_browser, event_bus=mock_bus)
        try:
            r = await open_url("https://example.com")
            assert r["title"] == "Example"
            assert r["status"] == 200
        finally:
            _reset_ctx(tokens)

    @pytest.mark.asyncio
    async def test_url_rejected(self):
        mock_sandbox = MagicMock()
        mock_sandbox.validate_url.return_value = "blocked"

        tokens = _set_ctx(sandbox=mock_sandbox)
        try:
            with pytest.raises(RuntimeError, match="被拒绝"):
                await open_url("http://192.168.1.1")
        finally:
            _reset_ctx(tokens)

    @pytest.mark.asyncio
    async def test_without_sandbox(self):
        mock_browser = AsyncMock()
        mock_browser.open_page.return_value = {
            "url": "https://example.com",
            "title": "Example",
            "status": 200,
        }
        mock_bus = MagicMock()

        tokens = _set_ctx(sandbox=None, browser_service=mock_browser, event_bus=mock_bus)
        try:
            r = await open_url("https://example.com")
            assert r["status"] == 200
        finally:
            _reset_ctx(tokens)


# ══════════════════════════════════════════════
# Skill Reference
# ══════════════════════════════════════════════

from tools.builtin.skill_reference import read_reference


class TestReadReference:
    @pytest.mark.asyncio
    async def test_valid_reference(self):
        r = await read_reference("expense", "standard_table")
        assert r["skill_name"] == "expense"
        assert r["reference_name"] == "standard_table"
        assert r["loaded"] is False
        assert "not found" in r["content"]

    @pytest.mark.asyncio
    async def test_another_reference(self):
        r = await read_reference("contract", "clause_template")
        assert r["skill_name"] == "contract"
        assert r["reference_name"] == "clause_template"
        assert r["loaded"] is False


# ══════════════════════════════════════════════
# Subagent Tools
# ══════════════════════════════════════════════

from tools.builtin.subagent_tools import spawn_subagent, spawn_subagents, _subagent_runner


class TestSpawnSubagent:
    @pytest.mark.asyncio
    async def test_basic_call(self):
        mock_runner = AsyncMock()
        mock_runner.run_subagent.return_value = "任务完成：数据已验证"

        token = _subagent_runner.set(mock_runner)
        try:
            r = await spawn_subagent(task="检查数据", prompt="你是验证专家")
            assert r == "任务完成：数据已验证"
            mock_runner.run_subagent.assert_called_once_with(
                task="检查数据", prompt="你是验证专家", tools="", timeout_s=120
            )
        finally:
            _subagent_runner.reset(token)

    @pytest.mark.asyncio
    async def test_missing_runner(self):
        token = _subagent_runner.set(None)
        try:
            r = await spawn_subagent(task="test")
            assert "未初始化" in r
        finally:
            _subagent_runner.reset(token)


class TestSpawnSubagents:
    @pytest.mark.asyncio
    async def test_parallel_spawn(self):
        mock_runner = AsyncMock()
        mock_runner.run_subagent.side_effect = ["结果A", "结果B"]

        token = _subagent_runner.set(mock_runner)
        try:
            tasks_json = json.dumps([
                {"task": "任务A", "prompt": "角色A"},
                {"task": "任务B"},
            ])
            r = await spawn_subagents(tasks=tasks_json)
            assert "结果A" in r
            assert "结果B" in r
            assert mock_runner.run_subagent.call_count == 2
        finally:
            _subagent_runner.reset(token)

    @pytest.mark.asyncio
    async def test_empty_list(self):
        token = _subagent_runner.set(MagicMock())
        try:
            r = await spawn_subagents(tasks="[]")
            assert "非空" in r or "错误" in r
        finally:
            _subagent_runner.reset(token)

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        token = _subagent_runner.set(MagicMock())
        try:
            r = await spawn_subagents(tasks="not json")
            assert "错误" in r
        finally:
            _subagent_runner.reset(token)

    @pytest.mark.asyncio
    async def test_missing_runner(self):
        token = _subagent_runner.set(None)
        try:
            r = await spawn_subagents(tasks='[{"task":"x"}]')
            assert "未初始化" in r
        finally:
            _subagent_runner.reset(token)

    @pytest.mark.asyncio
    async def test_string_items(self):
        mock_runner = AsyncMock()
        mock_runner.run_subagent.return_value = "done"

        token = _subagent_runner.set(mock_runner)
        try:
            r = await spawn_subagents(tasks='["do task A"]')
            assert "done" in r
        finally:
            _subagent_runner.reset(token)
