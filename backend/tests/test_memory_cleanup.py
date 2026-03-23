"""
Phase 5.3 — 30 天过期清理测试。
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from memory.markdown_store import MarkdownMemoryStore


@pytest.fixture
def store(tmp_path):
    return MarkdownMemoryStore(base_dir=str(tmp_path), max_prompt_chars=8000)


def _set_meta_entry(store, scope, entry_key, usage_count, days_ago, **kwargs):
    """辅助: 在 _meta.json 中写入一条带指定时间戳的条目。"""
    meta = store._load_meta(scope, **kwargs)
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    meta.setdefault("entries", {})[entry_key] = {
        "usage_count": usage_count,
        "last_used": ts,
        "created_at": ts,
    }
    store._save_meta(scope, meta, **kwargs)


class TestCleanupExpiredEntries:
    """cleanup_expired_entries 逻辑测试。"""

    def test_old_unused_is_cleaned(self, store):
        """30 天前 + usage_count=0 → 被清理。"""
        store.write_file("user", "notes.md", "## OldEntry\nOld content\n\n## Keep\nKeep this",
                         tenant_id="T1", user_id="U1")
        _set_meta_entry(store, "user", "notes.md::OldEntry", usage_count=0, days_ago=35,
                        tenant_id="T1", user_id="U1")
        _set_meta_entry(store, "user", "notes.md::Keep", usage_count=0, days_ago=5,
                        tenant_id="T1", user_id="U1")

        cleaned = store.cleanup_expired_entries(
            "user", tenant_id="T1", user_id="U1", retention_days=30,
        )
        assert cleaned == 1

        # OldEntry 从 _meta.json 移除
        meta = store._load_meta("user", tenant_id="T1", user_id="U1")
        assert "notes.md::OldEntry" not in meta["entries"]
        assert "notes.md::Keep" in meta["entries"]

        # OldEntry 从 .md 文件中删除
        content = store.read_file("user", "notes.md", tenant_id="T1", user_id="U1")
        assert "OldEntry" not in content
        assert "Keep this" in content

    def test_old_but_used_is_preserved(self, store):
        """30 天前 + usage_count>0 → 不清理。"""
        store.write_file("user", "notes.md", "## UsedEntry\nImportant",
                         tenant_id="T1", user_id="U1")
        _set_meta_entry(store, "user", "notes.md::UsedEntry", usage_count=3, days_ago=60,
                        tenant_id="T1", user_id="U1")

        cleaned = store.cleanup_expired_entries(
            "user", tenant_id="T1", user_id="U1", retention_days=30,
        )
        assert cleaned == 0

        content = store.read_file("user", "notes.md", tenant_id="T1", user_id="U1")
        assert "Important" in content

    def test_recent_unused_is_preserved(self, store):
        """5 天前 + usage_count=0 → 不清理。"""
        store.write_file("user", "notes.md", "## Recent\nFresh content",
                         tenant_id="T1", user_id="U1")
        _set_meta_entry(store, "user", "notes.md::Recent", usage_count=0, days_ago=5,
                        tenant_id="T1", user_id="U1")

        cleaned = store.cleanup_expired_entries(
            "user", tenant_id="T1", user_id="U1", retention_days=30,
        )
        assert cleaned == 0

    def test_cleanup_deletes_empty_file(self, store):
        """清理完所有段落后，文件应被删除。"""
        store.write_file("user", "temp.md", "## OnlyEntry\nWill be cleaned",
                         tenant_id="T1", user_id="U1")
        _set_meta_entry(store, "user", "temp.md::OnlyEntry", usage_count=0, days_ago=40,
                        tenant_id="T1", user_id="U1")

        cleaned = store.cleanup_expired_entries(
            "user", tenant_id="T1", user_id="U1", retention_days=30,
        )
        assert cleaned == 1
        assert "temp.md" not in store.list_files("user", tenant_id="T1", user_id="U1")

    def test_retention_days_zero_skips(self, store):
        """retention_days=0 → 不清理。"""
        store.write_file("user", "notes.md", "## Old\nContent",
                         tenant_id="T1", user_id="U1")
        _set_meta_entry(store, "user", "notes.md::Old", usage_count=0, days_ago=999,
                        tenant_id="T1", user_id="U1")

        cleaned = store.cleanup_expired_entries(
            "user", tenant_id="T1", user_id="U1", retention_days=0,
        )
        assert cleaned == 0

    def test_no_meta_entries(self, store):
        """没有 _meta.json 条目 → 返回 0。"""
        cleaned = store.cleanup_expired_entries(
            "user", tenant_id="T1", user_id="U1", retention_days=30,
        )
        assert cleaned == 0


class TestScanAndCleanupExpired:
    """scan_and_cleanup_expired 扫描多用户。"""

    def test_scans_multiple_users(self, store):
        for uid in ("U1", "U2"):
            store.write_file("user", "notes.md", "## Old\nExpired", tenant_id="T1", user_id=uid)
            _set_meta_entry(store, "user", "notes.md::Old", usage_count=0, days_ago=40,
                            tenant_id="T1", user_id=uid)

        total = store.scan_and_cleanup_expired(retention_days=30, max_per_run=10)
        assert total == 2

    def test_max_per_run_limit(self, store):
        for i in range(5):
            uid = f"U{i}"
            store.write_file("user", "notes.md", "## Old\nExpired", tenant_id="T1", user_id=uid)
            _set_meta_entry(store, "user", "notes.md::Old", usage_count=0, days_ago=40,
                            tenant_id="T1", user_id=uid)

        total = store.scan_and_cleanup_expired(retention_days=30, max_per_run=2)
        # 最多处理 2 个用户
        assert total <= 2
