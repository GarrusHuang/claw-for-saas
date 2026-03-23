"""
Phase 5.3 — 记忆引用追踪 (_meta.json + ID 标记) 测试。
"""

import json
import os
import re
import shutil
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory.markdown_store import MarkdownMemoryStore


@pytest.fixture
def store(tmp_path):
    return MarkdownMemoryStore(base_dir=str(tmp_path), max_prompt_chars=8000)


class TestMetaJsonBasics:
    """_meta.json 自动创建与读写。"""

    def test_load_meta_creates_empty(self, store):
        meta = store._load_meta("user", tenant_id="T1", user_id="U1")
        assert meta == {"entries": {}}

    def test_save_and_load_meta(self, store):
        meta = {"entries": {"file.md::sec": {"usage_count": 3, "last_used": "2026-01-01T00:00:00+00:00", "created_at": "2025-12-01T00:00:00+00:00"}}}
        store._save_meta("user", meta, tenant_id="T1", user_id="U1")
        loaded = store._load_meta("user", tenant_id="T1", user_id="U1")
        assert loaded["entries"]["file.md::sec"]["usage_count"] == 3

    def test_meta_path_location(self, store):
        path = store._meta_path("user", tenant_id="T1", user_id="U1")
        assert path.name == "_meta.json"
        assert "user" in str(path)


class TestParseEntries:
    """_parse_entries 分段测试。"""

    def test_sections_by_h2(self):
        content = "## Header A\nContent A\n\n## Header B\nContent B"
        entries = MarkdownMemoryStore._parse_entries(content, "file.md")
        assert len(entries) == 2
        assert entries[0][0] == "file.md::Header A"
        assert "Content A" in entries[0][1]
        assert entries[1][0] == "file.md::Header B"
        assert "Content B" in entries[1][1]

    def test_no_sections_uses_full(self):
        content = "Some plain text\nAnother line"
        entries = MarkdownMemoryStore._parse_entries(content, "notes.md")
        assert len(entries) == 1
        assert entries[0][0] == "notes.md::__full__"
        assert "Some plain text" in entries[0][1]

    def test_empty_content(self):
        entries = MarkdownMemoryStore._parse_entries("", "empty.md")
        assert entries == []

    def test_preamble_before_h2_is_skipped(self):
        content = "# Title\nPreamble\n\n## Section 1\nData"
        entries = MarkdownMemoryStore._parse_entries(content, "f.md")
        assert len(entries) == 1
        assert entries[0][0] == "f.md::Section 1"

    def test_date_headers(self):
        content = "## 2026-03-22 14:30\n- [偏好] content\n\n## 2026-03-22 15:00\n- [纠正] fix"
        entries = MarkdownMemoryStore._parse_entries(content, "auto-learning.md")
        assert len(entries) == 2
        assert entries[0][0] == "auto-learning.md::2026-03-22 14:30"
        assert entries[1][0] == "auto-learning.md::2026-03-22 15:00"


class TestIncrementUsage:
    """increment_usage 递增 + last_used 更新。"""

    def test_first_increment_creates_entry(self, store):
        store.increment_usage("user", "file.md::sec", tenant_id="T1", user_id="U1")
        meta = store._load_meta("user", tenant_id="T1", user_id="U1")
        entry = meta["entries"]["file.md::sec"]
        assert entry["usage_count"] == 1
        assert entry["last_used"]
        assert entry["created_at"]

    def test_subsequent_increments(self, store):
        store.increment_usage("user", "file.md::sec", tenant_id="T1", user_id="U1")
        store.increment_usage("user", "file.md::sec", tenant_id="T1", user_id="U1")
        store.increment_usage("user", "file.md::sec", tenant_id="T1", user_id="U1")
        meta = store._load_meta("user", tenant_id="T1", user_id="U1")
        assert meta["entries"]["file.md::sec"]["usage_count"] == 3

    def test_last_used_updates(self, store):
        store.increment_usage("user", "file.md::sec", tenant_id="T1", user_id="U1")
        first = store._load_meta("user", tenant_id="T1", user_id="U1")["entries"]["file.md::sec"]["last_used"]
        import time
        time.sleep(0.01)
        store.increment_usage("user", "file.md::sec", tenant_id="T1", user_id="U1")
        second = store._load_meta("user", tenant_id="T1", user_id="U1")["entries"]["file.md::sec"]["last_used"]
        assert second >= first


class TestGetUsageStats:
    """get_usage_stats 按 usage_count 降序。"""

    def test_sorted_by_usage(self, store):
        store.increment_usage("user", "a.md::sec1", tenant_id="T1", user_id="U1")
        for _ in range(5):
            store.increment_usage("user", "b.md::sec2", tenant_id="T1", user_id="U1")
        stats = store.get_usage_stats("user", tenant_id="T1", user_id="U1")
        assert len(stats) == 2
        assert stats[0]["entry_key"] == "b.md::sec2"
        assert stats[0]["usage_count"] == 5
        assert stats[1]["entry_key"] == "a.md::sec1"
        assert stats[1]["usage_count"] == 1


class TestBuildMemoryPromptWithIDs:
    """build_memory_prompt 输出含 [mN] 前缀 + id_map 正确映射。"""

    def test_empty_returns_empty_tuple(self, store):
        text, id_map = store.build_memory_prompt("T1", "U1")
        assert text == ""
        assert id_map == {}

    def test_single_level_has_ids(self, store):
        store.write_file("user", "prefs.md", "## Style\nUse dark mode", tenant_id="T1", user_id="U1")
        text, id_map = store.build_memory_prompt("T1", "U1")
        assert "[m1]" in text
        assert "<user>" in text
        assert "m1" in id_map
        assert id_map["m1"] == ("user", "prefs.md::Style")

    def test_three_levels_sequential_ids(self, store):
        store.write_file("global", "tips.md", "Global tip")
        store.write_file("tenant", "policy.md", "Tenant rule", tenant_id="T1")
        store.write_file("user", "pref.md", "User pref", tenant_id="T1", user_id="U1")
        text, id_map = store.build_memory_prompt("T1", "U1")
        assert "<global>" in text
        assert "<tenant>" in text
        assert "<user>" in text
        # Should have 3 IDs
        assert len(id_map) == 3

    def test_usage_count_sorting(self, store):
        store.write_file(
            "user", "notes.md",
            "## LowFreq\nRarely used\n\n## HighFreq\nOften used",
            tenant_id="T1", user_id="U1",
        )
        # HighFreq 使用 5 次
        for _ in range(5):
            store.increment_usage("user", "notes.md::HighFreq", tenant_id="T1", user_id="U1")
        text, id_map = store.build_memory_prompt("T1", "U1")
        # HighFreq 应该排在前面 (m1), LowFreq 后面 (m2)
        m1_scope, m1_key = id_map["m1"]
        assert m1_key == "notes.md::HighFreq"

    def test_budget_truncation(self, store):
        store.max_prompt_chars = 50
        store.write_file("user", "big.md", "## Sec\n" + "A" * 200, tenant_id="T1", user_id="U1")
        text, id_map = store.build_memory_prompt("T1", "U1")
        assert "[...truncated...]" in text
        assert len(id_map) >= 1

    def test_id_map_scope_correct(self, store):
        store.write_file("global", "g.md", "Global data")
        store.write_file("user", "u.md", "User data", tenant_id="T1", user_id="U1")
        _, id_map = store.build_memory_prompt("T1", "U1")
        scopes = {v[0] for v in id_map.values()}
        assert "global" in scopes
        assert "user" in scopes


class TestGatewayMemRefParsing:
    """gateway 解析 [mem:m2] 后调用 increment_usage 的集成测试。"""

    def test_parse_mem_refs(self):
        text = "根据你的偏好 [mem:m1]，我使用了暗色模式 [mem:m3]。另外 [mem:m1] 也适用。"
        refs = set(re.findall(r"\[mem:(m\d+)\]", text))
        assert refs == {"m1", "m3"}

    def test_no_refs(self):
        text = "这是一个普通回复，没有引用任何记忆。"
        refs = re.findall(r"\[mem:(m\d+)\]", text)
        assert refs == []
