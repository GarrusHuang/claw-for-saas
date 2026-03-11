"""Tests for agent/workflow.py — WorkflowTracker."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.workflow import WorkflowTracker, WorkflowPhase


def test_initial_state():
    t = WorkflowTracker()
    assert t.current_phase == WorkflowPhase.INITIALIZING


def test_classify_type_phase():
    t = WorkflowTracker()
    phase = t.on_tool_call("classify_type")
    assert phase == WorkflowPhase.CLASSIFYING


def test_update_form_field_phase():
    t = WorkflowTracker()
    phase = t.on_tool_call("update_form_field")
    assert phase == WorkflowPhase.FORM_FILLING


def test_check_audit_rule_phase():
    t = WorkflowTracker()
    phase = t.on_tool_call("check_audit_rule")
    assert phase == WorkflowPhase.AUDITING


def test_unknown_tool_no_change():
    t = WorkflowTracker()
    phase = t.on_tool_call("some_random_tool")
    assert phase == WorkflowPhase.INITIALIZING


def test_estimate_progress_increases():
    t = WorkflowTracker()
    p0 = t.estimate_progress()
    t.on_tool_call("classify_type")
    p1 = t.estimate_progress()
    t.on_tool_call("update_form_field")
    p2 = t.estimate_progress()
    assert p1 > p0
    assert p2 > p1


def test_mark_completed():
    t = WorkflowTracker()
    t.on_tool_call("classify_type")
    t.mark_completed()
    assert t.current_phase == WorkflowPhase.COMPLETING


def test_to_dict_keys():
    t = WorkflowTracker()
    d = t.to_dict()
    assert "phase" in d
    assert "completed_phases" in d
    assert "progress" in d
    assert "tool_count" in d


def test_business_type_affects_progress():
    t1 = WorkflowTracker(business_type="reimbursement_review")  # 3 phases
    t2 = WorkflowTracker(business_type="reimbursement_create")  # 5 phases
    # Same state, different total → different progress
    p1 = t1.estimate_progress()
    p2 = t2.estimate_progress()
    assert p1 > p2  # fewer total phases → higher progress


def test_completed_phases_tracked():
    t = WorkflowTracker()
    t.on_tool_call("classify_type")
    t.on_tool_call("update_form_field")
    # INITIALIZING and CLASSIFYING should be completed
    assert WorkflowPhase.INITIALIZING in t.completed_phases
    assert WorkflowPhase.CLASSIFYING in t.completed_phases
