"""Tests for API usage routes — admin + self-service (A10)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

import dependencies
from services.database import DatabaseService
from services.usage_service import UsageService


def _clear_all_lru_caches():
    for name in dir(dependencies):
        obj = getattr(dependencies, name)
        if hasattr(obj, "cache_clear"):
            obj.cache_clear()


@pytest.fixture(autouse=True)
def client(tmp_path):
    """TestClient with patched dependencies."""
    _clear_all_lru_caches()

    db_path = str(tmp_path / "test.db")
    db = DatabaseService(db_path=db_path)
    db.ensure_default_tenant_and_admin(tenant_id="default", admin_user_id="U001")
    usage_svc = UsageService(db_path=db_path)

    # Pre-populate some usage data
    usage_svc.record_pipeline(
        tenant_id="default", user_id="U001", session_id="S1",
        business_type="general_chat",
        prompt_tokens=100, completion_tokens=50, total_tokens=150,
        tool_call_count=3, iterations=2, duration_ms=1500.0,
        status="success", model="test-model",
        tool_names=["arithmetic", "read_reference"],
    )
    usage_svc.record_pipeline(
        tenant_id="default", user_id="U002", session_id="S2",
        business_type="general_chat",
        prompt_tokens=80, completion_tokens=40, total_tokens=120,
        tool_call_count=1, iterations=1, duration_ms=800.0,
        status="failed", model="test-model",
        tool_names=["read_reference"],
    )

    from main import app

    with (
        patch.object(dependencies, "get_database", return_value=db),
        patch.object(dependencies, "get_usage_service", return_value=usage_svc),
        patch.object(dependencies, "get_plugin_registry", return_value=MagicMock(list_plugins=lambda: [])),
    ):
        c = TestClient(app, raise_server_exceptions=False)
        c._usage_svc = usage_svc
        yield c

    _clear_all_lru_caches()
    app.dependency_overrides.clear()


# ═══════════════════════════════════════
# Admin Usage Routes — /api/admin/usage/*
# ═══════════════════════════════════════


class TestAdminUsageTenantSummary:
    def test_get_tenant_usage(self, client):
        resp = client.get("/api/admin/usage/tenant/default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 2
        assert data["total_tokens"] == 270
        assert data["success_count"] == 1
        assert data["failed_count"] == 1

    def test_get_tenant_usage_with_dates(self, client):
        resp = client.get("/api/admin/usage/tenant/default?start_date=2099-01-01")
        assert resp.status_code == 200
        assert resp.json()["total_requests"] == 0


class TestAdminUsageTenantDaily:
    def test_daily(self, client):
        resp = client.get("/api/admin/usage/tenant/default/daily")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["total_requests"] == 2


class TestAdminUsageUserRanking:
    def test_ranking(self, client):
        resp = client.get("/api/admin/usage/tenant/default/users")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # U001 has more tokens
        assert data[0]["user_id"] == "U001"

    def test_limit(self, client):
        resp = client.get("/api/admin/usage/tenant/default/users?limit=1")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestAdminUsageSingleUser:
    def test_user_usage(self, client):
        resp = client.get("/api/admin/usage/tenant/default/users/U001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 1
        assert data["total_tokens"] == 150


class TestAdminUsageTools:
    def test_tool_stats(self, client):
        resp = client.get("/api/admin/usage/tenant/default/tools")
        assert resp.status_code == 200
        data = resp.json()
        name_to_count = {d["tool_name"]: d["call_count"] for d in data}
        assert name_to_count["read_reference"] == 2
        assert name_to_count["arithmetic"] == 1


class TestAdminUsageEvents:
    def test_events(self, client):
        resp = client.get("/api/admin/usage/tenant/default/events")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_events_filter_user(self, client):
        resp = client.get("/api/admin/usage/tenant/default/events?user_id=U002")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestAdminUsageStorage:
    def test_storage(self, client):
        resp = client.get("/api/admin/usage/tenant/default/storage")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_bytes" in data
        assert "sessions_bytes" in data


class TestAdminUsageAuth:
    def test_admin_required_when_auth_enabled(self, client):
        """Non-admin gets 403 when auth is enabled."""
        from core.auth import AuthUser, get_current_user

        non_admin = AuthUser(tenant_id="default", user_id="U999", roles=[])

        from main import app
        app.dependency_overrides[get_current_user] = lambda: non_admin

        with patch("config.settings") as mock_settings:
            mock_settings.auth_enabled = True
            resp = client.get("/api/admin/usage/tenant/default")
            assert resp.status_code == 403

        app.dependency_overrides.clear()


# ═══════════════════════════════════════
# Self-service Usage Routes — /api/usage/*
# ═══════════════════════════════════════


class TestMyUsage:
    def test_my_summary(self, client):
        resp = client.get("/api/usage/me")
        assert resp.status_code == 200
        data = resp.json()
        # Default user is U001
        assert data["total_requests"] == 1
        assert data["total_tokens"] == 150

    def test_my_daily(self, client):
        resp = client.get("/api/usage/me/daily")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

    def test_my_events(self, client):
        resp = client.get("/api/usage/me/events")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["user_id"] == "U001"

    def test_only_own_data(self, client):
        """Self-service endpoints only return the authenticated user's data."""
        resp = client.get("/api/usage/me/events")
        data = resp.json()
        for event in data:
            assert event["user_id"] == "U001"
