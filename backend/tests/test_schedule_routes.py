"""
Comprehensive tests for A9 Schedule API routes.

Tests all 7 endpoints in api/schedule_routes.py:
  GET    /api/schedules              - list user's tasks
  POST   /api/schedules              - create task (validates cron)
  GET    /api/schedules/{task_id}    - get task detail
  PUT    /api/schedules/{task_id}    - update task (partial, validates cron)
  DELETE /api/schedules/{task_id}    - delete task
  POST   /api/schedules/{task_id}/pause  - pause task
  POST   /api/schedules/{task_id}/resume - resume task

Uses FastAPI TestClient with monkeypatched auth and scheduler dependencies.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import dependencies
from core.auth import AuthUser, get_current_user
from core.scheduler import ScheduledTask, Scheduler, ScheduleStore, compute_next_run


# ── Helpers ──


USER_A = AuthUser(tenant_id="tenant-1", user_id="UA01")
USER_B = AuthUser(tenant_id="tenant-1", user_id="UB02")
USER_OTHER_TENANT = AuthUser(tenant_id="tenant-2", user_id="UA01")

VALID_CRON = "*/5 * * * *"       # every 5 minutes
VALID_CRON_2 = "0 9 * * 1-5"     # 9 AM weekdays
INVALID_CRON = "not-a-cron"


def _make_task(
    task_id: str = "t001",
    name: str = "Daily report",
    cron: str = VALID_CRON,
    message: str = "Generate daily report",
    user_id: str = "UA01",
    tenant_id: str = "tenant-1",
    **kwargs,
) -> ScheduledTask:
    defaults = dict(
        id=task_id,
        name=name,
        cron=cron,
        message=message,
        user_id=user_id,
        tenant_id=tenant_id,
        business_type="scheduled_task",
        enabled=True,
        created_at=time.time(),
        last_run_at=None,
        last_run_status="",
        next_run_at=compute_next_run(cron),
    )
    defaults.update(kwargs)
    return ScheduledTask(**defaults)


def _clear_all_lru_caches():
    for name in dir(dependencies):
        obj = getattr(dependencies, name)
        if hasattr(obj, "cache_clear"):
            obj.cache_clear()


class FakeScheduler:
    """In-memory scheduler mock that mirrors the real Scheduler API."""

    def __init__(self):
        # Keyed as (tenant_id, user_id) -> list[ScheduledTask]
        self._store: dict[tuple[str, str], list[ScheduledTask]] = {}

    def _key(self, tenant_id: str, user_id: str) -> tuple[str, str]:
        return (tenant_id, user_id)

    def list_tasks(self, tenant_id: str, user_id: str) -> list[ScheduledTask]:
        return list(self._store.get(self._key(tenant_id, user_id), []))

    def add_task(self, task: ScheduledTask) -> ScheduledTask:
        task.next_run_at = compute_next_run(task.cron)
        key = self._key(task.tenant_id, task.user_id)
        self._store.setdefault(key, []).append(task)
        return task

    def get_task(
        self, tenant_id: str, user_id: str, task_id: str
    ) -> ScheduledTask | None:
        for t in self._store.get(self._key(tenant_id, user_id), []):
            if t.id == task_id:
                return t
        return None

    def update_task(
        self, tenant_id: str, user_id: str, task_id: str, **kwargs
    ) -> ScheduledTask | None:
        task = self.get_task(tenant_id, user_id, task_id)
        if not task:
            return None
        for k, v in kwargs.items():
            if hasattr(task, k) and k not in ("id", "user_id", "tenant_id", "created_at"):
                setattr(task, k, v)
        if "cron" in kwargs:
            task.next_run_at = compute_next_run(task.cron)
        return task

    def remove_task(self, tenant_id: str, user_id: str, task_id: str) -> bool:
        key = self._key(tenant_id, user_id)
        tasks = self._store.get(key, [])
        before = len(tasks)
        self._store[key] = [t for t in tasks if t.id != task_id]
        return len(self._store[key]) < before

    def pause_task(self, tenant_id: str, user_id: str, task_id: str) -> bool:
        task = self.get_task(tenant_id, user_id, task_id)
        if not task:
            return False
        task.enabled = False
        return True

    def resume_task(self, tenant_id: str, user_id: str, task_id: str) -> bool:
        task = self.get_task(tenant_id, user_id, task_id)
        if not task:
            return False
        task.enabled = True
        task.next_run_at = compute_next_run(task.cron)
        return True


# ── Fixtures ──


@pytest.fixture()
def fake_scheduler():
    return FakeScheduler()


@pytest.fixture()
def client(fake_scheduler):
    """TestClient with patched auth (USER_A) and scheduler."""
    _clear_all_lru_caches()

    from main import app

    app.dependency_overrides[get_current_user] = lambda: USER_A

    with patch("api.schedule_routes.get_scheduler", return_value=fake_scheduler):
        c = TestClient(app, raise_server_exceptions=False)
        yield c

    app.dependency_overrides.clear()
    _clear_all_lru_caches()


# ═══════════════════════════════════════════════════════════
# 1. List schedules — GET /api/schedules
# ═══════════════════════════════════════════════════════════


class TestListSchedules:
    def test_empty_list(self, client):
        resp = client.get("/api/schedules")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tasks"] == []
        assert data["total"] == 0

    def test_list_with_tasks(self, client, fake_scheduler):
        t1 = _make_task(task_id="t1", name="Task 1")
        t2 = _make_task(task_id="t2", name="Task 2")
        fake_scheduler.add_task(t1)
        fake_scheduler.add_task(t2)

        resp = client.get("/api/schedules")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["tasks"]) == 2
        names = {t["name"] for t in data["tasks"]}
        assert names == {"Task 1", "Task 2"}

    def test_list_returns_dict_format(self, client, fake_scheduler):
        fake_scheduler.add_task(_make_task())
        resp = client.get("/api/schedules")
        task = resp.json()["tasks"][0]
        # Verify all expected fields from ScheduledTask.to_dict()
        for field in ("id", "name", "cron", "message", "user_id", "tenant_id",
                       "business_type", "enabled", "created_at", "next_run_at"):
            assert field in task


# ═══════════════════════════════════════════════════════════
# 2. Create schedule — POST /api/schedules
# ═══════════════════════════════════════════════════════════


class TestCreateSchedule:
    def test_create_valid(self, client):
        payload = {
            "name": "Hourly check",
            "cron": "0 * * * *",
            "message": "Run hourly health check",
        }
        resp = client.post("/api/schedules", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Hourly check"
        assert data["cron"] == "0 * * * *"
        assert data["message"] == "Run hourly health check"
        assert data["user_id"] == USER_A.user_id
        assert data["tenant_id"] == USER_A.tenant_id
        assert data["enabled"] is True
        assert data["next_run_at"] is not None
        assert data["id"]  # non-empty

    def test_create_with_business_type(self, client):
        payload = {
            "name": "Custom type",
            "cron": VALID_CRON,
            "message": "test",
            "business_type": "report_gen",
        }
        resp = client.post("/api/schedules", json=payload)
        assert resp.status_code == 200
        assert resp.json()["business_type"] == "report_gen"

    def test_create_default_business_type(self, client):
        payload = {"name": "t", "cron": VALID_CRON, "message": "m"}
        resp = client.post("/api/schedules", json=payload)
        assert resp.status_code == 200
        assert resp.json()["business_type"] == "scheduled_task"

    def test_create_invalid_cron_returns_400(self, client):
        payload = {"name": "Bad", "cron": INVALID_CRON, "message": "test"}
        resp = client.post("/api/schedules", json=payload)
        assert resp.status_code == 400
        assert "Invalid cron" in resp.json()["detail"]

    def test_create_invalid_cron_partial_garbage(self, client):
        payload = {"name": "Bad", "cron": "60 25 32 13 8", "message": "test"}
        resp = client.post("/api/schedules", json=payload)
        assert resp.status_code == 400

    def test_create_missing_name_returns_422(self, client):
        payload = {"cron": VALID_CRON, "message": "test"}
        resp = client.post("/api/schedules", json=payload)
        assert resp.status_code == 422

    def test_create_missing_cron_returns_422(self, client):
        payload = {"name": "No cron", "message": "test"}
        resp = client.post("/api/schedules", json=payload)
        assert resp.status_code == 422

    def test_create_missing_message_returns_422(self, client):
        payload = {"name": "No msg", "cron": VALID_CRON}
        resp = client.post("/api/schedules", json=payload)
        assert resp.status_code == 422

    def test_create_empty_body_returns_422(self, client):
        resp = client.post("/api/schedules", json={})
        assert resp.status_code == 422

    def test_create_sets_next_run_at(self, client):
        payload = {"name": "t", "cron": VALID_CRON, "message": "m"}
        resp = client.post("/api/schedules", json=payload)
        data = resp.json()
        assert data["next_run_at"] is not None
        assert data["next_run_at"] > time.time() - 10  # should be in the future

    def test_create_generates_unique_id(self, client):
        payload = {"name": "t", "cron": VALID_CRON, "message": "m"}
        resp1 = client.post("/api/schedules", json=payload)
        resp2 = client.post("/api/schedules", json=payload)
        assert resp1.json()["id"] != resp2.json()["id"]


# ═══════════════════════════════════════════════════════════
# 3. Get schedule — GET /api/schedules/{task_id}
# ═══════════════════════════════════════════════════════════


class TestGetSchedule:
    def test_get_existing_task(self, client, fake_scheduler):
        task = _make_task(task_id="get-me")
        fake_scheduler.add_task(task)

        resp = client.get("/api/schedules/get-me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "get-me"
        assert data["name"] == task.name
        assert data["cron"] == task.cron
        assert data["message"] == task.message

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/api/schedules/no-such-task")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_get_returns_all_fields(self, client, fake_scheduler):
        task = _make_task(task_id="full-fields", last_run_status="success")
        task.last_run_at = time.time() - 60
        fake_scheduler.add_task(task)

        resp = client.get("/api/schedules/full-fields")
        data = resp.json()
        assert data["last_run_status"] == "success"
        assert data["last_run_at"] is not None
        assert "enabled" in data


# ═══════════════════════════════════════════════════════════
# 4. Update schedule — PUT /api/schedules/{task_id}
# ═══════════════════════════════════════════════════════════


class TestUpdateSchedule:
    def test_update_name_only(self, client, fake_scheduler):
        fake_scheduler.add_task(_make_task(task_id="upd1"))

        resp = client.put("/api/schedules/upd1", json={"name": "New name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "New name"

    def test_update_message_only(self, client, fake_scheduler):
        fake_scheduler.add_task(_make_task(task_id="upd2"))

        resp = client.put("/api/schedules/upd2", json={"message": "New msg"})
        assert resp.status_code == 200
        assert resp.json()["message"] == "New msg"

    def test_update_cron_recalculates_next_run(self, client, fake_scheduler):
        task = _make_task(task_id="upd3", cron="0 0 * * *")
        fake_scheduler.add_task(task)
        old_next = task.next_run_at

        resp = client.put("/api/schedules/upd3", json={"cron": "0 12 * * *"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["cron"] == "0 12 * * *"
        # next_run_at should have been recalculated
        assert data["next_run_at"] != old_next

    def test_update_invalid_cron_returns_400(self, client, fake_scheduler):
        fake_scheduler.add_task(_make_task(task_id="upd4"))

        resp = client.put("/api/schedules/upd4", json={"cron": INVALID_CRON})
        assert resp.status_code == 400
        assert "Invalid cron" in resp.json()["detail"]

    def test_update_nonexistent_returns_404(self, client):
        resp = client.put("/api/schedules/nonexistent", json={"name": "x"})
        assert resp.status_code == 404

    def test_update_enabled_field(self, client, fake_scheduler):
        fake_scheduler.add_task(_make_task(task_id="upd5"))

        resp = client.put("/api/schedules/upd5", json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_update_business_type(self, client, fake_scheduler):
        fake_scheduler.add_task(_make_task(task_id="upd6"))

        resp = client.put("/api/schedules/upd6", json={"business_type": "nightly_job"})
        assert resp.status_code == 200
        assert resp.json()["business_type"] == "nightly_job"

    def test_update_multiple_fields(self, client, fake_scheduler):
        fake_scheduler.add_task(_make_task(task_id="upd7"))

        resp = client.put(
            "/api/schedules/upd7",
            json={"name": "Multi", "message": "updated msg", "business_type": "multi"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Multi"
        assert data["message"] == "updated msg"
        assert data["business_type"] == "multi"

    def test_update_empty_body_is_noop(self, client, fake_scheduler):
        task = _make_task(task_id="upd8")
        fake_scheduler.add_task(task)

        resp = client.put("/api/schedules/upd8", json={})
        assert resp.status_code == 200
        # Original values preserved
        assert resp.json()["name"] == task.name


# ═══════════════════════════════════════════════════════════
# 5. Delete schedule — DELETE /api/schedules/{task_id}
# ═══════════════════════════════════════════════════════════


class TestDeleteSchedule:
    def test_delete_existing(self, client, fake_scheduler):
        fake_scheduler.add_task(_make_task(task_id="del1"))

        resp = client.delete("/api/schedules/del1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert data["task_id"] == "del1"

    def test_delete_removes_from_list(self, client, fake_scheduler):
        fake_scheduler.add_task(_make_task(task_id="del2"))

        client.delete("/api/schedules/del2")
        resp = client.get("/api/schedules")
        assert resp.json()["total"] == 0

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/schedules/no-such-task")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_delete_idempotent_second_call_404(self, client, fake_scheduler):
        fake_scheduler.add_task(_make_task(task_id="del3"))

        resp1 = client.delete("/api/schedules/del3")
        assert resp1.status_code == 200
        resp2 = client.delete("/api/schedules/del3")
        assert resp2.status_code == 404


# ═══════════════════════════════════════════════════════════
# 6. Pause schedule — POST /api/schedules/{task_id}/pause
# ═══════════════════════════════════════════════════════════


class TestPauseSchedule:
    def test_pause_existing(self, client, fake_scheduler):
        fake_scheduler.add_task(_make_task(task_id="p1"))

        resp = client.post("/api/schedules/p1/pause")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "paused"
        assert data["task_id"] == "p1"

    def test_pause_sets_enabled_false(self, client, fake_scheduler):
        fake_scheduler.add_task(_make_task(task_id="p2"))

        client.post("/api/schedules/p2/pause")
        task = fake_scheduler.get_task("tenant-1", "UA01", "p2")
        assert task.enabled is False

    def test_pause_nonexistent_returns_404(self, client):
        resp = client.post("/api/schedules/no-task/pause")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_pause_already_paused(self, client, fake_scheduler):
        task = _make_task(task_id="p3", enabled=False)
        fake_scheduler.add_task(task)

        # Pausing an already-paused task should still succeed
        resp = client.post("/api/schedules/p3/pause")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════
# 7. Resume schedule — POST /api/schedules/{task_id}/resume
# ═══════════════════════════════════════════════════════════


class TestResumeSchedule:
    def test_resume_existing(self, client, fake_scheduler):
        task = _make_task(task_id="r1", enabled=False)
        fake_scheduler.add_task(task)

        resp = client.post("/api/schedules/r1/resume")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resumed"
        assert data["task_id"] == "r1"

    def test_resume_sets_enabled_true(self, client, fake_scheduler):
        task = _make_task(task_id="r2", enabled=False)
        fake_scheduler.add_task(task)

        client.post("/api/schedules/r2/resume")
        updated = fake_scheduler.get_task("tenant-1", "UA01", "r2")
        assert updated.enabled is True

    def test_resume_recalculates_next_run(self, client, fake_scheduler):
        task = _make_task(task_id="r3", enabled=False)
        task.next_run_at = None
        fake_scheduler.add_task(task)

        client.post("/api/schedules/r3/resume")
        updated = fake_scheduler.get_task("tenant-1", "UA01", "r3")
        assert updated.next_run_at is not None
        assert updated.next_run_at > time.time() - 10

    def test_resume_nonexistent_returns_404(self, client):
        resp = client.post("/api/schedules/no-task/resume")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════
# 8. Cross-user isolation
# ═══════════════════════════════════════════════════════════


class TestCrossUserIsolation:
    """User A cannot see or modify User B's tasks.

    These tests create inline clients that share a single FakeScheduler
    to avoid fixture conflicts with app.dependency_overrides.
    """

    @staticmethod
    def _make_clients(scheduler):
        """Build two TestClients (user A, user B) sharing the same scheduler."""
        _clear_all_lru_caches()
        from main import app

        patcher = patch("api.schedule_routes.get_scheduler", return_value=scheduler)
        patcher.start()

        app.dependency_overrides[get_current_user] = lambda: USER_A
        client_a = TestClient(app, raise_server_exceptions=False)

        app.dependency_overrides[get_current_user] = lambda: USER_B
        client_b = TestClient(app, raise_server_exceptions=False)

        return app, patcher, client_a, client_b

    @staticmethod
    def _cleanup(app, patcher):
        patcher.stop()
        app.dependency_overrides.clear()
        _clear_all_lru_caches()

    def test_user_b_cannot_list_user_a_tasks(self):
        scheduler = FakeScheduler()
        scheduler.add_task(_make_task(task_id="iso1", user_id="UA01", tenant_id="tenant-1"))

        app, patcher, client_a, client_b = self._make_clients(scheduler)
        try:
            # Switch to user A
            app.dependency_overrides[get_current_user] = lambda: USER_A
            resp_a = client_a.get("/api/schedules")
            assert resp_a.json()["total"] == 1

            # Switch to user B
            app.dependency_overrides[get_current_user] = lambda: USER_B
            resp_b = client_b.get("/api/schedules")
            assert resp_b.json()["total"] == 0
        finally:
            self._cleanup(app, patcher)

    def test_user_b_cannot_get_user_a_task(self):
        scheduler = FakeScheduler()
        scheduler.add_task(_make_task(task_id="iso2", user_id="UA01", tenant_id="tenant-1"))

        app, patcher, _, client_b = self._make_clients(scheduler)
        try:
            resp = client_b.get("/api/schedules/iso2")
            assert resp.status_code == 404
        finally:
            self._cleanup(app, patcher)

    def test_user_b_cannot_delete_user_a_task(self):
        scheduler = FakeScheduler()
        scheduler.add_task(_make_task(task_id="iso3", user_id="UA01", tenant_id="tenant-1"))

        app, patcher, _, client_b = self._make_clients(scheduler)
        try:
            resp = client_b.delete("/api/schedules/iso3")
            assert resp.status_code == 404
        finally:
            self._cleanup(app, patcher)

    def test_user_b_cannot_pause_user_a_task(self):
        scheduler = FakeScheduler()
        scheduler.add_task(_make_task(task_id="iso4", user_id="UA01", tenant_id="tenant-1"))

        app, patcher, _, client_b = self._make_clients(scheduler)
        try:
            resp = client_b.post("/api/schedules/iso4/pause")
            assert resp.status_code == 404
        finally:
            self._cleanup(app, patcher)

    def test_user_b_cannot_resume_user_a_task(self):
        scheduler = FakeScheduler()
        task = _make_task(task_id="iso5", user_id="UA01", tenant_id="tenant-1", enabled=False)
        scheduler.add_task(task)

        app, patcher, _, client_b = self._make_clients(scheduler)
        try:
            resp = client_b.post("/api/schedules/iso5/resume")
            assert resp.status_code == 404
        finally:
            self._cleanup(app, patcher)

    def test_user_b_cannot_update_user_a_task(self):
        scheduler = FakeScheduler()
        scheduler.add_task(_make_task(task_id="iso6", user_id="UA01", tenant_id="tenant-1"))

        app, patcher, _, client_b = self._make_clients(scheduler)
        try:
            resp = client_b.put("/api/schedules/iso6", json={"name": "Hacked"})
            assert resp.status_code == 404
        finally:
            self._cleanup(app, patcher)

    def test_user_b_creates_own_task_separate(self):
        scheduler = FakeScheduler()
        scheduler.add_task(_make_task(task_id="iso7a", user_id="UA01", tenant_id="tenant-1"))

        app, patcher, client_a, client_b = self._make_clients(scheduler)
        try:
            # User B creates a task via the API
            payload = {"name": "B's task", "cron": VALID_CRON, "message": "B's msg"}
            resp = client_b.post("/api/schedules", json=payload)
            assert resp.status_code == 200
            assert resp.json()["user_id"] == USER_B.user_id

            # User A still only sees their own
            app.dependency_overrides[get_current_user] = lambda: USER_A
            resp_a = client_a.get("/api/schedules")
            assert resp_a.json()["total"] == 1

            # User B only sees theirs
            app.dependency_overrides[get_current_user] = lambda: USER_B
            resp_b = client_b.get("/api/schedules")
            assert resp_b.json()["total"] == 1
        finally:
            self._cleanup(app, patcher)


# ═══════════════════════════════════════════════════════════
# 9. Auth dependency verification
# ═══════════════════════════════════════════════════════════


class TestAuthRequired:
    """Verify all schedule endpoints use the auth dependency."""

    def test_list_uses_auth_user_identity(self, fake_scheduler):
        """Create tasks for two users; auth determines which are returned."""
        _clear_all_lru_caches()
        from main import app

        fake_scheduler.add_task(_make_task(task_id="auth1", user_id="UA01", tenant_id="tenant-1"))
        fake_scheduler.add_task(_make_task(task_id="auth2", user_id="UX99", tenant_id="tenant-1"))

        # Authenticate as UA01
        app.dependency_overrides[get_current_user] = lambda: USER_A

        with patch("api.schedule_routes.get_scheduler", return_value=fake_scheduler):
            c = TestClient(app, raise_server_exceptions=False)
            resp = c.get("/api/schedules")
            assert resp.status_code == 200
            assert resp.json()["total"] == 1
            assert resp.json()["tasks"][0]["id"] == "auth1"

        app.dependency_overrides.clear()
        _clear_all_lru_caches()

    def test_create_assigns_authenticated_user(self, fake_scheduler):
        """Created task gets the authenticated user's identity, not a random one."""
        _clear_all_lru_caches()
        from main import app

        custom_user = AuthUser(tenant_id="custom-t", user_id="custom-u")
        app.dependency_overrides[get_current_user] = lambda: custom_user

        with patch("api.schedule_routes.get_scheduler", return_value=fake_scheduler):
            c = TestClient(app, raise_server_exceptions=False)
            payload = {"name": "t", "cron": VALID_CRON, "message": "m"}
            resp = c.post("/api/schedules", json=payload)
            assert resp.status_code == 200
            data = resp.json()
            assert data["tenant_id"] == "custom-t"
            assert data["user_id"] == "custom-u"

        app.dependency_overrides.clear()
        _clear_all_lru_caches()

    def test_all_endpoints_reject_without_auth_override(self):
        """When auth is enabled and no token provided, endpoints should reject."""
        _clear_all_lru_caches()
        from main import app

        # Simulate auth_enabled by making get_current_user raise 401
        def require_auth():
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Unauthorized")

        app.dependency_overrides[get_current_user] = require_auth

        c = TestClient(app, raise_server_exceptions=False)

        endpoints = [
            ("GET", "/api/schedules"),
            ("POST", "/api/schedules"),
            ("GET", "/api/schedules/any-id"),
            ("PUT", "/api/schedules/any-id"),
            ("DELETE", "/api/schedules/any-id"),
            ("POST", "/api/schedules/any-id/pause"),
            ("POST", "/api/schedules/any-id/resume"),
        ]

        for method, path in endpoints:
            if method == "GET":
                resp = c.get(path)
            elif method == "POST":
                resp = c.post(path, json={"name": "t", "cron": "* * * * *", "message": "m"})
            elif method == "PUT":
                resp = c.put(path, json={"name": "t"})
            elif method == "DELETE":
                resp = c.delete(path)
            else:
                raise ValueError(f"Unhandled method: {method}")

            assert resp.status_code == 401, f"{method} {path} should require auth, got {resp.status_code}"

        app.dependency_overrides.clear()
        _clear_all_lru_caches()


# ═══════════════════════════════════════════════════════════
# 10. Edge cases
# ═══════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_create_five_field_cron(self, client):
        """Standard 5-field cron expression."""
        payload = {"name": "t", "cron": "30 2 * * 0", "message": "weekly"}
        resp = client.post("/api/schedules", json=payload)
        assert resp.status_code == 200

    def test_create_cron_with_ranges(self, client):
        payload = {"name": "t", "cron": "0 9-17 * * 1-5", "message": "work hours"}
        resp = client.post("/api/schedules", json=payload)
        assert resp.status_code == 200

    def test_create_cron_with_steps(self, client):
        payload = {"name": "t", "cron": "*/10 * * * *", "message": "every 10 min"}
        resp = client.post("/api/schedules", json=payload)
        assert resp.status_code == 200

    def test_create_cron_with_lists(self, client):
        payload = {"name": "t", "cron": "0 8,12,18 * * *", "message": "three times"}
        resp = client.post("/api/schedules", json=payload)
        assert resp.status_code == 200

    def test_update_with_valid_new_cron(self, client, fake_scheduler):
        fake_scheduler.add_task(_make_task(task_id="edge1"))
        resp = client.put("/api/schedules/edge1", json={"cron": VALID_CRON_2})
        assert resp.status_code == 200
        assert resp.json()["cron"] == VALID_CRON_2

    def test_create_and_get_roundtrip(self, client):
        """Created task can be retrieved and has matching fields."""
        payload = {
            "name": "Roundtrip",
            "cron": "0 6 * * *",
            "message": "Morning task",
            "business_type": "custom_type",
        }
        create_resp = client.post("/api/schedules", json=payload)
        assert create_resp.status_code == 200
        task_id = create_resp.json()["id"]

        get_resp = client.get(f"/api/schedules/{task_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["name"] == "Roundtrip"
        assert data["cron"] == "0 6 * * *"
        assert data["message"] == "Morning task"
        assert data["business_type"] == "custom_type"

    def test_pause_then_resume_roundtrip(self, client, fake_scheduler):
        fake_scheduler.add_task(_make_task(task_id="pr1"))

        # Pause
        resp = client.post("/api/schedules/pr1/pause")
        assert resp.status_code == 200
        task = fake_scheduler.get_task("tenant-1", "UA01", "pr1")
        assert task.enabled is False

        # Resume
        resp = client.post("/api/schedules/pr1/resume")
        assert resp.status_code == 200
        task = fake_scheduler.get_task("tenant-1", "UA01", "pr1")
        assert task.enabled is True
        assert task.next_run_at is not None
