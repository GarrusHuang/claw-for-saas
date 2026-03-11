"""Tests for tools/builtin/plan_tools.py — propose_plan tool (A2 simplified)."""
import sys
import os
import json

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.context import current_event_bus, current_plan_tracker
from core.event_bus import EventBus
from tools.builtin.plan_tools import propose_plan, plan_capability_registry


class TestProposePlan:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.bus = EventBus(trace_id="test")
        self.token = current_event_bus.set(self.bus)
        yield
        current_event_bus.reset(self.token)
        self.bus.close()

    def test_basic_plan(self):
        result = propose_plan(
            summary="执行审核",
            steps=[{"action": "check", "tools": ["arithmetic"]}],
        )
        assert result["status"] == "ok"

    def test_emits_plan_proposed_event(self):
        propose_plan(
            summary="Test plan",
            steps=[{"action": "step1", "tools": ["read_file"]}],
            detail="# Plan\n## Steps\n1. Read file",
            estimated_actions=3,
        )
        history = self.bus.history
        plan_events = [e for e in history if e.event_type == "plan_proposed"]
        assert len(plan_events) == 1
        data = plan_events[0].data
        assert data["summary"] == "Test plan"
        assert data["detail"].startswith("# Plan")
        assert data["estimated_actions"] == 3
        assert len(data["steps"]) == 1

    def test_creates_plan_tracker(self):
        propose_plan(
            summary="Test",
            steps=[
                {"action": "s1", "tools": ["tool_a"]},
                {"action": "s2", "tools": ["tool_b"]},
            ],
        )
        tracker = current_plan_tracker.get(None)
        assert tracker is not None
        assert len(tracker.steps) == 2

    def test_steps_json_string(self):
        """LLM may pass steps as JSON string instead of list."""
        steps_json = json.dumps([{"action": "step1", "tools": ["calc"]}])
        result = propose_plan(summary="Test", steps=steps_json)
        assert result["status"] == "ok"
        tracker = current_plan_tracker.get(None)
        assert len(tracker.steps) == 1

    def test_steps_invalid_json_string(self):
        """Invalid JSON string should fall back to empty list."""
        result = propose_plan(summary="Test", steps="not valid json")
        assert result["status"] == "ok"
        tracker = current_plan_tracker.get(None)
        assert len(tracker.steps) == 0

    def test_empty_steps(self):
        result = propose_plan(summary="Simple task", steps=[])
        assert result["status"] == "ok"

    def test_default_estimated_actions(self):
        propose_plan(summary="Test", steps=[])
        events = [e for e in self.bus.history if e.event_type == "plan_proposed"]
        assert events[0].data["estimated_actions"] == 10

    def test_no_requires_approval(self):
        """A2: requires_approval removed — plan is pure progress display."""
        propose_plan(summary="Test", steps=[])
        events = [e for e in self.bus.history if e.event_type == "plan_proposed"]
        assert "requires_approval" not in events[0].data


class TestPlanToolRegistry:
    def test_registered(self):
        assert "propose_plan" in plan_capability_registry.get_tool_names()

    def test_not_read_only(self):
        assert plan_capability_registry.is_read_only("propose_plan") is False
