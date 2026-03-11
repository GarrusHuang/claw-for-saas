"""Tests for memory/learning.py — two-phase learning memory."""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.learning import LearningMemory, LearningExperience


class TestLearningExperience:
    def test_defaults(self):
        exp = LearningExperience()
        assert exp.experience_id  # auto-generated
        assert exp.confidence == 0.5
        assert exp.use_count == 0


class TestRecordSuccess:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.lm = LearningMemory(storage_path=str(tmp_path / "learning.json"))

    def test_record_new(self):
        exp = self.lm.record_success(
            scenario="audit_review",
            business_type="reimbursement",
            description="Travel expense audit",
        )
        assert exp.scenario == "audit_review"
        assert exp.confidence == 0.9  # no corrections
        assert self.lm.total_experiences == 1

    def test_confidence_with_corrections(self):
        exp = self.lm.record_success(
            scenario="s1", business_type="bt1", correction_count=1,
        )
        assert exp.confidence == 0.7

    def test_confidence_with_many_corrections(self):
        exp = self.lm.record_success(
            scenario="s1", business_type="bt1", correction_count=5,
        )
        assert exp.confidence == 0.5

    def test_update_existing(self):
        self.lm.record_success(scenario="s1", business_type="bt1", category="c1", doc_type="d1")
        exp = self.lm.record_success(scenario="s1", business_type="bt1", category="c1", doc_type="d1")
        assert exp.use_count == 1
        assert abs(exp.confidence - 0.95) < 1e-9  # 0.9 + 0.05
        assert self.lm.total_experiences == 1

    def test_confidence_cap(self):
        self.lm.record_success(scenario="s1", business_type="bt1", category="c1", doc_type="d1")
        for _ in range(10):
            exp = self.lm.record_success(scenario="s1", business_type="bt1", category="c1", doc_type="d1")
        assert exp.confidence <= 0.99

    def test_infer_category_audit(self):
        exp = self.lm.record_success(scenario="audit_check", business_type="bt1")
        assert exp.category == "audit_pattern"

    def test_infer_category_form(self):
        exp = self.lm.record_success(scenario="create_invoice", business_type="bt1")
        assert exp.category == "form_fill_strategy"

    def test_infer_category_general(self):
        exp = self.lm.record_success(scenario="chat", business_type="bt1")
        assert exp.category == "general"


class TestGetRelevantExperiences:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.lm = LearningMemory(storage_path=str(tmp_path / "learning.json"))
        # Create varied experiences
        self.lm.record_success(scenario="s1", business_type="bt1", doc_type="d1", description="exact match")
        self.lm.record_success(scenario="s1", business_type="bt1", doc_type="d2", description="scenario match")
        self.lm.record_success(scenario="s2", business_type="bt1", description="type match")
        self.lm.record_success(scenario="s3", business_type="bt2", description="unrelated")

    def test_exact_match(self):
        results = self.lm.get_relevant_experiences("s1", "bt1", "d1")
        assert len(results) >= 1
        assert results[0].description == "exact match"

    def test_scenario_match(self):
        results = self.lm.get_relevant_experiences("s1", "bt1")
        assert len(results) >= 2

    def test_type_match_fallback(self):
        results = self.lm.get_relevant_experiences("unknown", "bt1")
        assert len(results) >= 1  # Falls back to business_type match

    def test_no_match(self):
        results = self.lm.get_relevant_experiences("x", "y")
        assert results == []

    def test_top_k_limit(self):
        results = self.lm.get_relevant_experiences("s1", "bt1", top_k=1)
        assert len(results) == 1


class TestBuildExperiencePrompt:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.lm = LearningMemory(storage_path=str(tmp_path / "learning.json"))

    def test_no_experiences_empty(self):
        result = self.lm.build_experience_prompt("s1", "bt1")
        assert result == ""

    def test_with_experiences(self):
        self.lm.record_success(
            scenario="s1", business_type="bt1",
            description="先查标准再比较",
            success_pattern={"tool_chain": ["get_standards", "arithmetic"]},
        )
        prompt = self.lm.build_experience_prompt("s1", "bt1")
        assert "历史成功案例" in prompt
        assert "先查标准再比较" in prompt
        assert "get_standards → arithmetic" in prompt


class TestConsolidate:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.lm = LearningMemory(storage_path=str(tmp_path / "learning.json"))

    def test_no_removal_fresh(self):
        self.lm.record_success(scenario="s1", business_type="bt1")
        removed = self.lm.consolidate()
        assert removed == 0

    def test_max_experiences_cap(self):
        for i in range(15):
            self.lm.record_success(
                scenario=f"s{i}", business_type="bt1",
                category=f"c{i}", doc_type=f"d{i}",
            )
        removed = self.lm.consolidate(max_experiences=10)
        assert self.lm.total_experiences == 10
        assert removed == 5


class TestPersistence:
    def test_save_and_reload(self, tmp_path):
        path = str(tmp_path / "learning.json")
        lm1 = LearningMemory(storage_path=path)
        lm1.record_success(scenario="s1", business_type="bt1", description="test")

        lm2 = LearningMemory(storage_path=path)
        assert lm2.total_experiences == 1
        exps = lm2.get_relevant_experiences("s1", "bt1")
        assert exps[0].description == "test"


class TestStats:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.lm = LearningMemory(storage_path=str(tmp_path / "learning.json"))

    def test_empty_stats(self):
        stats = self.lm.get_stats()
        assert stats["total"] == 0
        assert stats["avg_confidence"] == 0.0

    def test_with_data(self):
        self.lm.record_success(scenario="s1", business_type="bt1")
        self.lm.record_success(scenario="s2", business_type="bt2")
        stats = self.lm.get_stats()
        assert stats["total"] == 2
        assert stats["scenarios"] == 2

    def test_clear(self):
        self.lm.record_success(scenario="s1", business_type="bt1")
        self.lm.clear()
        assert self.lm.total_experiences == 0
