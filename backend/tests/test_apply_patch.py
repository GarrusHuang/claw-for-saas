"""
Tests for apply_patch tool — parser + applier + tool handler.
"""

import os
import sys
import textwrap
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.builtin.apply_patch import (
    parse_patch,
    apply_patch_to_filesystem,
    AddFile,
    DeleteFile,
    UpdateFile,
    UpdateChunk,
    PatchParseError,
    PatchApplyError,
    _seek_sequence,
    _apply_update,
)


# ── Parser Tests ──


class TestParsePatch:
    def test_add_file(self):
        patch = textwrap.dedent("""\
            *** Begin Patch
            *** Add File: hello.txt
            +Hello
            +World
            *** End Patch
        """)
        hunks = parse_patch(patch)
        assert len(hunks) == 1
        h = hunks[0]
        assert isinstance(h, AddFile)
        assert h.path == "hello.txt"
        assert h.contents == "Hello\nWorld\n"

    def test_delete_file(self):
        patch = textwrap.dedent("""\
            *** Begin Patch
            *** Delete File: old.txt
            *** End Patch
        """)
        hunks = parse_patch(patch)
        assert len(hunks) == 1
        assert isinstance(hunks[0], DeleteFile)
        assert hunks[0].path == "old.txt"

    def test_update_file_simple(self):
        patch = textwrap.dedent("""\
            *** Begin Patch
            *** Update File: app.py
            @@
             def greet():
            -    print("Hi")
            +    print("Hello")
            *** End Patch
        """)
        hunks = parse_patch(patch)
        assert len(hunks) == 1
        h = hunks[0]
        assert isinstance(h, UpdateFile)
        assert h.path == "app.py"
        assert len(h.chunks) == 1
        chunk = h.chunks[0]
        assert chunk.old_lines == ['def greet():', '    print("Hi")']
        assert chunk.new_lines == ['def greet():', '    print("Hello")']

    def test_update_file_with_context(self):
        patch = textwrap.dedent("""\
            *** Begin Patch
            *** Update File: app.py
            @@ class Foo
             old_line
            -remove
            +add
            *** End Patch
        """)
        hunks = parse_patch(patch)
        h = hunks[0]
        assert isinstance(h, UpdateFile)
        assert h.chunks[0].context_hint == "class Foo"

    def test_update_file_multiple_chunks(self):
        patch = textwrap.dedent("""\
            *** Begin Patch
            *** Update File: multi.txt
            @@
            -line2
            +changed2
            @@
            -line4
            +changed4
            *** End Patch
        """)
        hunks = parse_patch(patch)
        h = hunks[0]
        assert isinstance(h, UpdateFile)
        assert len(h.chunks) == 2

    def test_update_file_with_move(self):
        patch = textwrap.dedent("""\
            *** Begin Patch
            *** Update File: old.py
            *** Move to: new.py
            @@
            -old
            +new
            *** End Patch
        """)
        hunks = parse_patch(patch)
        h = hunks[0]
        assert isinstance(h, UpdateFile)
        assert h.move_to == "new.py"

    def test_multiple_operations(self):
        patch = textwrap.dedent("""\
            *** Begin Patch
            *** Add File: new.txt
            +content
            *** Update File: edit.txt
            @@
            -old
            +new
            *** Delete File: remove.txt
            *** End Patch
        """)
        hunks = parse_patch(patch)
        assert len(hunks) == 3
        assert isinstance(hunks[0], AddFile)
        assert isinstance(hunks[1], UpdateFile)
        assert isinstance(hunks[2], DeleteFile)

    def test_end_of_file_marker(self):
        patch = textwrap.dedent("""\
            *** Begin Patch
            *** Update File: tail.txt
            @@
             last
            -old_end
            +new_end
            *** End of File
            *** End Patch
        """)
        hunks = parse_patch(patch)
        h = hunks[0]
        assert isinstance(h, UpdateFile)
        assert h.chunks[0].is_eof is True

    def test_pure_addition(self):
        patch = textwrap.dedent("""\
            *** Begin Patch
            *** Update File: input.txt
            @@
            +added line 1
            +added line 2
            *** End Patch
        """)
        hunks = parse_patch(patch)
        h = hunks[0]
        assert isinstance(h, UpdateFile)
        chunk = h.chunks[0]
        assert chunk.old_lines == []
        assert chunk.new_lines == ["added line 1", "added line 2"]

    def test_invalid_no_begin(self):
        with pytest.raises(PatchParseError, match="Begin Patch"):
            parse_patch("bad\n*** End Patch")

    def test_invalid_no_end(self):
        with pytest.raises(PatchParseError, match="End Patch"):
            parse_patch("*** Begin Patch\nbad")

    def test_invalid_empty_update(self):
        patch = textwrap.dedent("""\
            *** Begin Patch
            *** Update File: empty.py
            *** End Patch
        """)
        with pytest.raises(PatchParseError, match="no chunks"):
            parse_patch(patch)


# ── Seek Sequence Tests ──


class TestSeekSequence:
    def test_exact_match(self):
        lines = ["foo", "bar", "baz"]
        assert _seek_sequence(lines, ["bar", "baz"], 0, False) == 1

    def test_trim_trailing(self):
        lines = ["foo   ", "bar\t"]
        assert _seek_sequence(lines, ["foo", "bar"], 0, False) == 0

    def test_trim_both_sides(self):
        lines = ["  foo  ", "  bar  "]
        assert _seek_sequence(lines, ["foo", "bar"], 0, False) == 0

    def test_not_found(self):
        lines = ["abc", "def"]
        assert _seek_sequence(lines, ["xyz"], 0, False) is None

    def test_pattern_longer_than_input(self):
        lines = ["one"]
        assert _seek_sequence(lines, ["a", "b", "c"], 0, False) is None

    def test_eof_mode(self):
        lines = ["a", "b", "c", "b", "c"]
        # eof=True should find the last occurrence
        assert _seek_sequence(lines, ["b", "c"], 0, True) == 3

    def test_empty_pattern(self):
        assert _seek_sequence(["a", "b"], [], 0, False) == 0

    def test_start_offset(self):
        lines = ["a", "b", "a", "b"]
        assert _seek_sequence(lines, ["a", "b"], 2, False) == 2


# ── Apply Update Tests ──


class TestApplyUpdate:
    def test_simple_replacement(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("foo\nbar\nbaz\n")
        chunks = [UpdateChunk(old_lines=["bar"], new_lines=["BAR"])]
        result = _apply_update(str(f), chunks)
        assert result == "foo\nBAR\nbaz\n"

    def test_multiple_chunks(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("a\nb\nc\nd\n")
        chunks = [
            UpdateChunk(old_lines=["b"], new_lines=["B"]),
            UpdateChunk(old_lines=["d"], new_lines=["D"]),
        ]
        result = _apply_update(str(f), chunks)
        assert result == "a\nB\nc\nD\n"

    def test_pure_addition(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\n")
        chunks = [UpdateChunk(old_lines=[], new_lines=["line3"])]
        result = _apply_update(str(f), chunks)
        assert result == "line1\nline2\nline3\n"

    def test_deletion(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("a\nb\nc\n")
        chunks = [UpdateChunk(old_lines=["b"], new_lines=[])]
        result = _apply_update(str(f), chunks)
        assert result == "a\nc\n"

    def test_context_hint(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("class Foo:\n    def bar(self):\n        pass\n\nclass Baz:\n    def bar(self):\n        pass\n")
        chunks = [UpdateChunk(
            context_hint="class Baz:",
            old_lines=["        pass"],
            new_lines=["        return 42"],
        )]
        result = _apply_update(str(f), chunks)
        assert "class Foo:\n    def bar(self):\n        pass\n" in result
        assert "class Baz:\n    def bar(self):\n        return 42\n" in result

    def test_not_found_raises(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("abc\ndef\n")
        chunks = [UpdateChunk(old_lines=["xyz"], new_lines=["new"])]
        with pytest.raises(PatchApplyError, match="Could not find"):
            _apply_update(str(f), chunks)

    def test_eof_marker(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("first\nsecond\n")
        chunks = [UpdateChunk(
            old_lines=["second"],
            new_lines=["second updated"],
            is_eof=True,
        )]
        result = _apply_update(str(f), chunks)
        assert result == "first\nsecond updated\n"


# ── Filesystem Apply Tests ──


class TestApplyPatchToFilesystem:
    def test_add_file(self, tmp_path):
        hunks = [AddFile(path="new.txt", contents="hello\n")]
        result = apply_patch_to_filesystem(hunks, str(tmp_path))
        assert result["added"] == ["new.txt"]
        assert (tmp_path / "new.txt").read_text() == "hello\n"

    def test_add_file_with_dirs(self, tmp_path):
        hunks = [AddFile(path="a/b/new.txt", contents="deep\n")]
        result = apply_patch_to_filesystem(hunks, str(tmp_path))
        assert (tmp_path / "a" / "b" / "new.txt").read_text() == "deep\n"

    def test_delete_file(self, tmp_path):
        (tmp_path / "del.txt").write_text("bye")
        hunks = [DeleteFile(path="del.txt")]
        result = apply_patch_to_filesystem(hunks, str(tmp_path))
        assert result["deleted"] == ["del.txt"]
        assert not (tmp_path / "del.txt").exists()

    def test_delete_missing_file_raises(self, tmp_path):
        hunks = [DeleteFile(path="nope.txt")]
        with pytest.raises(PatchApplyError, match="not found"):
            apply_patch_to_filesystem(hunks, str(tmp_path))

    def test_update_file(self, tmp_path):
        (tmp_path / "edit.txt").write_text("foo\nbar\nbaz\n")
        hunks = [UpdateFile(
            path="edit.txt",
            chunks=[UpdateChunk(old_lines=["bar"], new_lines=["BAR"])],
        )]
        result = apply_patch_to_filesystem(hunks, str(tmp_path))
        assert result["modified"] == ["edit.txt"]
        assert (tmp_path / "edit.txt").read_text() == "foo\nBAR\nbaz\n"

    def test_update_with_move(self, tmp_path):
        (tmp_path / "src.txt").write_text("line\n")
        hunks = [UpdateFile(
            path="src.txt",
            move_to="dst.txt",
            chunks=[UpdateChunk(old_lines=["line"], new_lines=["LINE"])],
        )]
        result = apply_patch_to_filesystem(hunks, str(tmp_path))
        assert result["modified"] == ["dst.txt"]
        assert not (tmp_path / "src.txt").exists()
        assert (tmp_path / "dst.txt").read_text() == "LINE\n"

    def test_multi_operation(self, tmp_path):
        (tmp_path / "edit.txt").write_text("old\n")
        (tmp_path / "remove.txt").write_text("bye\n")
        hunks = [
            AddFile(path="new.txt", contents="hello\n"),
            UpdateFile(path="edit.txt", chunks=[UpdateChunk(old_lines=["old"], new_lines=["new"])]),
            DeleteFile(path="remove.txt"),
        ]
        result = apply_patch_to_filesystem(hunks, str(tmp_path))
        assert result["added"] == ["new.txt"]
        assert result["modified"] == ["edit.txt"]
        assert result["deleted"] == ["remove.txt"]

    def test_interleaved_changes(self, tmp_path):
        """Multiple chunks editing different parts of one file."""
        (tmp_path / "code.py").write_text("a\nb\nc\nd\ne\nf\n")
        hunks = [UpdateFile(
            path="code.py",
            chunks=[
                UpdateChunk(
                    old_lines=["a", "b"],
                    new_lines=["a", "B"],
                ),
                UpdateChunk(
                    old_lines=["d", "e"],
                    new_lines=["d", "E"],
                ),
            ],
        )]
        apply_patch_to_filesystem(hunks, str(tmp_path))
        assert (tmp_path / "code.py").read_text() == "a\nB\nc\nd\nE\nf\n"


# ── Tool Handler Tests ──


class TestApplyPatchTool:
    def test_tool_success(self, tmp_path):
        (tmp_path / "test.txt").write_text("hello\nworld\n")
        patch_text = textwrap.dedent("""\
            *** Begin Patch
            *** Update File: test.txt
            @@
            -world
            +WORLD
            *** End Patch
        """)
        with patch("tools.builtin.apply_patch.current_sandbox") as mock_sandbox_var, \
             patch("tools.builtin.apply_patch.current_event_bus") as mock_bus_var, \
             patch("tools.builtin.apply_patch.current_session_id") as mock_sid:
            mock_sandbox_var.get.return_value = None
            mock_bus_var.get.return_value = None
            mock_sid.get.return_value = ""

            with patch.dict(os.environ, {"CODE_ALLOWED_PATHS": str(tmp_path)}):
                from tools.builtin.apply_patch import apply_patch as apply_patch_tool
                result = apply_patch_tool(patch=patch_text)

        assert result["success"] is True
        assert "test.txt" in result["modified"]
        assert (tmp_path / "test.txt").read_text() == "hello\nWORLD\n"

    def test_tool_parse_error(self):
        with patch("tools.builtin.apply_patch.current_sandbox") as mock_sandbox_var:
            mock_sandbox_var.get.return_value = None
            from tools.builtin.apply_patch import apply_patch as apply_patch_tool
            result = apply_patch_tool(patch="bad input")
        assert "error" in result
        assert "解析失败" in result["error"]

    def test_tool_absolute_path_rejected(self, tmp_path):
        patch_text = textwrap.dedent("""\
            *** Begin Patch
            *** Add File: /etc/passwd
            +hacked
            *** End Patch
        """)
        with patch("tools.builtin.apply_patch.current_sandbox") as mock_sandbox_var:
            mock_sandbox_var.get.return_value = None
            with patch.dict(os.environ, {"CODE_ALLOWED_PATHS": str(tmp_path)}):
                from tools.builtin.apply_patch import apply_patch as apply_patch_tool
                result = apply_patch_tool(patch=patch_text)
        assert "error" in result
        assert "Absolute" in result["error"]

    def test_tool_path_traversal_rejected(self, tmp_path):
        patch_text = textwrap.dedent("""\
            *** Begin Patch
            *** Add File: ../../../etc/evil
            +hacked
            *** End Patch
        """)
        with patch("tools.builtin.apply_patch.current_sandbox") as mock_sandbox_var:
            mock_sandbox_var.get.return_value = None
            with patch.dict(os.environ, {"CODE_ALLOWED_PATHS": str(tmp_path)}):
                from tools.builtin.apply_patch import apply_patch as apply_patch_tool
                result = apply_patch_tool(patch=patch_text)
        assert "error" in result
        assert "escapes" in result["error"]
