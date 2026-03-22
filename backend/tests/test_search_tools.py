"""Tests for tools/builtin/search_tools.py — grep_files / list_dir."""
import json
import os
import sys
import time
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.builtin.search_tools import grep_files, list_dir


def _mock_context(workspace: str):
    """Create a mock RequestContext pointing to a workspace directory."""
    ctx = MagicMock()
    ctx.sandbox = MagicMock()
    ctx.sandbox.get_workspace.return_value = workspace

    def validate_path(path, ws):
        resolved = os.path.realpath(path)
        ws_real = os.path.realpath(ws)
        if resolved == ws_real or resolved.startswith(ws_real + os.sep):
            return resolved
        raise PermissionError(f"路径 {path} 不在工作空间内")

    ctx.sandbox.validate_path.side_effect = validate_path
    ctx.tenant_id = "T001"
    ctx.user_id = "U001"
    ctx.session_id = "S001"
    return ctx


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace with sample files."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    # Create sample files
    (ws / "hello.py").write_text("def hello():\n    print('hello world')\n    return 42\n")
    (ws / "utils.py").write_text("import os\nimport sys\n\ndef helper():\n    pass\n")
    (ws / "data.txt").write_text("line one\nline two\nline three\n")

    sub = ws / "sub"
    sub.mkdir()
    (sub / "nested.py").write_text("# nested file\nclass Foo:\n    bar = 1\n")

    return str(ws)


class TestGrepFiles:
    def test_basic_match(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = grep_files(pattern="hello")
        assert result["match_count"] > 0
        assert any(m["file"] == "hello.py" for m in result["matches"])

    def test_regex_pattern(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = grep_files(pattern=r"def \w+\(\)")
        assert result["match_count"] >= 2  # hello() and helper()

    def test_invalid_regex(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = grep_files(pattern="[invalid")
        assert "error" in result

    def test_include_filter(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = grep_files(pattern="line", include="*.txt")
        assert result["match_count"] > 0
        assert all(m["file"].endswith(".txt") for m in result["matches"])

    def test_max_results(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = grep_files(pattern=".", max_results=2)
        assert result["match_count"] == 2
        assert result["truncated"] is True

    def test_context_lines(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = grep_files(pattern="print", context_lines=1)
        assert result["match_count"] > 0
        match = result["matches"][0]
        assert "context" in match
        assert len(match["context"]) >= 2  # at least the match line + context

    def test_path_traversal_blocked(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = grep_files(pattern=".", path="../../../etc")
        assert "error" in result

    def test_binary_file_skipped(self, workspace):
        # Create a binary file
        binary_path = os.path.join(workspace, "binary.bin")
        with open(binary_path, "wb") as f:
            f.write(b"\x00\x01\x02hello\x00\xff")

        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = grep_files(pattern="hello")
        # binary.bin should be skipped — match should be from hello.py only
        assert all("binary.bin" not in m["file"] for m in result["matches"])

    def test_no_matches(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = grep_files(pattern="nonexistent_xyz_string")
        assert result["match_count"] == 0
        assert result["matches"] == []
        assert result["truncated"] is False

    def test_nested_file_found(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = grep_files(pattern="class Foo")
        assert result["match_count"] == 1
        assert "nested.py" in result["matches"][0]["file"]


class TestListDir:
    def test_basic_listing(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = list_dir()
        assert result["total"] > 0
        paths = [e["path"] for e in result["entries"]]
        assert "hello.py" in paths
        assert "sub" in paths

    def test_depth_limit(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result_d1 = list_dir(depth=1)
            result_d2 = list_dir(depth=2)
        # depth=1 should not include sub/nested.py
        paths_d1 = [e["path"] for e in result_d1["entries"]]
        assert not any("nested.py" in p for p in paths_d1)
        # depth=2 should include sub/nested.py
        paths_d2 = [e["path"] for e in result_d2["entries"]]
        assert any("nested.py" in p for p in paths_d2)

    def test_include_filter(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = list_dir(include="*.py")
        files = [e for e in result["entries"] if e["type"] == "file"]
        assert all(e["path"].endswith(".py") for e in files)

    def test_pagination(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = list_dir(limit=2, offset=0)
        assert len(result["entries"]) == 2
        assert result["has_more"] is True

    def test_path_traversal_blocked(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = list_dir(path="../../../etc")
        assert "error" in result

    def test_empty_directory(self, workspace):
        empty = os.path.join(workspace, "empty")
        os.makedirs(empty)
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = list_dir(path="empty")
        assert result["total"] == 0
        assert result["entries"] == []

    def test_metadata_present(self, workspace):
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = list_dir()
        for entry in result["entries"]:
            assert "path" in entry
            assert "type" in entry
            assert "mtime" in entry
            if entry["type"] == "file":
                assert "size" in entry
                assert entry["size"] > 0

    def test_directories_first(self, workspace):
        """Directories should appear before files at each level."""
        with patch("tools.builtin.search_tools.get_request_context", return_value=_mock_context(workspace)):
            result = list_dir(depth=1)
        types = [e["type"] for e in result["entries"]]
        # All directories should come before files (at depth=1 level)
        dir_indices = [i for i, t in enumerate(types) if t == "directory"]
        file_indices = [i for i, t in enumerate(types) if t == "file"]
        if dir_indices and file_indices:
            assert max(dir_indices) < min(file_indices)
