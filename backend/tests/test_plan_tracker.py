"""Tests for agent/plan_tracker.py — step progression via tool matching."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.plan_tracker import PlanTracker


class TestPlanTrackerInit:
    def test_empty_steps(self):
        pt = PlanTracker([], None)
        assert pt.steps == []
        assert pt.current_index is None

    def test_steps_parsed(self):
        steps = [
            {"action": "analyze", "description": "Analyze data", "tools": ["read_file"]},
            {"action": "compute", "description": "Calculate", "tools": "arithmetic"},
        ]
        pt = PlanTracker(steps, None)
        assert len(pt.steps) == 2
        assert pt.steps[0]["tools"] == ["read_file"]
        assert pt.steps[1]["tools"] == ["arithmetic"]  # str → list

    def test_missing_tools(self):
        pt = PlanTracker([{"action": "step1"}], None)
        assert pt.steps[0]["tools"] == []

    def test_initial_status_pending(self):
        pt = PlanTracker([{"action": "s1", "tools": ["t1"]}], None)
        assert pt.steps[0]["status"] == "pending"


class TestOnToolExecuted:
    def test_first_tool_starts_step(self):
        pt = PlanTracker([
            {"action": "s1", "tools": ["tool_a"]},
        ], None)
        pt.on_tool_executed("tool_a")
        assert pt.current_index == 0
        assert pt.steps[0]["status"] == "running"

    def test_no_match_no_change(self):
        pt = PlanTracker([
            {"action": "s1", "tools": ["tool_a"]},
        ], None)
        pt.on_tool_executed("tool_b")
        assert pt.current_index is None

    def test_same_step_no_change(self):
        pt = PlanTracker([
            {"action": "s1", "tools": ["tool_a", "tool_b"]},
        ], None)
        pt.on_tool_executed("tool_a")
        assert pt.current_index == 0
        pt.on_tool_executed("tool_b")  # Same step
        assert pt.current_index == 0
        assert pt.steps[0]["status"] == "running"

    def test_advance_to_next_step(self):
        pt = PlanTracker([
            {"action": "s1", "tools": ["tool_a"]},
            {"action": "s2", "tools": ["tool_b"]},
        ], None)
        pt.on_tool_executed("tool_a")
        assert pt.current_index == 0
        pt.on_tool_executed("tool_b")
        assert pt.current_index == 1
        assert pt.steps[0]["status"] == "completed"
        assert pt.steps[1]["status"] == "running"

    def test_skip_intermediate_steps(self):
        pt = PlanTracker([
            {"action": "s1", "tools": ["tool_a"]},
            {"action": "s2", "tools": ["tool_b"]},
            {"action": "s3", "tools": ["tool_c"]},
        ], None)
        pt.on_tool_executed("tool_a")
        pt.on_tool_executed("tool_c")  # Skip s2
        assert pt.current_index == 2
        assert pt.steps[0]["status"] == "completed"
        assert pt.steps[1]["status"] == "completed"  # Auto-completed
        assert pt.steps[2]["status"] == "running"

    def test_empty_steps_no_error(self):
        pt = PlanTracker([], None)
        pt.on_tool_executed("anything")  # Should not raise


class TestCompleteAll:
    def test_complete_all_pending(self):
        pt = PlanTracker([
            {"action": "s1", "tools": ["t1"]},
            {"action": "s2", "tools": ["t2"]},
        ], None)
        pt.complete_all()
        assert all(s["status"] == "completed" for s in pt.steps)

    def test_complete_all_with_running(self):
        pt = PlanTracker([
            {"action": "s1", "tools": ["t1"]},
            {"action": "s2", "tools": ["t2"]},
        ], None)
        pt.on_tool_executed("t1")  # s1 running
        pt.complete_all()
        assert pt.steps[0]["status"] == "completed"
        assert pt.steps[1]["status"] == "completed"


class TestFailCurrent:
    def test_fail_running_step(self):
        pt = PlanTracker([
            {"action": "s1", "tools": ["t1"]},
        ], None)
        pt.on_tool_executed("t1")
        pt.fail_current()
        assert pt.steps[0]["status"] == "failed"

    def test_fail_no_current(self):
        pt = PlanTracker([
            {"action": "s1", "tools": ["t1"]},
        ], None)
        pt.fail_current()  # No current step, should not raise
        assert pt.steps[0]["status"] == "pending"
