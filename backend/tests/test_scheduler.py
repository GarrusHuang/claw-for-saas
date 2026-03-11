"""
A9: 定时调度测试 — ScheduledTask / ScheduleStore / Scheduler。
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.scheduler import ScheduledTask, ScheduleStore, Scheduler, compute_next_run


# ───── ScheduledTask serialization ─────

class TestScheduledTask:
    def test_defaults(self):
        t = ScheduledTask(
            id="t1", name="Test", cron="0 9 * * *",
            message="hi", user_id="U1", tenant_id="T1",
        )
        assert t.enabled is True
        assert t.last_run_at is None
        assert t.last_run_status == ""
        assert t.business_type == "scheduled_task"

    def test_to_dict(self):
        t = ScheduledTask(
            id="t1", name="N", cron="*/5 * * * *",
            message="m", user_id="U1", tenant_id="T1",
        )
        d = t.to_dict()
        assert d["id"] == "t1"
        assert d["cron"] == "*/5 * * * *"

    def test_from_dict(self):
        data = {
            "id": "t2", "name": "N2", "cron": "0 0 * * *",
            "message": "daily", "user_id": "U1", "tenant_id": "T1",
            "enabled": False, "last_run_status": "success",
        }
        t = ScheduledTask.from_dict(data)
        assert t.id == "t2"
        assert t.enabled is False
        assert t.last_run_status == "success"

    def test_roundtrip(self):
        orig = ScheduledTask(
            id="t3", name="RT", cron="0 */2 * * *",
            message="test", user_id="U1", tenant_id="T1",
        )
        restored = ScheduledTask.from_dict(orig.to_dict())
        assert restored.id == orig.id
        assert restored.cron == orig.cron


# ───── compute_next_run ─────

class TestComputeNextRun:
    def test_next_run_in_future(self):
        now = time.time()
        next_run = compute_next_run("* * * * *", now)
        assert next_run > now

    def test_daily_cron(self):
        now = time.time()
        next_run = compute_next_run("0 9 * * *", now)
        assert next_run > now


# ───── ScheduleStore ─────

class TestScheduleStore:
    def test_add_and_list(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        task = ScheduledTask(
            id="s1", name="Job1", cron="0 9 * * *",
            message="go", user_id="U1", tenant_id="T1",
        )
        store.add(task)
        tasks = store.list_tasks("T1", "U1")
        assert len(tasks) == 1
        assert tasks[0].id == "s1"

    def test_remove(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        task = ScheduledTask(
            id="s2", name="Job2", cron="0 0 * * *",
            message="x", user_id="U1", tenant_id="T1",
        )
        store.add(task)
        assert store.remove("T1", "U1", "s2") is True
        assert store.list_tasks("T1", "U1") == []

    def test_remove_nonexistent(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        assert store.remove("T1", "U1", "nope") is False

    def test_get(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        task = ScheduledTask(
            id="s3", name="Job3", cron="*/10 * * * *",
            message="y", user_id="U1", tenant_id="T1",
        )
        store.add(task)
        got = store.get("T1", "U1", "s3")
        assert got is not None
        assert got.name == "Job3"

    def test_get_nonexistent(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        assert store.get("T1", "U1", "nope") is None

    def test_update(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        task = ScheduledTask(
            id="s4", name="Old", cron="0 0 * * *",
            message="z", user_id="U1", tenant_id="T1",
        )
        store.add(task)
        task.name = "New"
        store.update(task)
        got = store.get("T1", "U1", "s4")
        assert got.name == "New"

    def test_list_all_tasks(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        t1 = ScheduledTask(id="a", name="A", cron="0 0 * * *", message="1", user_id="U1", tenant_id="T1")
        t2 = ScheduledTask(id="b", name="B", cron="0 0 * * *", message="2", user_id="U2", tenant_id="T1")
        t3 = ScheduledTask(id="c", name="C", cron="0 0 * * *", message="3", user_id="U1", tenant_id="T2")
        store.add(t1)
        store.add(t2)
        store.add(t3)
        all_tasks = store.list_all_tasks()
        assert len(all_tasks) == 3

    def test_list_all_empty(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        assert store.list_all_tasks() == []


# ───── Scheduler ─────

class TestScheduler:
    @pytest.mark.asyncio
    async def test_start_loads_tasks(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        task = ScheduledTask(
            id="st1", name="StartTest", cron="0 9 * * *",
            message="hello", user_id="U1", tenant_id="T1",
            enabled=True,
        )
        store.add(task)

        scheduler = Scheduler(store=store, gateway_factory=lambda: None, check_interval_s=3600)
        await scheduler.start()
        assert "st1" in scheduler._tasks
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_add_task(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        scheduler = Scheduler(store=store, gateway_factory=lambda: None)

        task = ScheduledTask(
            id="at1", name="AddTest", cron="*/5 * * * *",
            message="go", user_id="U1", tenant_id="T1",
        )
        result = scheduler.add_task(task)
        assert result.next_run_at is not None
        assert "at1" in scheduler._tasks
        assert len(store.list_tasks("T1", "U1")) == 1

    @pytest.mark.asyncio
    async def test_remove_task(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        scheduler = Scheduler(store=store, gateway_factory=lambda: None)

        task = ScheduledTask(
            id="rt1", name="RmTest", cron="0 0 * * *",
            message="x", user_id="U1", tenant_id="T1",
        )
        scheduler.add_task(task)
        assert scheduler.remove_task("T1", "U1", "rt1") is True
        assert "rt1" not in scheduler._tasks
        assert len(store.list_tasks("T1", "U1")) == 0

    @pytest.mark.asyncio
    async def test_pause_resume(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        scheduler = Scheduler(store=store, gateway_factory=lambda: None)

        task = ScheduledTask(
            id="pr1", name="PauseTest", cron="0 0 * * *",
            message="x", user_id="U1", tenant_id="T1",
        )
        scheduler.add_task(task)
        assert scheduler.pause_task("T1", "U1", "pr1") is True
        assert "pr1" not in scheduler._tasks
        stored = store.get("T1", "U1", "pr1")
        assert stored.enabled is False

        assert scheduler.resume_task("T1", "U1", "pr1") is True
        assert "pr1" in scheduler._tasks
        stored = store.get("T1", "U1", "pr1")
        assert stored.enabled is True

    @pytest.mark.asyncio
    async def test_update_task(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        scheduler = Scheduler(store=store, gateway_factory=lambda: None)

        task = ScheduledTask(
            id="ut1", name="Old", cron="0 0 * * *",
            message="x", user_id="U1", tenant_id="T1",
        )
        scheduler.add_task(task)
        updated = scheduler.update_task("T1", "U1", "ut1", name="New", cron="*/10 * * * *")
        assert updated.name == "New"
        assert updated.cron == "*/10 * * * *"

    @pytest.mark.asyncio
    async def test_execute_task_success(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        mock_gateway = AsyncMock()
        mock_gateway.chat = AsyncMock(return_value={"answer": "done"})

        scheduler = Scheduler(
            store=store,
            gateway_factory=lambda: mock_gateway,
        )

        task = ScheduledTask(
            id="ex1", name="ExecTest", cron="* * * * *",
            message="run", user_id="U1", tenant_id="T1",
        )
        scheduler.add_task(task)
        await scheduler._execute_task(task)

        mock_gateway.chat.assert_awaited_once()
        stored = store.get("T1", "U1", "ex1")
        assert stored.last_run_status == "success"
        assert stored.last_run_at is not None

    @pytest.mark.asyncio
    async def test_execute_task_failure(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        mock_gateway = AsyncMock()
        mock_gateway.chat = AsyncMock(side_effect=Exception("boom"))

        scheduler = Scheduler(
            store=store,
            gateway_factory=lambda: mock_gateway,
        )

        task = ScheduledTask(
            id="ef1", name="FailTest", cron="* * * * *",
            message="run", user_id="U1", tenant_id="T1",
        )
        scheduler.add_task(task)
        await scheduler._execute_task(task)

        stored = store.get("T1", "U1", "ef1")
        assert stored.last_run_status == "failed"

    @pytest.mark.asyncio
    async def test_execute_task_with_webhook(self, tmp_path):
        store = ScheduleStore(str(tmp_path))
        mock_gateway = AsyncMock()
        mock_gateway.chat = AsyncMock(return_value={"answer": "ok"})
        mock_dispatcher = AsyncMock()
        mock_dispatcher.dispatch = AsyncMock(return_value=True)

        scheduler = Scheduler(
            store=store,
            gateway_factory=lambda: mock_gateway,
            webhook_dispatcher=mock_dispatcher,
        )

        task = ScheduledTask(
            id="wh1", name="WhTest", cron="* * * * *",
            message="run", user_id="U1", tenant_id="T1",
        )
        scheduler.add_task(task)
        await scheduler._execute_task(task)

        mock_dispatcher.dispatch.assert_awaited_once()
        call_args = mock_dispatcher.dispatch.call_args
        assert call_args.kwargs["event"] == "task_completed"
