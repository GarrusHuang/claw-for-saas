"""
A9: 定时调度工具测试 — create_schedule / list_schedules / delete_schedule。
"""

import contextvars
from unittest.mock import MagicMock, patch

import pytest

from core.context import current_scheduler, current_tenant_id, current_user_id
from tools.builtin.schedule_tools import (
    create_schedule, list_schedules, delete_schedule,
    schedule_capability_registry,
)
from core.scheduler import ScheduleStore, Scheduler, ScheduledTask


@pytest.fixture
def scheduler(tmp_path):
    store = ScheduleStore(str(tmp_path))
    s = Scheduler(store=store, gateway_factory=lambda: None)
    return s


@pytest.fixture(autouse=True)
def _set_context(scheduler):
    """Set up ContextVars for all tests."""
    t1 = current_scheduler.set(scheduler)
    t2 = current_tenant_id.set("T1")
    t3 = current_user_id.set("U1")
    yield
    current_scheduler.reset(t1)
    current_tenant_id.reset(t2)
    current_user_id.reset(t3)


# ───── Registry ─────

class TestScheduleRegistry:
    def test_has_three_tools(self):
        names = {t.name for t in schedule_capability_registry.list_tools()}
        assert "create_schedule" in names
        assert "list_schedules" in names
        assert "delete_schedule" in names

    def test_list_schedules_is_read_only(self):
        for t in schedule_capability_registry.list_tools():
            if t.name == "list_schedules":
                assert t.read_only is True
            else:
                assert t.read_only is False


# ───── create_schedule ─────

class TestCreateSchedule:
    def test_success(self):
        result = create_schedule(name="Daily", cron="0 9 * * *", message="run report")
        assert result["status"] == "created"
        assert "task_id" in result
        assert result["cron"] == "0 9 * * *"
        assert result["next_run_at"] is not None

    def test_invalid_cron(self):
        result = create_schedule(name="Bad", cron="not-a-cron", message="x")
        assert "error" in result
        assert "cron" in result["error"].lower()

    def test_with_business_type(self):
        result = create_schedule(
            name="Budget Check", cron="0 8 * * 1",
            message="check budget", business_type="budget_check",
        )
        assert result["status"] == "created"

    def test_no_scheduler(self):
        token = current_scheduler.set(None)
        try:
            result = create_schedule(name="X", cron="* * * * *", message="y")
            assert "error" in result
        finally:
            current_scheduler.reset(token)


# ───── list_schedules ─────

class TestListSchedules:
    def test_empty(self):
        result = list_schedules()
        assert result["total"] == 0
        assert result["tasks"] == []

    def test_with_tasks(self):
        create_schedule(name="A", cron="0 9 * * *", message="a")
        create_schedule(name="B", cron="0 10 * * *", message="b")
        result = list_schedules()
        assert result["total"] == 2
        names = {t["name"] for t in result["tasks"]}
        assert names == {"A", "B"}

    def test_no_scheduler(self):
        token = current_scheduler.set(None)
        try:
            result = list_schedules()
            assert "error" in result
        finally:
            current_scheduler.reset(token)


# ───── delete_schedule ─────

class TestDeleteSchedule:
    def test_success(self):
        r = create_schedule(name="Del", cron="0 0 * * *", message="d")
        task_id = r["task_id"]
        result = delete_schedule(task_id=task_id)
        assert result["status"] == "deleted"
        # Verify gone
        assert list_schedules()["total"] == 0

    def test_nonexistent(self):
        result = delete_schedule(task_id="nope")
        assert "error" in result

    def test_no_scheduler(self):
        token = current_scheduler.set(None)
        try:
            result = delete_schedule(task_id="x")
            assert "error" in result
        finally:
            current_scheduler.reset(token)
