"""Tests for tools/builtin/memory_tools.py — save_memory & recall_memory (A8)."""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.context import current_memory_store, current_tenant_id, current_user_id, current_event_bus
from core.event_bus import EventBus
from memory.markdown_store import MarkdownMemoryStore
from tools.builtin.memory_tools import save_memory, recall_memory, memory_capability_registry


class TestSaveMemory:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.store = MarkdownMemoryStore(base_dir=str(tmp_path / "memory"))
        self.bus = EventBus(trace_id="test")
        self.tokens = [
            current_memory_store.set(self.store),
            current_tenant_id.set("T1"),
            current_user_id.set("U1"),
            current_event_bus.set(self.bus),
        ]
        yield
        for tok in reversed(self.tokens):
            try:
                tok.var.reset(tok)
            except Exception:
                pass
        self.bus.close()

    def test_save_user_scope(self):
        result = save_memory(content="User preference: dark mode", scope="user", file="preferences.md")
        assert result["status"] == "saved"
        assert result["scope"] == "user"

    def test_save_tenant_scope(self):
        result = save_memory(content="Team policy", scope="tenant", file="policies.md")
        assert result["status"] == "saved"

    def test_save_global_scope(self):
        result = save_memory(content="Global rule", scope="global", file="rules.md")
        assert result["status"] == "saved"

    def test_save_append_mode(self):
        save_memory(content="line1", scope="user", file="notes.md", mode="append")
        save_memory(content="line2", scope="user", file="notes.md", mode="append")
        content = self.store.read_file("user", "notes.md", tenant_id="T1", user_id="U1")
        assert "line1" in content
        assert "line2" in content

    def test_save_rewrite_mode(self):
        save_memory(content="old", scope="user", file="notes.md", mode="append")
        save_memory(content="new", scope="user", file="notes.md", mode="rewrite")
        content = self.store.read_file("user", "notes.md", tenant_id="T1", user_id="U1")
        assert "old" not in content
        assert "new" in content

    def test_invalid_scope(self):
        result = save_memory(content="test", scope="invalid")
        assert "error" in result

    def test_invalid_mode(self):
        result = save_memory(content="test", scope="user", mode="delete")
        assert "error" in result

    def test_no_store_error(self):
        current_memory_store.set(None)
        result = save_memory(content="test")
        assert "error" in result

    def test_emits_memory_saved_event(self):
        save_memory(content="test", scope="user", file="test.md")
        events = [e for e in self.bus.history if e.event_type == "memory_saved"]
        assert len(events) == 1
        assert events[0].data["scope"] == "user"


class TestRecallMemory:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.store = MarkdownMemoryStore(base_dir=str(tmp_path / "memory"))
        self.tokens = [
            current_memory_store.set(self.store),
            current_tenant_id.set("T1"),
            current_user_id.set("U1"),
        ]
        # Seed some data
        self.store.write_file("user", "notes.md", "user notes", "append", "T1", "U1")
        self.store.write_file("global", "rules.md", "global rules", "append")
        yield
        for tok in reversed(self.tokens):
            try:
                tok.var.reset(tok)
            except Exception:
                pass

    def test_recall_user_file(self):
        result = recall_memory(scope="user", file="notes.md")
        assert "user notes" in result["content"]

    def test_recall_global_file(self):
        result = recall_memory(scope="global", file="rules.md")
        assert "global rules" in result["content"]

    def test_recall_nonexistent_file(self):
        result = recall_memory(scope="user", file="nope.md")
        assert "不存在" in result["content"] or "空" in result["content"]

    def test_recall_all_scopes(self):
        result = recall_memory(scope="all")
        assert "content" in result
        assert result["scope"] == "all"

    def test_recall_scope_listing(self):
        result = recall_memory(scope="user")
        assert "files" in result

    def test_invalid_scope(self):
        result = recall_memory(scope="bad")
        assert "error" in result

    def test_no_store_error(self):
        current_memory_store.set(None)
        result = recall_memory()
        assert "error" in result


class TestMemoryToolRegistry:
    def test_save_registered(self):
        assert "save_memory" in memory_capability_registry.get_tool_names()

    def test_recall_registered(self):
        assert "recall_memory" in memory_capability_registry.get_tool_names()

    def test_recall_is_read_only(self):
        assert memory_capability_registry.is_read_only("recall_memory") is True

    def test_save_not_read_only(self):
        assert memory_capability_registry.is_read_only("save_memory") is False
