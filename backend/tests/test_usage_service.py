"""Tests for services/usage_service.py — UsageService."""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.database import DatabaseService
from services.usage_service import UsageService


@pytest.fixture
def svc(tmp_path):
    """Create UsageService with temp DB (tables initialized by DatabaseService)."""
    db_path = str(tmp_path / "test.db")
    db = DatabaseService(db_path=db_path)  # initializes all tables
    db.create_tenant("T1", "Test Tenant")
    return UsageService(db_path=db_path)


@pytest.fixture
def svc_with_data(tmp_path):
    """UsageService with pre-populated data."""
    db_path = str(tmp_path / "test.db")
    db = DatabaseService(db_path=db_path)
    db.create_tenant("T1", "Tenant 1")
    svc = UsageService(db_path=db_path)

    # Record some events
    svc.record_pipeline(
        tenant_id="T1", user_id="U1", session_id="S1",
        business_type="general_chat",
        prompt_tokens=100, completion_tokens=50, total_tokens=150,
        tool_call_count=3, iterations=2, duration_ms=1500.0,
        status="success", model="qwen2.5",
        tool_names=["read_reference", "arithmetic"],
    )
    svc.record_pipeline(
        tenant_id="T1", user_id="U1", session_id="S2",
        business_type="reimbursement_create",
        prompt_tokens=200, completion_tokens=100, total_tokens=300,
        tool_call_count=5, iterations=3, duration_ms=2500.0,
        status="success", model="qwen2.5",
        tool_names=["arithmetic", "propose_plan"],
    )
    svc.record_pipeline(
        tenant_id="T1", user_id="U2", session_id="S3",
        business_type="general_chat",
        prompt_tokens=80, completion_tokens=40, total_tokens=120,
        tool_call_count=1, iterations=1, duration_ms=800.0,
        status="failed", model="qwen2.5",
        tool_names=["read_reference"],
    )
    return svc


# ── record_pipeline ──


class TestRecordPipeline:
    def test_single_record(self, svc):
        event_id = svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
            tool_call_count=2, iterations=1, duration_ms=500.0,
            status="success", model="qwen2.5",
        )
        assert event_id is not None
        assert event_id > 0

    def test_multiple_records(self, svc):
        id1 = svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            total_tokens=100, status="success",
        )
        id2 = svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S2",
            total_tokens=200, status="success",
        )
        assert id2 > id1

    def test_daily_upsert_same_day(self, svc):
        """Same user+tenant+day should accumulate in usage_daily."""
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
            tool_call_count=2, status="success",
        )
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S2",
            prompt_tokens=200, completion_tokens=100, total_tokens=300,
            tool_call_count=3, status="success",
        )

        daily = svc.get_user_daily("T1", "U1")
        assert len(daily) == 1
        assert daily[0]["total_requests"] == 2
        assert daily[0]["total_tokens"] == 450
        assert daily[0]["total_tool_calls"] == 5
        assert daily[0]["success_count"] == 2

    def test_daily_upsert_failure(self, svc):
        """Failed events should increment failed_count."""
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            total_tokens=100, status="success",
        )
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S2",
            total_tokens=50, status="failed",
        )

        daily = svc.get_user_daily("T1", "U1")
        assert daily[0]["success_count"] == 1
        assert daily[0]["failed_count"] == 1

    def test_different_users_separate_daily(self, svc):
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1", total_tokens=100,
        )
        svc.record_pipeline(
            tenant_id="T1", user_id="U2", session_id="S2", total_tokens=200,
        )

        u1_daily = svc.get_user_daily("T1", "U1")
        u2_daily = svc.get_user_daily("T1", "U2")
        assert len(u1_daily) == 1
        assert len(u2_daily) == 1
        assert u1_daily[0]["total_tokens"] == 100
        assert u2_daily[0]["total_tokens"] == 200

    def test_tool_names_stored_as_json(self, svc):
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            tool_names=["arithmetic", "read_reference"],
        )
        events = svc.get_recent_events("T1")
        assert events[0]["tool_names"] == ["arithmetic", "read_reference"]

    def test_default_values(self, svc):
        event_id = svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
        )
        events = svc.get_recent_events("T1")
        e = events[0]
        assert e["business_type"] == "general_chat"
        assert e["status"] == "success"
        assert e["tool_names"] == []


# ── Query: Tenant Usage ──


class TestTenantUsage:
    def test_empty_result(self, svc):
        result = svc.get_tenant_usage("T_EMPTY")
        assert result["total_requests"] == 0
        assert result["total_tokens"] == 0
        assert result["avg_tokens_per_request"] == 0

    def test_aggregate(self, svc_with_data):
        result = svc_with_data.get_tenant_usage("T1")
        assert result["total_requests"] == 3
        assert result["total_tokens"] == 570  # 150 + 300 + 120
        assert result["total_tool_calls"] == 9  # 3 + 5 + 1
        assert result["success_count"] == 2
        assert result["failed_count"] == 1
        assert result["avg_tokens_per_request"] == 190.0  # 570 / 3

    def test_date_filter(self, svc):
        """Date filtering with start_date / end_date."""
        # Records created with time.time() → today
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1", total_tokens=100,
        )
        # Far future filter should return nothing
        result = svc.get_tenant_usage("T1", start_date="2099-01-01")
        assert result["total_requests"] == 0

        # Filter covering today should return the record
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        result = svc.get_tenant_usage("T1", start_date=today, end_date=today)
        assert result["total_requests"] == 1


# ── Query: Tenant Daily ──


class TestTenantDaily:
    def test_daily_aggregation(self, svc_with_data):
        daily = svc_with_data.get_tenant_daily("T1")
        assert len(daily) == 1  # all same day
        assert daily[0]["total_requests"] == 3
        assert daily[0]["total_tokens"] == 570

    def test_empty_daily(self, svc):
        daily = svc.get_tenant_daily("T_EMPTY")
        assert daily == []

    def test_date_filter_daily(self, svc_with_data):
        daily = svc_with_data.get_tenant_daily("T1", start_date="2099-01-01")
        assert daily == []


# ── Query: User Ranking ──


class TestUserRanking:
    def test_ranking_by_tokens(self, svc_with_data):
        ranking = svc_with_data.get_tenant_user_ranking("T1")
        assert len(ranking) == 2
        assert ranking[0]["user_id"] == "U1"  # 450 tokens > U2's 120
        assert ranking[1]["user_id"] == "U2"

    def test_limit(self, svc_with_data):
        ranking = svc_with_data.get_tenant_user_ranking("T1", limit=1)
        assert len(ranking) == 1

    def test_empty_ranking(self, svc):
        ranking = svc.get_tenant_user_ranking("T_EMPTY")
        assert ranking == []


# ── Query: User Usage ──


class TestUserUsage:
    def test_user_aggregate(self, svc_with_data):
        result = svc_with_data.get_user_usage("T1", "U1")
        assert result["total_requests"] == 2
        assert result["total_tokens"] == 450
        assert result["success_count"] == 2

    def test_user_not_found(self, svc):
        result = svc.get_user_usage("T1", "U_MISSING")
        assert result["total_requests"] == 0

    def test_user_daily(self, svc_with_data):
        daily = svc_with_data.get_user_daily("T1", "U1")
        assert len(daily) == 1
        assert daily[0]["total_requests"] == 2


# ── Query: Recent Events ──


class TestRecentEvents:
    def test_list_events(self, svc_with_data):
        events = svc_with_data.get_recent_events("T1")
        assert len(events) == 3
        # Ordered by created_at DESC
        assert events[0]["created_at"] >= events[1]["created_at"]

    def test_filter_by_user(self, svc_with_data):
        events = svc_with_data.get_recent_events("T1", user_id="U2")
        assert len(events) == 1
        assert events[0]["user_id"] == "U2"

    def test_limit(self, svc_with_data):
        events = svc_with_data.get_recent_events("T1", limit=2)
        assert len(events) == 2

    def test_tool_names_parsed(self, svc_with_data):
        events = svc_with_data.get_recent_events("T1", user_id="U1", limit=1)
        assert isinstance(events[0]["tool_names"], list)


# ── Query: Tool Usage Stats ──


class TestToolUsageStats:
    def test_tool_frequency(self, svc_with_data):
        stats = svc_with_data.get_tool_usage_stats("T1")
        # arithmetic appears in 2 events, read_reference in 2, propose_plan in 1
        name_to_count = {s["tool_name"]: s["call_count"] for s in stats}
        assert name_to_count["arithmetic"] == 2
        assert name_to_count["read_reference"] == 2
        assert name_to_count["propose_plan"] == 1

    def test_sorted_descending(self, svc_with_data):
        stats = svc_with_data.get_tool_usage_stats("T1")
        counts = [s["call_count"] for s in stats]
        assert counts == sorted(counts, reverse=True)

    def test_empty_stats(self, svc):
        stats = svc.get_tool_usage_stats("T_EMPTY")
        assert stats == []


# ── Query: Storage Usage ──


class TestStorageUsage:
    def test_empty_dirs(self, svc):
        result = svc.get_storage_usage("T1")
        assert result["sessions_bytes"] == 0
        assert result["memory_bytes"] == 0
        assert result["files_bytes"] == 0
        assert result["total_bytes"] == 0

    def test_with_files(self, tmp_path):
        """Create temp files and verify size calculation."""
        db_path = str(tmp_path / "test.db")
        DatabaseService(db_path=db_path)
        svc = UsageService(db_path=db_path)

        # Create session files
        session_dir = tmp_path / "sessions" / "T1" / "U1"
        session_dir.mkdir(parents=True)
        (session_dir / "s1.jsonl").write_text("x" * 100)

        # Create memory files
        mem_dir = tmp_path / "memory" / "tenant" / "T1"
        mem_dir.mkdir(parents=True)
        (mem_dir / "notes.md").write_text("y" * 200)

        result = svc.get_storage_usage("T1")
        assert result["sessions_bytes"] == 100
        assert result["memory_bytes"] == 200
        assert result["total_bytes"] == 300

    def test_user_scoped_storage(self, tmp_path):
        """User-scoped storage scans user-specific directories."""
        db_path = str(tmp_path / "test.db")
        DatabaseService(db_path=db_path)
        svc = UsageService(db_path=db_path)

        # Create user-specific session file
        session_dir = tmp_path / "sessions" / "T1" / "U1"
        session_dir.mkdir(parents=True)
        (session_dir / "s1.jsonl").write_text("a" * 50)

        # Create user-specific memory
        mem_dir = tmp_path / "memory" / "user" / "T1" / "U1"
        mem_dir.mkdir(parents=True)
        (mem_dir / "prefs.md").write_text("b" * 75)

        result = svc.get_storage_usage("T1", user_id="U1")
        assert result["sessions_bytes"] == 50
        assert result["memory_bytes"] == 75
        assert result["total_bytes"] == 125
