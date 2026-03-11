"""Tests for memory/correction.py — CorrectionMemory."""
import sys
import os
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.correction import CorrectionMemory, CorrectionRecord


class TestCorrectionMemory:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.storage_path = str(tmp_path / "correction_memory.json")
        self.mem = CorrectionMemory(storage_path=self.storage_path)

    def test_record_correction(self):
        record = self.mem.record_correction(
            user_id="U001",
            business_type="expense",
            doc_type="travel",
            field_id="meal_subsidy",
            agent_value="80",
            user_value="100",
        )
        assert record.user_id == "U001"
        assert record.field_id == "meal_subsidy"
        assert self.mem.total_records == 1

    def test_deduplication(self):
        self.mem.record_correction("U001", "expense", "travel", "f1", "a", "b")
        self.mem.record_correction("U001", "expense", "travel", "f1", "a", "b")
        assert self.mem.total_records == 1
        record = self.mem.get_corrections("U001", "expense")[0]
        assert record.times_applied == 1  # incremented once

    def test_different_values_not_deduplicated(self):
        self.mem.record_correction("U001", "expense", "travel", "f1", "a", "b")
        self.mem.record_correction("U001", "expense", "travel", "f1", "a", "c")
        assert self.mem.total_records == 2

    def test_get_corrections_filter(self):
        self.mem.record_correction("U001", "expense", "travel", "f1", "a", "b")
        self.mem.record_correction("U001", "contract", "purchase", "f2", "c", "d")
        self.mem.record_correction("U002", "expense", "travel", "f3", "e", "f")

        results = self.mem.get_corrections("U001", "expense")
        assert len(results) == 1
        assert results[0].field_id == "f1"

    def test_get_corrections_by_field(self):
        self.mem.record_correction("U001", "expense", "travel", "f1", "a", "b")
        self.mem.record_correction("U001", "expense", "travel", "f2", "c", "d")

        results = self.mem.get_corrections("U001", "expense", field_id="f1")
        assert len(results) == 1

    def test_sorting_by_priority(self):
        self.mem.record_correction("U001", "expense", "travel", "f1", "a", "b")
        # Record the same correction multiple times to increase times_applied
        for _ in range(3):
            self.mem.record_correction("U001", "expense", "travel", "f2", "c", "d")

        results = self.mem.get_corrections("U001", "expense")
        # f2 should come first (higher times_applied)
        assert results[0].field_id == "f2"

    def test_build_preference_prompt(self):
        self.mem.record_correction("U001", "expense", "travel", "meal", "80", "100")
        prompt = self.mem.build_preference_prompt("U001", "expense", "travel")
        assert "meal" in prompt
        assert "80" in prompt
        assert "100" in prompt

    def test_build_preference_prompt_empty(self):
        prompt = self.mem.build_preference_prompt("U001", "expense", "travel")
        assert prompt == ""

    def test_persistence(self):
        self.mem.record_correction("U001", "expense", "travel", "f1", "a", "b")

        # Create new instance to test loading
        mem2 = CorrectionMemory(storage_path=self.storage_path)
        assert mem2.total_records == 1
        assert mem2.get_corrections("U001", "expense")[0].field_id == "f1"

    def test_get_stats(self):
        self.mem.record_correction("U001", "expense", "travel", "f1", "a", "b")
        self.mem.record_correction("U002", "expense", "travel", "f2", "c", "d")

        stats = self.mem.get_stats()
        assert stats["total"] == 2
        assert stats["users"] == 2
        assert stats["fields"] == 2

    def test_get_stats_empty(self):
        stats = self.mem.get_stats()
        assert stats["total"] == 0

    def test_cleanup_stale(self):
        # Create old record
        record = self.mem.record_correction("U001", "expense", "travel", "f1", "a", "b")
        record.created_at = time.time() - 200 * 86400  # 200 days ago
        record.times_applied = 0
        self.mem._save()

        removed = self.mem.cleanup_stale(max_age_days=180)
        assert removed == 1
        assert self.mem.total_records == 0

    def test_cleanup_keeps_active_records(self):
        record = self.mem.record_correction("U001", "expense", "travel", "f1", "a", "b")
        record.created_at = time.time() - 200 * 86400  # old
        record.times_applied = 5  # but actively used
        self.mem._save()

        removed = self.mem.cleanup_stale(max_age_days=180)
        assert removed == 0

    def test_clear(self):
        self.mem.record_correction("U001", "expense", "travel", "f1", "a", "b")
        self.mem.clear()
        assert self.mem.total_records == 0

    def test_mark_applied(self):
        record = self.mem.record_correction("U001", "expense", "travel", "f1", "a", "b")
        assert record.times_applied == 0
        self.mem.mark_applied(record)
        assert record.times_applied == 1
