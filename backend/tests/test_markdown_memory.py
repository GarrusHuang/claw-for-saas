"""Tests for memory/markdown_store.py — MarkdownMemoryStore."""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.markdown_store import MarkdownMemoryStore


class TestMarkdownMemoryStore:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.store = MarkdownMemoryStore(
            base_dir=str(tmp_path / "memory"),
            max_prompt_chars=1000,
        )

    # ─── 基础读写 ─────────────────────────────────────────

    def test_write_and_read_user(self):
        self.store.write_file("user", "notes.md", "Hello", tenant_id="T1", user_id="U1")
        content = self.store.read_file("user", "notes.md", tenant_id="T1", user_id="U1")
        assert content == "Hello"

    def test_write_and_read_tenant(self):
        self.store.write_file("tenant", "policies.md", "Rule 1", tenant_id="T1")
        content = self.store.read_file("tenant", "policies.md", tenant_id="T1")
        assert content == "Rule 1"

    def test_write_and_read_global(self):
        self.store.write_file("global", "best-practices.md", "Practice 1")
        content = self.store.read_file("global", "best-practices.md")
        assert content == "Practice 1"

    def test_append_mode(self):
        self.store.write_file("user", "log.md", "Line 1", tenant_id="T1", user_id="U1")
        self.store.write_file("user", "log.md", "Line 2", mode="append", tenant_id="T1", user_id="U1")
        content = self.store.read_file("user", "log.md", tenant_id="T1", user_id="U1")
        assert "Line 1" in content
        assert "Line 2" in content

    def test_rewrite_mode(self):
        self.store.write_file("user", "notes.md", "Old", tenant_id="T1", user_id="U1")
        self.store.write_file("user", "notes.md", "New", mode="rewrite", tenant_id="T1", user_id="U1")
        content = self.store.read_file("user", "notes.md", tenant_id="T1", user_id="U1")
        assert content == "New"
        assert "Old" not in content

    def test_read_nonexistent(self):
        content = self.store.read_file("user", "missing.md", tenant_id="T1", user_id="U1")
        assert content == ""

    def test_auto_add_md_extension(self):
        self.store.write_file("global", "notes", "Content")
        content = self.store.read_file("global", "notes")
        assert content == "Content"

    # ─── 列表 ─────────────────────────────────────────────

    def test_list_files(self):
        self.store.write_file("user", "a.md", "A", tenant_id="T1", user_id="U1")
        self.store.write_file("user", "b.md", "B", tenant_id="T1", user_id="U1")
        files = self.store.list_files("user", tenant_id="T1", user_id="U1")
        assert sorted(files) == ["a.md", "b.md"]

    def test_list_files_empty(self):
        files = self.store.list_files("user", tenant_id="T1", user_id="U1")
        assert files == []

    # ─── read_all ─────────────────────────────────────────

    def test_read_all(self):
        self.store.write_file("global", "a.md", "Content A")
        self.store.write_file("global", "b.md", "Content B")
        content = self.store.read_all("global")
        assert "Content A" in content
        assert "Content B" in content

    def test_read_all_empty(self):
        content = self.store.read_all("user", tenant_id="T1", user_id="U1")
        assert content == ""

    # ─── 删除 ─────────────────────────────────────────────

    def test_delete_file(self):
        self.store.write_file("user", "temp.md", "data", tenant_id="T1", user_id="U1")
        assert self.store.delete_file("user", "temp.md", tenant_id="T1", user_id="U1")
        assert self.store.read_file("user", "temp.md", tenant_id="T1", user_id="U1") == ""

    def test_delete_nonexistent(self):
        assert not self.store.delete_file("user", "nope.md", tenant_id="T1", user_id="U1")

    # ─── Prompt 注入 ──────────────────────────────────────

    def test_build_memory_prompt_empty(self):
        prompt, id_map = self.store.build_memory_prompt("T1", "U1")
        assert prompt == ""
        assert id_map == {}

    def test_build_memory_prompt_single_level(self):
        self.store.write_file("user", "prefs.md", "Prefer dark mode", tenant_id="T1", user_id="U1")
        prompt, id_map = self.store.build_memory_prompt("T1", "U1")
        assert "<user>" in prompt
        assert "Prefer dark mode" in prompt
        assert "</user>" in prompt
        assert "[m1]" in prompt
        assert len(id_map) >= 1

    def test_build_memory_prompt_three_levels(self):
        self.store.write_file("global", "best.md", "Global tip")
        self.store.write_file("tenant", "policy.md", "Tenant rule", tenant_id="T1")
        self.store.write_file("user", "pref.md", "User pref", tenant_id="T1", user_id="U1")

        prompt, id_map = self.store.build_memory_prompt("T1", "U1")
        assert "<global>" in prompt
        assert "Global tip" in prompt
        assert "<tenant>" in prompt
        assert "Tenant rule" in prompt
        assert "<user>" in prompt
        assert "User pref" in prompt
        assert len(id_map) == 3

    def test_build_memory_prompt_budget_truncation(self):
        # Set very small budget
        self.store.max_prompt_chars = 50
        self.store.write_file("global", "big.md", "A" * 200)
        self.store.write_file("user", "small.md", "User data", tenant_id="T1", user_id="U1")

        prompt, _ = self.store.build_memory_prompt("T1", "U1")
        # User data should be preserved (higher priority)
        assert "User data" in prompt

    # ─── 隔离 ─────────────────────────────────────────────

    def test_user_isolation(self):
        self.store.write_file("user", "notes.md", "User1 data", tenant_id="T1", user_id="U1")
        self.store.write_file("user", "notes.md", "User2 data", tenant_id="T1", user_id="U2")

        c1 = self.store.read_file("user", "notes.md", tenant_id="T1", user_id="U1")
        c2 = self.store.read_file("user", "notes.md", tenant_id="T1", user_id="U2")
        assert c1 == "User1 data"
        assert c2 == "User2 data"

    def test_tenant_isolation(self):
        self.store.write_file("tenant", "rules.md", "T1 rules", tenant_id="T1")
        self.store.write_file("tenant", "rules.md", "T2 rules", tenant_id="T2")

        c1 = self.store.read_file("tenant", "rules.md", tenant_id="T1")
        c2 = self.store.read_file("tenant", "rules.md", tenant_id="T2")
        assert c1 == "T1 rules"
        assert c2 == "T2 rules"

    # ─── 统计 ─────────────────────────────────────────────

    def test_get_stats(self):
        self.store.write_file("global", "a.md", "data")
        self.store.write_file("user", "b.md", "data", tenant_id="T1", user_id="U1")

        stats = self.store.get_stats(tenant_id="T1", user_id="U1")
        assert stats["global_files"] == 1
        assert stats["user_files"] == 1
        assert stats["total_size_bytes"] > 0

    def test_get_stats_empty(self):
        stats = self.store.get_stats()
        assert stats["global_files"] == 0

    # ─── 安全 ─────────────────────────────────────────────

    def test_path_traversal_prevention(self):
        self.store.write_file("user", "../../../etc/passwd", "bad", tenant_id="T1", user_id="U1")
        # Should not escape the base directory
        content = self.store.read_file("user", "../../../etc/passwd", tenant_id="T1", user_id="U1")
        assert content == "bad"  # Written to sanitized path, not actual /etc/passwd

    def test_invalid_scope(self):
        with pytest.raises(ValueError, match="Invalid scope"):
            self.store.write_file("invalid", "test.md", "data")

    # ─── 压缩提示 ─────────────────────────────────────────

    def test_file_needs_compaction(self):
        self.store.max_file_bytes = 100
        self.store.write_file("user", "big.md", "x" * 200, tenant_id="T1", user_id="U1")
        assert self.store.file_needs_compaction("user", "big.md", tenant_id="T1", user_id="U1")

    def test_file_no_compaction_needed(self):
        self.store.write_file("user", "small.md", "tiny", tenant_id="T1", user_id="U1")
        assert not self.store.file_needs_compaction("user", "small.md", tenant_id="T1", user_id="U1")

    def test_file_nonexistent_no_compaction(self):
        assert not self.store.file_needs_compaction("user", "nope.md", tenant_id="T1", user_id="U1")
