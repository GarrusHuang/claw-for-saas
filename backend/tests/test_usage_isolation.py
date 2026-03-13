"""
Tests for UsageService — cross-tenant isolation, error handling, JSON corruption,
API parameter validation, and concurrent UPSERT stress.

Coverage gaps addressed:
  1. Cross-Tenant Data Isolation (HIGH PRIORITY)
  2. DB Connection/Error Handling
  3. JSON Corruption Recovery
  4. API Parameter Validation
  5. Concurrent UPSERT Stress
"""
import asyncio
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.database import DatabaseService
from services.usage_service import UsageService


# ── Shared Fixtures ──


@pytest.fixture
def svc(tmp_path):
    """UsageService with a clean temp DB and a default tenant."""
    db_path = str(tmp_path / "test.db")
    db = DatabaseService(db_path=db_path)
    db.create_tenant("T1", "Test Tenant")
    return UsageService(db_path=db_path)


@pytest.fixture
def two_tenant_svc(tmp_path):
    """UsageService with data for Tenant A and Tenant B — isolation tests."""
    db_path = str(tmp_path / "test.db")
    db = DatabaseService(db_path=db_path)
    db.create_tenant("TA", "Tenant A")
    db.create_tenant("TB", "Tenant B")
    svc = UsageService(db_path=db_path)

    # --- Tenant A: 3 events, 2 users ---
    svc.record_pipeline(
        tenant_id="TA", user_id="UA1", session_id="SA1",
        business_type="general_chat",
        prompt_tokens=100, completion_tokens=50, total_tokens=150,
        tool_call_count=3, iterations=2, duration_ms=1500.0,
        status="success", model="test-model",
        tool_names=["read_reference", "arithmetic"],
    )
    svc.record_pipeline(
        tenant_id="TA", user_id="UA1", session_id="SA2",
        business_type="reimbursement_create",
        prompt_tokens=200, completion_tokens=100, total_tokens=300,
        tool_call_count=5, iterations=3, duration_ms=2500.0,
        status="success", model="test-model",
        tool_names=["arithmetic", "propose_plan"],
    )
    svc.record_pipeline(
        tenant_id="TA", user_id="UA2", session_id="SA3",
        business_type="general_chat",
        prompt_tokens=80, completion_tokens=40, total_tokens=120,
        tool_call_count=1, iterations=1, duration_ms=800.0,
        status="failed", model="test-model",
        tool_names=["read_reference"],
    )

    # --- Tenant B: 2 events, 1 user ---
    svc.record_pipeline(
        tenant_id="TB", user_id="UB1", session_id="SB1",
        business_type="general_chat",
        prompt_tokens=500, completion_tokens=250, total_tokens=750,
        tool_call_count=10, iterations=5, duration_ms=5000.0,
        status="success", model="gpt-4",
        tool_names=["open_url", "page_screenshot"],
    )
    svc.record_pipeline(
        tenant_id="TB", user_id="UB1", session_id="SB2",
        business_type="general_chat",
        prompt_tokens=300, completion_tokens=150, total_tokens=450,
        tool_call_count=7, iterations=4, duration_ms=3500.0,
        status="success", model="gpt-4",
        tool_names=["open_url"],
    )

    return svc


# ═══════════════════════════════════════════════════════
# 1. Cross-Tenant Data Isolation (HIGH PRIORITY)
# ═══════════════════════════════════════════════════════


class TestCrossTenantIsolation:
    """Every query API must return ONLY the requested tenant's data."""

    # -- get_tenant_usage --

    def test_tenant_usage_returns_only_own_data(self, two_tenant_svc):
        """TA usage must reflect only TA's 3 events."""
        result = two_tenant_svc.get_tenant_usage("TA")
        assert result["total_requests"] == 3
        assert result["total_tokens"] == 570  # 150 + 300 + 120
        assert result["total_tool_calls"] == 9  # 3 + 5 + 1
        assert result["success_count"] == 2
        assert result["failed_count"] == 1

    def test_tenant_usage_b_excludes_a_data(self, two_tenant_svc):
        """TB usage must reflect only TB's 2 events, not TA's."""
        result = two_tenant_svc.get_tenant_usage("TB")
        assert result["total_requests"] == 2
        assert result["total_tokens"] == 1200  # 750 + 450
        assert result["total_tool_calls"] == 17  # 10 + 7
        assert result["success_count"] == 2
        assert result["failed_count"] == 0

    def test_tenant_usage_nonexistent_returns_zero(self, two_tenant_svc):
        """Unknown tenant must return zeros, not crash or leak data."""
        result = two_tenant_svc.get_tenant_usage("TX_NONEXIST")
        assert result["total_requests"] == 0
        assert result["total_tokens"] == 0

    # -- get_tenant_daily --

    def test_tenant_daily_returns_only_own_dates(self, two_tenant_svc):
        """TA daily must show TA's aggregated daily row only."""
        daily_a = two_tenant_svc.get_tenant_daily("TA")
        daily_b = two_tenant_svc.get_tenant_daily("TB")

        assert len(daily_a) == 1
        assert daily_a[0]["total_requests"] == 3
        assert daily_a[0]["total_tokens"] == 570

        assert len(daily_b) == 1
        assert daily_b[0]["total_requests"] == 2
        assert daily_b[0]["total_tokens"] == 1200

    def test_tenant_daily_no_cross_leak(self, two_tenant_svc):
        """Sum of TA daily tokens must not include TB data."""
        daily_a = two_tenant_svc.get_tenant_daily("TA")
        total_tokens_a = sum(d["total_tokens"] for d in daily_a)
        assert total_tokens_a == 570  # strictly TA

    # -- get_tenant_user_ranking --

    def test_user_ranking_returns_only_own_users(self, two_tenant_svc):
        """TA ranking must contain only UA1, UA2 — not UB1."""
        ranking_a = two_tenant_svc.get_tenant_user_ranking("TA")
        user_ids_a = {r["user_id"] for r in ranking_a}
        assert user_ids_a == {"UA1", "UA2"}
        assert "UB1" not in user_ids_a

    def test_user_ranking_b_excludes_a_users(self, two_tenant_svc):
        """TB ranking must contain only UB1."""
        ranking_b = two_tenant_svc.get_tenant_user_ranking("TB")
        user_ids_b = {r["user_id"] for r in ranking_b}
        assert user_ids_b == {"UB1"}
        assert "UA1" not in user_ids_b
        assert "UA2" not in user_ids_b

    def test_user_ranking_correct_ordering(self, two_tenant_svc):
        """TA: UA1 (450 tokens) > UA2 (120 tokens)."""
        ranking = two_tenant_svc.get_tenant_user_ranking("TA")
        assert ranking[0]["user_id"] == "UA1"
        assert ranking[0]["total_tokens"] == 450
        assert ranking[1]["user_id"] == "UA2"
        assert ranking[1]["total_tokens"] == 120

    # -- get_user_usage --

    def test_user_usage_returns_only_own_tenant_data(self, two_tenant_svc):
        """UA1 in TA must see only TA data (2 events, 450 tokens)."""
        result = two_tenant_svc.get_user_usage("TA", "UA1")
        assert result["total_requests"] == 2
        assert result["total_tokens"] == 450

    def test_user_usage_cross_tenant_query_returns_empty(self, two_tenant_svc):
        """Querying TA for UB1 (a TB user) must return zero."""
        result = two_tenant_svc.get_user_usage("TA", "UB1")
        assert result["total_requests"] == 0
        assert result["total_tokens"] == 0

    def test_user_usage_b_correct(self, two_tenant_svc):
        """UB1 in TB must see only TB data (2 events, 1200 tokens)."""
        result = two_tenant_svc.get_user_usage("TB", "UB1")
        assert result["total_requests"] == 2
        assert result["total_tokens"] == 1200

    # -- get_recent_events --

    def test_recent_events_returns_only_own_events(self, two_tenant_svc):
        """TA events must not include any TB event."""
        events_a = two_tenant_svc.get_recent_events("TA")
        assert len(events_a) == 3
        for e in events_a:
            assert e["tenant_id"] == "TA"

    def test_recent_events_b_excludes_a(self, two_tenant_svc):
        """TB events must not include any TA event."""
        events_b = two_tenant_svc.get_recent_events("TB")
        assert len(events_b) == 2
        for e in events_b:
            assert e["tenant_id"] == "TB"

    def test_recent_events_nonexistent_tenant_empty(self, two_tenant_svc):
        """Non-existent tenant must return empty list."""
        events = two_tenant_svc.get_recent_events("TX_GHOST")
        assert events == []

    # -- get_tool_usage_stats --

    def test_tool_stats_returns_only_own_tools(self, two_tenant_svc):
        """TA tools: read_reference(2), arithmetic(2), propose_plan(1). No open_url."""
        stats_a = two_tenant_svc.get_tool_usage_stats("TA")
        names_a = {s["tool_name"] for s in stats_a}
        assert names_a == {"read_reference", "arithmetic", "propose_plan"}
        assert "open_url" not in names_a
        assert "page_screenshot" not in names_a

    def test_tool_stats_b_excludes_a_tools(self, two_tenant_svc):
        """TB tools: open_url(2), page_screenshot(1). No arithmetic."""
        stats_b = two_tenant_svc.get_tool_usage_stats("TB")
        names_b = {s["tool_name"] for s in stats_b}
        assert names_b == {"open_url", "page_screenshot"}
        assert "arithmetic" not in names_b

    def test_tool_stats_counts_correct_per_tenant(self, two_tenant_svc):
        """Verify exact counts are scoped to the tenant."""
        stats_a = {s["tool_name"]: s["call_count"]
                    for s in two_tenant_svc.get_tool_usage_stats("TA")}
        assert stats_a["arithmetic"] == 2
        assert stats_a["read_reference"] == 2
        assert stats_a["propose_plan"] == 1

        stats_b = {s["tool_name"]: s["call_count"]
                    for s in two_tenant_svc.get_tool_usage_stats("TB")}
        assert stats_b["open_url"] == 2
        assert stats_b["page_screenshot"] == 1

    # -- get_storage_usage --

    def test_storage_usage_scoped_to_tenant(self, tmp_path):
        """Storage scan must use tenant-specific paths."""
        db_path = str(tmp_path / "test.db")
        db = DatabaseService(db_path=db_path)
        db.create_tenant("TA", "A")
        db.create_tenant("TB", "B")
        svc = UsageService(db_path=db_path)

        # Create files for TA only
        ta_sessions = tmp_path / "sessions" / "TA"
        ta_sessions.mkdir(parents=True)
        (ta_sessions / "s1.jsonl").write_text("x" * 200)

        ta_memory = tmp_path / "memory" / "tenant" / "TA"
        ta_memory.mkdir(parents=True)
        (ta_memory / "notes.md").write_text("y" * 100)

        # Create files for TB only
        tb_sessions = tmp_path / "sessions" / "TB"
        tb_sessions.mkdir(parents=True)
        (tb_sessions / "s2.jsonl").write_text("z" * 500)

        # TA storage must not include TB files
        storage_a = svc.get_storage_usage("TA")
        assert storage_a["sessions_bytes"] == 200
        assert storage_a["memory_bytes"] == 100
        assert storage_a["total_bytes"] == 300

        # TB storage must not include TA files
        storage_b = svc.get_storage_usage("TB")
        assert storage_b["sessions_bytes"] == 500
        assert storage_b["memory_bytes"] == 0
        assert storage_b["total_bytes"] == 500

    def test_storage_nonexistent_tenant_zero(self, svc):
        """Non-existent tenant directories return 0 bytes."""
        storage = svc.get_storage_usage("TX_NODIR")
        assert storage["total_bytes"] == 0


# ═══════════════════════════════════════════════════════
# 2. DB Connection/Error Handling
# ═══════════════════════════════════════════════════════


class TestDBConnectionErrors:
    """Verify the service handles database connection failures."""

    def test_connect_raises_operational_error(self, tmp_path):
        """Mock sqlite3.connect to raise OperationalError."""
        db_path = str(tmp_path / "test.db")
        DatabaseService(db_path=db_path)
        svc = UsageService(db_path=db_path)

        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("disk I/O error")):
            with pytest.raises(sqlite3.OperationalError):
                svc.record_pipeline(
                    tenant_id="T1", user_id="U1", session_id="S1",
                    total_tokens=100,
                )

    def test_connect_error_on_read(self, tmp_path):
        """Read queries also fail gracefully when connect raises."""
        db_path = str(tmp_path / "test.db")
        DatabaseService(db_path=db_path)
        svc = UsageService(db_path=db_path)

        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("locked")):
            with pytest.raises(sqlite3.OperationalError):
                svc.get_tenant_usage("T1")

    def test_directory_as_db_path(self, tmp_path):
        """If db_path is a directory (not a file), sqlite3 should error."""
        # Create the directory at the path where the DB file would go
        bad_path = str(tmp_path / "is_a_dir.db")
        os.makedirs(bad_path, exist_ok=True)

        svc = UsageService(db_path=bad_path)
        # sqlite3.connect on a directory varies by platform; should raise
        with pytest.raises((sqlite3.OperationalError, OSError, sqlite3.DatabaseError)):
            svc._get_conn()

    def test_readonly_filesystem_write_fails(self, tmp_path):
        """When the DB cannot be written to, record_pipeline should raise."""
        db_path = str(tmp_path / "test.db")
        DatabaseService(db_path=db_path)
        svc = UsageService(db_path=db_path)

        # Wrap the real connection with a proxy that intercepts INSERT
        orig_get_conn = svc._get_conn

        class ReadonlyConnProxy:
            """Proxy that raises on INSERT but passes other calls through."""
            def __init__(self, real_conn):
                self._conn = real_conn

            def execute(self, sql, *args, **kwargs):
                if sql.strip().startswith("INSERT"):
                    raise sqlite3.OperationalError(
                        "attempt to write a readonly database"
                    )
                return self._conn.execute(sql, *args, **kwargs)

            def commit(self):
                return self._conn.commit()

            def close(self):
                return self._conn.close()

            def __getattr__(self, name):
                return getattr(self._conn, name)

        def _readonly_conn():
            return ReadonlyConnProxy(orig_get_conn())

        with patch.object(svc, "_get_conn", side_effect=_readonly_conn):
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                svc.record_pipeline(
                    tenant_id="T1", user_id="U1", session_id="S1",
                    total_tokens=100,
                )


# ═══════════════════════════════════════════════════════
# 3. JSON Corruption Recovery
# ═══════════════════════════════════════════════════════


class TestJsonCorruptionRecovery:
    """Test behavior when tool_names column contains invalid JSON."""

    def _insert_corrupt_row(self, db_path: str, tenant_id: str, bad_json: str,
                            session_id: str = "SCORRUPT"):
        """Directly INSERT a row with corrupt JSON in tool_names.

        FK checks are disabled so we can insert without a matching tenant row.
        """
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            """INSERT INTO usage_events
               (tenant_id, user_id, session_id, business_type,
                prompt_tokens, completion_tokens, total_tokens,
                tool_call_count, iterations, duration_ms,
                status, model, tool_names, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tenant_id, "U1", session_id, "general_chat",
             10, 5, 15, 1, 1, 100.0,
             "success", "test", bad_json, time.time()),
        )
        conn.commit()
        conn.close()

    def test_get_recent_events_with_invalid_json(self, tmp_path):
        """get_recent_events gracefully handles invalid JSON in tool_names."""
        db_path = str(tmp_path / "test.db")
        db = DatabaseService(db_path=db_path)
        db.create_tenant("T1", "Test")
        svc = UsageService(db_path=db_path)

        # Insert a valid row first
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S_OK",
            tool_names=["arithmetic"],
        )

        # Insert a corrupt row directly (bypasses FK)
        self._insert_corrupt_row(db_path, "T1", "NOT_VALID_JSON{{{")

        # After fix: corrupt JSON falls back to empty list, no crash
        events = svc.get_recent_events("T1")
        assert len(events) == 2
        tool_names_lists = [e["tool_names"] for e in events]
        assert [] in tool_names_lists  # corrupt row → []
        assert ["arithmetic"] in tool_names_lists  # valid row preserved

    def test_get_tool_usage_stats_with_invalid_json(self, tmp_path):
        """get_tool_usage_stats gracefully handles invalid JSON in tool_names."""
        db_path = str(tmp_path / "test.db")
        db = DatabaseService(db_path=db_path)
        db.create_tenant("T1", "Test")
        svc = UsageService(db_path=db_path)

        # Insert a valid row
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S_OK",
            tool_names=["arithmetic"],
        )

        # Insert a corrupt row (bypasses FK)
        self._insert_corrupt_row(db_path, "T1", "{broken", session_id="SCORRUPT2")

        # After fix: corrupt JSON skipped, valid tool stats preserved
        stats = svc.get_tool_usage_stats("T1")
        assert len(stats) == 1
        assert stats[0]["tool_name"] == "arithmetic"
        assert stats[0]["call_count"] == 1

    def test_get_recent_events_with_null_string(self, tmp_path):
        """tool_names = 'null' — JSON null falls back to empty list."""
        db_path = str(tmp_path / "test.db")
        db = DatabaseService(db_path=db_path)
        db.create_tenant("T1", "Test")
        svc = UsageService(db_path=db_path)

        self._insert_corrupt_row(db_path, "T1", "null")

        # After fix: json.loads("null") → None → not a list → falls back to []
        events = svc.get_recent_events("T1")
        assert len(events) == 1
        assert events[0]["tool_names"] == []

    def test_get_tool_usage_stats_with_null_string(self, tmp_path):
        """'null' JSON in tool_names: gracefully treated as empty list."""
        db_path = str(tmp_path / "test.db")
        db = DatabaseService(db_path=db_path)
        db.create_tenant("T1", "Test")
        svc = UsageService(db_path=db_path)

        self._insert_corrupt_row(db_path, "T1", "null")

        # After fix: None from json.loads("null") → falls back to [] → no tools counted
        stats = svc.get_tool_usage_stats("T1")
        assert stats == []

    def test_get_tool_usage_stats_with_string_instead_of_list(self, tmp_path):
        """tool_names = '"just_a_string"' — not a list, falls back to empty."""
        db_path = str(tmp_path / "test.db")
        db = DatabaseService(db_path=db_path)
        db.create_tenant("T1", "Test")
        svc = UsageService(db_path=db_path)

        self._insert_corrupt_row(db_path, "T1", '"hello"')

        # After fix: str is not a list → falls back to [] → no tools counted
        stats = svc.get_tool_usage_stats("T1")
        assert stats == []


# ═══════════════════════════════════════════════════════
# 4. API Parameter Validation
# ═══════════════════════════════════════════════════════


def _clear_all_lru_caches():
    import dependencies
    for name in dir(dependencies):
        obj = getattr(dependencies, name)
        if hasattr(obj, "cache_clear"):
            obj.cache_clear()


@pytest.fixture
def api_client(tmp_path):
    """TestClient wired with real DB + UsageService for parameter validation."""
    import dependencies
    _clear_all_lru_caches()

    db_path = str(tmp_path / "test.db")
    db = DatabaseService(db_path=db_path)
    db.ensure_default_tenant_and_admin(tenant_id="default", admin_user_id="U001")
    usage_svc = UsageService(db_path=db_path)

    # Pre-populate a record so non-empty results are possible
    usage_svc.record_pipeline(
        tenant_id="default", user_id="U001", session_id="S1",
        prompt_tokens=100, completion_tokens=50, total_tokens=150,
        tool_call_count=2, iterations=1, duration_ms=500.0,
        status="success", model="test-model",
        tool_names=["arithmetic"],
    )

    from main import app
    from fastapi.testclient import TestClient

    with (
        patch.object(dependencies, "get_database", return_value=db),
        patch.object(dependencies, "get_usage_service", return_value=usage_svc),
        patch.object(dependencies, "get_plugin_registry",
                     return_value=MagicMock(list_plugins=lambda: [])),
    ):
        c = TestClient(app, raise_server_exceptions=False)
        yield c

    _clear_all_lru_caches()
    app.dependency_overrides.clear()


class TestAPIParameterValidation:
    """Test admin + self-service routes with malformed/boundary parameters."""

    # -- Malformed date parameters --

    def test_admin_tenant_usage_malformed_start_date(self, api_client):
        """'not-a-date' start_date should still return 200 (treated as no filter)."""
        resp = api_client.get("/api/admin/usage/tenant/default?start_date=not-a-date")
        assert resp.status_code == 200
        # _date_to_ts returns None for invalid dates, so no filter applied
        data = resp.json()
        assert data["total_requests"] >= 1

    def test_admin_tenant_usage_impossible_date(self, api_client):
        """'2024-13-40' is invalid — treated as no filter."""
        resp = api_client.get("/api/admin/usage/tenant/default?start_date=2024-13-40")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] >= 1

    def test_admin_tenant_daily_malformed_date(self, api_client):
        """Invalid dates in daily route should not cause 500."""
        resp = api_client.get(
            "/api/admin/usage/tenant/default/daily?start_date=xyz&end_date=abc"
        )
        # Daily queries compare date strings directly, so invalid strings
        # just yield no match (alphabetically wrong range)
        assert resp.status_code == 200

    # -- limit boundary values --

    def test_admin_ranking_limit_zero_rejected(self, api_client):
        """limit=0 should fail FastAPI validation (ge=1)."""
        resp = api_client.get("/api/admin/usage/tenant/default/users?limit=0")
        assert resp.status_code == 422  # Unprocessable Entity

    def test_admin_ranking_limit_negative_rejected(self, api_client):
        """limit=-1 should fail FastAPI validation (ge=1)."""
        resp = api_client.get("/api/admin/usage/tenant/default/users?limit=-1")
        assert resp.status_code == 422

    def test_admin_ranking_limit_over_max_rejected(self, api_client):
        """limit=999 should fail FastAPI validation (le=100)."""
        resp = api_client.get("/api/admin/usage/tenant/default/users?limit=999")
        assert resp.status_code == 422

    def test_admin_ranking_limit_max_boundary(self, api_client):
        """limit=100 (max) should be accepted."""
        resp = api_client.get("/api/admin/usage/tenant/default/users?limit=100")
        assert resp.status_code == 200

    def test_admin_ranking_limit_one(self, api_client):
        """limit=1 (min) should be accepted."""
        resp = api_client.get("/api/admin/usage/tenant/default/users?limit=1")
        assert resp.status_code == 200
        assert len(resp.json()) <= 1

    def test_admin_events_limit_zero_rejected(self, api_client):
        """Events limit=0 rejected."""
        resp = api_client.get("/api/admin/usage/tenant/default/events?limit=0")
        assert resp.status_code == 422

    def test_admin_events_limit_negative_rejected(self, api_client):
        """Events limit=-1 rejected."""
        resp = api_client.get("/api/admin/usage/tenant/default/events?limit=-1")
        assert resp.status_code == 422

    def test_admin_events_limit_over_max_rejected(self, api_client):
        """Events limit=999 rejected (le=200)."""
        resp = api_client.get("/api/admin/usage/tenant/default/events?limit=999")
        assert resp.status_code == 422

    def test_admin_events_limit_max_boundary(self, api_client):
        """Events limit=200 (max) should be accepted."""
        resp = api_client.get("/api/admin/usage/tenant/default/events?limit=200")
        assert resp.status_code == 200

    # -- Self-service routes boundary values --

    def test_self_events_limit_zero_rejected(self, api_client):
        resp = api_client.get("/api/usage/me/events?limit=0")
        assert resp.status_code == 422

    def test_self_events_limit_negative_rejected(self, api_client):
        resp = api_client.get("/api/usage/me/events?limit=-1")
        assert resp.status_code == 422

    def test_self_events_limit_over_max_rejected(self, api_client):
        resp = api_client.get("/api/usage/me/events?limit=999")
        assert resp.status_code == 422

    def test_self_events_limit_valid(self, api_client):
        resp = api_client.get("/api/usage/me/events?limit=10")
        assert resp.status_code == 200

    def test_self_usage_malformed_date(self, api_client):
        """Self-service /me with malformed date should not 500."""
        resp = api_client.get("/api/usage/me?start_date=garbage")
        assert resp.status_code == 200

    def test_self_daily_malformed_date(self, api_client):
        resp = api_client.get("/api/usage/me/daily?start_date=not-valid")
        assert resp.status_code == 200

    # -- Non-existent tenant returns empty data (not 500) --

    def test_admin_nonexistent_tenant_returns_empty(self, api_client):
        """Querying a tenant that doesn't exist should return zeros, not 500."""
        resp = api_client.get("/api/admin/usage/tenant/GHOST_TENANT")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 0
        assert data["total_tokens"] == 0

    def test_admin_nonexistent_tenant_daily_empty(self, api_client):
        resp = api_client.get("/api/admin/usage/tenant/GHOST_TENANT/daily")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_admin_nonexistent_tenant_users_empty(self, api_client):
        resp = api_client.get("/api/admin/usage/tenant/GHOST_TENANT/users")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_admin_nonexistent_tenant_tools_empty(self, api_client):
        resp = api_client.get("/api/admin/usage/tenant/GHOST_TENANT/tools")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_admin_nonexistent_tenant_events_empty(self, api_client):
        resp = api_client.get("/api/admin/usage/tenant/GHOST_TENANT/events")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_admin_nonexistent_tenant_storage_zero(self, api_client):
        resp = api_client.get("/api/admin/usage/tenant/GHOST_TENANT/storage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_bytes"] == 0

    def test_admin_nonexistent_user_returns_empty(self, api_client):
        resp = api_client.get("/api/admin/usage/tenant/default/users/GHOST_USER")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 0


# ═══════════════════════════════════════════════════════
# 5. Concurrent UPSERT Stress
# ═══════════════════════════════════════════════════════


class TestConcurrentUpsertStress:
    """100+ concurrent record_pipeline calls to same (tenant, user, date)."""

    async def test_100_concurrent_same_key(self, svc):
        """100 concurrent writes should all persist without lost writes."""
        n = 100
        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=20)

        async def _record(i: int):
            await loop.run_in_executor(
                executor,
                lambda: svc.record_pipeline(
                    tenant_id="T1",
                    user_id="U1",
                    session_id=f"STRESS-{i:04d}",
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                    tool_call_count=1,
                    iterations=1,
                    duration_ms=50.0,
                    status="success",
                    model="stress-model",
                    tool_names=["tool_a"],
                ),
            )

        await asyncio.gather(*[_record(i) for i in range(n)])
        executor.shutdown(wait=True)

        # Verify all 100 events are persisted
        events = svc.get_recent_events("T1", limit=200)
        assert len(events) == n

        # Verify daily aggregation is correct
        daily = svc.get_user_daily("T1", "U1")
        assert len(daily) == 1
        row = daily[0]
        assert row["total_requests"] == n
        assert row["total_tokens"] == 15 * n  # 1500
        assert row["total_tool_calls"] == n
        assert row["total_prompt_tokens"] == 10 * n
        assert row["total_completion_tokens"] == 5 * n
        assert row["success_count"] == n
        assert row["failed_count"] == 0

    async def test_150_concurrent_mixed_status(self, svc):
        """150 concurrent writes with mixed success/failure."""
        n = 150
        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=25)

        async def _record(i: int):
            status = "success" if i % 3 != 0 else "failed"
            await loop.run_in_executor(
                executor,
                lambda s=status: svc.record_pipeline(
                    tenant_id="T1",
                    user_id="U1",
                    session_id=f"MIX-{i:04d}",
                    total_tokens=10,
                    tool_call_count=1,
                    duration_ms=20.0,
                    status=s,
                ),
            )

        await asyncio.gather(*[_record(i) for i in range(n)])
        executor.shutdown(wait=True)

        events = svc.get_recent_events("T1", limit=300)
        assert len(events) == n

        daily = svc.get_user_daily("T1", "U1")
        assert len(daily) == 1
        row = daily[0]
        assert row["total_requests"] == n

        expected_failed = len([i for i in range(n) if i % 3 == 0])
        expected_success = n - expected_failed
        assert row["success_count"] == expected_success
        assert row["failed_count"] == expected_failed

    async def test_concurrent_multi_tenant_isolation(self, tmp_path):
        """Concurrent writes across 3 tenants — each tenant's data stays isolated."""
        db_path = str(tmp_path / "test.db")
        db = DatabaseService(db_path=db_path)
        db.create_tenant("T1", "T1")
        db.create_tenant("T2", "T2")
        db.create_tenant("T3", "T3")
        svc = UsageService(db_path=db_path)

        n_per_tenant = 50
        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=30)

        async def _record(tenant: str, i: int):
            await loop.run_in_executor(
                executor,
                lambda t=tenant: svc.record_pipeline(
                    tenant_id=t,
                    user_id="U1",
                    session_id=f"{t}-{i:04d}",
                    total_tokens=100,
                    tool_call_count=2,
                    status="success",
                ),
            )

        tasks = []
        for t in ["T1", "T2", "T3"]:
            for i in range(n_per_tenant):
                tasks.append(_record(t, i))

        await asyncio.gather(*tasks)
        executor.shutdown(wait=True)

        # Each tenant must have exactly n_per_tenant events
        for t in ["T1", "T2", "T3"]:
            events = svc.get_recent_events(t, limit=200)
            assert len(events) == n_per_tenant, f"Tenant {t} has {len(events)} events"
            for e in events:
                assert e["tenant_id"] == t

            usage = svc.get_tenant_usage(t)
            assert usage["total_requests"] == n_per_tenant
            assert usage["total_tokens"] == 100 * n_per_tenant

    async def test_concurrent_upsert_token_accumulation(self, svc):
        """Verify exact token sums after concurrent UPSERT (no lost updates)."""
        n = 120
        tokens_per_call = 25
        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=15)

        async def _record(i: int):
            await loop.run_in_executor(
                executor,
                lambda: svc.record_pipeline(
                    tenant_id="T1",
                    user_id="U1",
                    session_id=f"TOK-{i:04d}",
                    prompt_tokens=15,
                    completion_tokens=10,
                    total_tokens=tokens_per_call,
                    duration_ms=30.0,
                    status="success",
                ),
            )

        await asyncio.gather(*[_record(i) for i in range(n)])
        executor.shutdown(wait=True)

        usage = svc.get_tenant_usage("T1")
        assert usage["total_requests"] == n
        assert usage["total_tokens"] == tokens_per_call * n  # 3000
        assert usage["total_prompt_tokens"] == 15 * n  # 1800
        assert usage["total_completion_tokens"] == 10 * n  # 1200
        assert usage["avg_tokens_per_request"] == pytest.approx(
            tokens_per_call, rel=0.01
        )
