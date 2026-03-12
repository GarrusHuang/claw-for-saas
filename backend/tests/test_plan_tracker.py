"""Tests for agent/plan_tracker.py — AI 主动驱动 step 推进。"""
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
            {"action": "analyze", "description": "Analyze data"},
            {"action": "compute", "description": "Calculate"},
        ]
        pt = PlanTracker(steps, None)
        assert len(pt.steps) == 2
        assert pt.steps[0]["action"] == "analyze"
        assert pt.steps[1]["description"] == "Calculate"

    def test_initial_status_pending(self):
        pt = PlanTracker([{"action": "s1"}], None)
        assert pt.steps[0]["status"] == "pending"


class TestUpdateStep:
    def test_set_running(self):
        pt = PlanTracker([{"action": "s1"}], None)
        result = pt.update_step(0, "running")
        assert result["ok"] is True
        assert pt.steps[0]["status"] == "running"
        assert pt.steps[0]["started_at"] is not None
        assert pt.current_index == 0

    def test_set_completed(self):
        pt = PlanTracker([{"action": "s1"}], None)
        pt.update_step(0, "running")
        result = pt.update_step(0, "completed")
        assert result["ok"] is True
        assert pt.steps[0]["status"] == "completed"
        assert pt.steps[0]["completed_at"] is not None

    def test_set_failed(self):
        pt = PlanTracker([{"action": "s1"}], None)
        pt.update_step(0, "running")
        result = pt.update_step(0, "failed")
        assert result["ok"] is True
        assert pt.steps[0]["status"] == "failed"

    def test_running_idempotent(self):
        pt = PlanTracker([{"action": "s1"}], None)
        pt.update_step(0, "running")
        result = pt.update_step(0, "running")
        assert result["ok"] is True
        assert pt.steps[0]["status"] == "running"

    def test_out_of_range(self):
        pt = PlanTracker([{"action": "s1"}], None)
        result = pt.update_step(5, "running")
        assert result["ok"] is False
        assert "超出范围" in result["error"]

    def test_negative_index(self):
        pt = PlanTracker([{"action": "s1"}], None)
        result = pt.update_step(-1, "running")
        assert result["ok"] is False

    def test_invalid_status(self):
        pt = PlanTracker([{"action": "s1"}], None)
        result = pt.update_step(0, "unknown")
        assert result["ok"] is False
        assert "无效状态" in result["error"]

    def test_sequential_steps(self):
        """模拟 AI 逐步更新：s0 running → completed, s1 running → completed"""
        pt = PlanTracker([
            {"action": "s1", "description": "Step 1"},
            {"action": "s2", "description": "Step 2"},
        ], None)

        pt.update_step(0, "running")
        assert pt.current_index == 0

        pt.update_step(0, "completed")
        assert pt.steps[0]["status"] == "completed"
        assert pt.current_index is None  # 没有 running 的步骤

        pt.update_step(1, "running")
        assert pt.current_index == 1

        pt.update_step(1, "completed")
        assert pt.steps[1]["status"] == "completed"
        assert all(s["status"] == "completed" for s in pt.steps)

    def test_completed_has_duration(self):
        """completed 时应计算 duration_ms"""
        import time
        pt = PlanTracker([{"action": "s1"}], None)
        pt.update_step(0, "running")
        time.sleep(0.01)  # 10ms
        pt.update_step(0, "completed")
        assert pt.steps[0]["completed_at"] > pt.steps[0]["started_at"]


class TestUpdateStepEvents:
    def test_running_emits_step_started(self):
        events = []

        class FakeBus:
            def emit(self, event_type, data):
                events.append((event_type, data))

        pt = PlanTracker([{"action": "s1", "description": "Do stuff"}], FakeBus())
        pt.update_step(0, "running")
        assert len(events) == 1
        assert events[0][0] == "step_started"
        assert events[0][1]["step_index"] == 0
        assert events[0][1]["description"] == "Do stuff"

    def test_completed_emits_step_completed(self):
        events = []

        class FakeBus:
            def emit(self, event_type, data):
                events.append((event_type, data))

        pt = PlanTracker([{"action": "s1"}], FakeBus())
        pt.update_step(0, "running")
        pt.update_step(0, "completed")
        assert events[-1][0] == "step_completed"
        assert events[-1][1]["step_index"] == 0
        assert "duration_ms" in events[-1][1]

    def test_failed_emits_step_failed(self):
        events = []

        class FakeBus:
            def emit(self, event_type, data):
                events.append((event_type, data))

        pt = PlanTracker([{"action": "s1"}], FakeBus())
        pt.update_step(0, "running")
        pt.update_step(0, "failed")
        assert events[-1][0] == "step_failed"
        assert events[-1][1]["step_index"] == 0

    def test_running_idempotent_no_extra_event(self):
        events = []

        class FakeBus:
            def emit(self, event_type, data):
                events.append((event_type, data))

        pt = PlanTracker([{"action": "s1"}], FakeBus())
        pt.update_step(0, "running")
        pt.update_step(0, "running")  # 幂等，不发额外事件
        assert len(events) == 1


class TestCompleteAll:
    def test_complete_all_pending(self):
        pt = PlanTracker([
            {"action": "s1"},
            {"action": "s2"},
        ], None)
        pt.complete_all()
        assert all(s["status"] == "completed" for s in pt.steps)

    def test_complete_all_with_running(self):
        pt = PlanTracker([
            {"action": "s1"},
            {"action": "s2"},
        ], None)
        pt.update_step(0, "running")
        pt.complete_all()
        assert pt.steps[0]["status"] == "completed"
        assert pt.steps[1]["status"] == "completed"

    def test_complete_all_skips_already_completed(self):
        events = []

        class FakeBus:
            def emit(self, event_type, data):
                events.append((event_type, data))

        pt = PlanTracker([{"action": "s1"}, {"action": "s2"}], FakeBus())
        pt.update_step(0, "running")
        pt.update_step(0, "completed")
        events.clear()

        pt.complete_all()  # 只 complete s2
        completed_events = [e for e in events if e[0] == "step_completed"]
        assert len(completed_events) == 1
        assert completed_events[0][1]["step_index"] == 1


class TestFailCurrent:
    def test_fail_running_step(self):
        pt = PlanTracker([{"action": "s1"}], None)
        pt.update_step(0, "running")
        pt.fail_current()
        assert pt.steps[0]["status"] == "failed"

    def test_fail_no_current(self):
        pt = PlanTracker([{"action": "s1"}], None)
        pt.fail_current()  # No running step
        assert pt.steps[0]["status"] == "pending"
