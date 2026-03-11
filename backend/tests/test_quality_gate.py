"""Tests for agent/quality_gate.py — self-correction quality checks."""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.hooks import HookEvent
from agent.quality_gate import (
    QualityCheckResult,
    QualityGate,
    check_form_completeness,
    check_audit_consistency,
    check_calculation_verified,
    quality_gate_hook,
    reset_correction_count,
    _correction_counts,
    MAX_SELF_CORRECTIONS,
)


def _make_event(
    context: dict | None = None,
    runtime_steps: list | None = None,
    user_id: str = "U1",
    session_id: str = "S1",
) -> HookEvent:
    return HookEvent(
        event_type="agent_stop",
        tool_name="",
        tool_input={},
        context=context or {},
        runtime_steps=runtime_steps or [],
        user_id=user_id,
        session_id=session_id,
    )


# ── QualityCheckResult ──


class TestQualityCheckResult:
    def test_defaults(self):
        r = QualityCheckResult()
        assert r.passed is True
        assert r.issues == []
        assert r.corrections == []


# ── check_form_completeness ──


class TestCheckFormCompleteness:
    def test_non_create_skips(self):
        event = _make_event(context={"business_type": "query"})
        passed, issue, correction = check_form_completeness(event)
        assert passed is True

    def test_no_form_fields_pass(self):
        event = _make_event(context={"business_type": "draft_doc"})
        passed, _, _ = check_form_completeness(event)
        assert passed is True

    def test_no_required_fields_pass(self):
        event = _make_event(context={
            "business_type": "create_invoice",
            "form_fields": [{"field_id": "note", "required": False}],
        })
        passed, _, _ = check_form_completeness(event)
        assert passed is True

    def test_all_required_filled(self):
        event = _make_event(
            context={
                "business_type": "create_invoice",
                "form_fields": [{"field_id": "amount", "required": True}],
            },
            runtime_steps=[
                {"tool": "update_form_field", "args": {"field_id": "amount"}},
            ],
        )
        passed, _, _ = check_form_completeness(event)
        assert passed is True

    def test_missing_required_field(self):
        event = _make_event(
            context={
                "business_type": "create_invoice",
                "form_fields": [
                    {"field_id": "amount", "required": True},
                    {"field_id": "vendor", "required": True},
                ],
            },
            runtime_steps=[
                {"tool": "update_form_field", "args": {"field_id": "amount"}},
            ],
        )
        passed, issue, correction = check_form_completeness(event)
        assert passed is False
        assert "vendor" in issue
        assert "update_form_field" in correction


# ── check_audit_consistency ──


class TestCheckAuditConsistency:
    def test_no_audit_pass(self):
        event = _make_event(runtime_steps=[])
        passed, _, _ = check_audit_consistency(event)
        assert passed is True

    def test_audit_without_submit(self):
        event = _make_event(runtime_steps=[
            {"tool": "check_audit_rule", "result": "通过"},
        ])
        passed, issue, correction = check_audit_consistency(event)
        assert passed is False
        assert "未提交" in issue

    def test_audit_with_submit(self):
        event = _make_event(runtime_steps=[
            {"tool": "check_audit_rule", "result": "通过"},
            {"tool": "submit_all_audit_results"},
        ])
        passed, _, _ = check_audit_consistency(event)
        assert passed is True


# ── check_calculation_verified ──


class TestCheckCalculationVerified:
    def test_no_numeric_pass(self):
        event = _make_event(context={"final_answer": "操作完成"})
        passed, _, _ = check_calculation_verified(event)
        assert passed is True

    def test_numeric_without_calculator(self):
        event = _make_event(
            context={"final_answer": "金额超出预算 500 元"},
            runtime_steps=[{"tool": "read_file"}],
        )
        passed, issue, correction = check_calculation_verified(event)
        assert passed is False
        assert "calculator" in correction

    def test_numeric_with_calculator(self):
        event = _make_event(
            context={"final_answer": "金额超出预算 500 元"},
            runtime_steps=[{"tool": "arithmetic"}],
        )
        passed, _, _ = check_calculation_verified(event)
        assert passed is True

    def test_all_calculator_tools_accepted(self):
        for tool in ["arithmetic", "numeric_compare", "sum_values", "calculate_ratio", "date_diff"]:
            event = _make_event(
                context={"final_answer": "合计超标"},
                runtime_steps=[{"tool": tool}],
            )
            passed, _, _ = check_calculation_verified(event)
            assert passed is True, f"Tool {tool} should satisfy calculator check"


# ── QualityGate.evaluate ──


class TestQualityGateEvaluate:
    def test_all_pass(self):
        gate = QualityGate(checks=[lambda e: (True, "", "")])
        result = gate.evaluate(_make_event())
        assert result.passed is True

    def test_one_fail(self):
        gate = QualityGate(checks=[
            lambda e: (True, "", ""),
            lambda e: (False, "problem", "fix it"),
        ])
        result = gate.evaluate(_make_event())
        assert result.passed is False
        assert "problem" in result.issues
        assert "fix it" in result.corrections

    def test_check_exception_ignored(self):
        def bad_check(e):
            raise RuntimeError("boom")

        gate = QualityGate(checks=[bad_check])
        result = gate.evaluate(_make_event())
        assert result.passed is True  # Error → treated as pass


# ── quality_gate_hook ──


class TestQualityGateHook:
    def setup_method(self):
        _correction_counts.clear()

    def test_pass_allows(self):
        event = _make_event(context={"business_type": "query"})
        result = quality_gate_hook(event)
        assert result.action == "allow"

    def test_fail_blocks_with_correction(self):
        event = _make_event(
            context={
                "business_type": "create_invoice",
                "form_fields": [{"field_id": "amount", "required": True}],
            },
            runtime_steps=[],
        )
        result = quality_gate_hook(event)
        assert result.action == "block"
        assert "质量检查" in result.message

    def test_max_corrections_allows(self):
        """After MAX_SELF_CORRECTIONS, should allow despite issues."""
        key = "U1:S1"
        _correction_counts[key] = MAX_SELF_CORRECTIONS
        event = _make_event(
            context={
                "business_type": "create_invoice",
                "form_fields": [{"field_id": "amount", "required": True}],
            },
        )
        result = quality_gate_hook(event)
        assert result.action == "allow"

    def test_reset_correction_count(self):
        _correction_counts["U1:S1"] = 2
        reset_correction_count("U1:S1")
        assert "U1:S1" not in _correction_counts

    def test_cleanup_on_overflow(self):
        """When dict grows > 100, it should clear."""
        for i in range(101):
            _correction_counts[f"user:{i}"] = 1
        event = _make_event(context={"business_type": "query"})
        quality_gate_hook(event)
        assert len(_correction_counts) <= 1
