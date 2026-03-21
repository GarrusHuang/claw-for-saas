"""Tests for tools/builtin/plan_tools.py — propose_plan + update_plan_step."""
import sys
import os
import json

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.context import RequestContext, current_request
from core.event_bus import EventBus
from tools.builtin.plan_tools import propose_plan, update_plan_step, plan_capability_registry


class TestProposePlan:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.bus = EventBus(trace_id="test")
        ctx = RequestContext(event_bus=self.bus)
        self.token = current_request.set(ctx)
        self.ctx = ctx
        yield
        current_request.reset(self.token)
        self.bus.close()

    def test_basic_plan(self):
        result = propose_plan(
            summary="执行审核",
            steps=[{"action": "check"}],
        )
        assert result["status"] == "ok"

    def test_emits_plan_proposed_event(self):
        propose_plan(
            summary="Test plan",
            steps=[{"action": "step1"}],
            detail="# Plan\n## Steps\n1. Do stuff",
            estimated_actions=3,
        )
        history = self.bus.history
        plan_events = [e for e in history if e.event_type == "plan_proposed"]
        assert len(plan_events) == 1
        data = plan_events[0].data
        assert data["summary"] == "Test plan"
        assert data["detail"].startswith("# Plan")
        assert data["estimated_actions"] == 3

    def test_creates_plan_tracker(self):
        propose_plan(
            summary="Test",
            steps=[
                {"action": "s1", "description": "Step 1"},
                {"action": "s2", "description": "Step 2"},
            ],
        )
        tracker = self.ctx.plan_tracker
        assert tracker is not None
        assert len(tracker.steps) == 2

    def test_steps_json_string(self):
        steps_json = json.dumps([{"action": "step1"}])
        result = propose_plan(summary="Test", steps=steps_json)
        assert result["status"] == "ok"
        tracker = self.ctx.plan_tracker
        assert len(tracker.steps) == 1

    def test_steps_invalid_json_string(self):
        result = propose_plan(summary="Test", steps="not valid json")
        assert result["status"] == "ok"
        tracker = self.ctx.plan_tracker
        assert len(tracker.steps) == 0

    def test_empty_steps(self):
        result = propose_plan(summary="Simple task", steps=[])
        assert result["status"] == "ok"

    def test_message_mentions_completed(self):
        result = propose_plan(summary="Test", steps=[{"action": "s1"}])
        assert "completed" in result["message"]


class TestUpdatePlanStep:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.bus = EventBus(trace_id="test")
        self.ctx = RequestContext(event_bus=self.bus)
        self.token = current_request.set(self.ctx)
        # 先创建 plan
        propose_plan(
            summary="Test plan",
            steps=[
                {"action": "s1", "description": "Step 1"},
                {"action": "s2", "description": "Step 2"},
                {"action": "s3", "description": "Step 3"},
            ],
        )
        yield
        current_request.reset(self.token)
        self.bus.close()

    def test_set_running(self):
        result = update_plan_step(step_index=0, status="running")
        assert result["ok"] is True
        # 验证 SSE 事件
        started = [e for e in self.bus.history if e.event_type == "step_started"]
        assert len(started) == 1
        assert started[0].data["step_index"] == 0

    def test_set_completed(self):
        update_plan_step(step_index=0, status="running")
        result = update_plan_step(step_index=0, status="completed")
        assert result["ok"] is True
        completed = [e for e in self.bus.history if e.event_type == "step_completed"]
        assert len(completed) == 1

    def test_set_failed(self):
        update_plan_step(step_index=1, status="running")
        result = update_plan_step(step_index=1, status="failed")
        assert result["ok"] is True
        failed = [e for e in self.bus.history if e.event_type == "step_failed"]
        assert len(failed) == 1

    def test_sequential_full_flow(self):
        """模拟完整的 AI 主动更新流程"""
        update_plan_step(step_index=0, status="running")
        update_plan_step(step_index=0, status="completed")
        update_plan_step(step_index=1, status="running")
        update_plan_step(step_index=1, status="completed")
        update_plan_step(step_index=2, status="running")
        update_plan_step(step_index=2, status="completed")

        tracker = self.ctx.plan_tracker
        assert all(s["status"] == "completed" for s in tracker.steps)

        started = [e for e in self.bus.history if e.event_type == "step_started"]
        completed = [e for e in self.bus.history if e.event_type == "step_completed"]
        assert len(started) == 3
        assert len(completed) == 3

    def test_out_of_range(self):
        result = update_plan_step(step_index=99, status="running")
        assert result["ok"] is False

    def test_invalid_status(self):
        result = update_plan_step(step_index=0, status="whatever")
        assert result["ok"] is False

    def test_no_tracker_returns_error(self):
        """没有调用 propose_plan 时直接调用 update_plan_step"""
        self.ctx.plan_tracker = None
        result = update_plan_step(step_index=0, status="running")
        assert result["ok"] is False
        assert "propose_plan" in result["error"]


class TestPlanToolRegistry:
    def test_propose_plan_registered(self):
        assert "propose_plan" in plan_capability_registry.get_tool_names()

    def test_update_plan_step_registered(self):
        assert "update_plan_step" in plan_capability_registry.get_tool_names()

    def test_both_not_read_only(self):
        assert plan_capability_registry.is_read_only("propose_plan") is False
        assert plan_capability_registry.is_read_only("update_plan_step") is False
