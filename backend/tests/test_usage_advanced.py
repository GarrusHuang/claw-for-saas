"""
Advanced tests for UsageService — edge cases not covered by test_usage_service.py.

Covers:
  1. _date_to_ts edge cases (None, empty, invalid formats, end_of_day)
  2. Concurrent writes (asyncio.gather + run_in_executor)
  3. Division-by-zero handling in avg calculations
  4. JSON parsing in get_recent_events (empty list, None tool_names)
  5. Date range query edge cases (inverted range, same-day, no filter)
  6. Pydantic model validation (all 6 usage models)
"""
import asyncio
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.database import DatabaseService
from services.usage_service import UsageService
from models.usage import (
    UsageSummary,
    DailyUsage,
    UserRanking,
    ToolUsageStat,
    UsageEvent,
    StorageUsage,
)


@pytest.fixture
def svc(tmp_path):
    """Create UsageService with temp DB (tables initialized by DatabaseService)."""
    db_path = str(tmp_path / "test.db")
    DatabaseService(db_path=db_path).create_tenant("T1", "Test Tenant")
    return UsageService(db_path=db_path)


# ── 1. _date_to_ts edge cases ──


class TestDateToTs:
    """Test the private _date_to_ts helper for boundary conditions."""

    def test_none_returns_none(self, svc):
        assert svc._date_to_ts(None) is None

    def test_empty_string_returns_none(self, svc):
        assert svc._date_to_ts("") is None

    def test_valid_date_returns_timestamp(self, svc):
        ts = svc._date_to_ts("2024-06-15")
        assert ts is not None
        # Verify it round-trips back to the same date
        dt = datetime.fromtimestamp(ts)
        assert dt.year == 2024
        assert dt.month == 6
        assert dt.day == 15
        assert dt.hour == 0
        assert dt.minute == 0

    def test_end_of_day_adds_offset(self, svc):
        ts_start = svc._date_to_ts("2024-06-15", end_of_day=False)
        ts_end = svc._date_to_ts("2024-06-15", end_of_day=True)
        assert ts_start is not None
        assert ts_end is not None
        diff = ts_end - ts_start
        # Should be 86400 - 0.001 = 86399.999
        assert abs(diff - 86399.999) < 0.01

    def test_invalid_month_returns_none(self, svc):
        assert svc._date_to_ts("2024-13-01") is None

    def test_invalid_text_returns_none(self, svc):
        assert svc._date_to_ts("not-a-date") is None

    def test_wrong_separator_returns_none(self, svc):
        assert svc._date_to_ts("2024/06/15") is None

    def test_partial_date_returns_none(self, svc):
        assert svc._date_to_ts("2024-06") is None

    def test_date_with_time_returns_none(self, svc):
        assert svc._date_to_ts("2024-06-15T12:00:00") is None


# ── 2. Concurrent writes ──


class TestConcurrentWrites:
    """Verify SQLite transaction safety under concurrent writes."""

    async def test_concurrent_record_pipeline_no_data_loss(self, svc):
        """50 concurrent record_pipeline calls should all persist."""
        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=10)

        async def _record(i: int):
            await loop.run_in_executor(
                executor,
                lambda: svc.record_pipeline(
                    tenant_id="T1",
                    user_id="U1",
                    session_id=f"S{i:03d}",
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                    tool_call_count=1,
                    iterations=1,
                    duration_ms=100.0,
                    status="success",
                    model="test-model",
                ),
            )

        await asyncio.gather(*[_record(i) for i in range(50)])
        executor.shutdown(wait=True)

        # Verify all 50 events exist
        events = svc.get_recent_events("T1", limit=100)
        assert len(events) == 50

        # Verify daily row accumulated correctly (1 row, 50 requests)
        daily = svc.get_user_daily("T1", "U1")
        assert len(daily) == 1
        assert daily[0]["total_requests"] == 50
        assert daily[0]["total_tokens"] == 15 * 50  # 750
        assert daily[0]["total_tool_calls"] == 50
        assert daily[0]["total_duration_ms"] == pytest.approx(100.0 * 50, rel=0.01)

    async def test_concurrent_different_users(self, svc):
        """Concurrent writes for different users stay separated."""
        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=5)

        async def _record(user_id: str, count: int):
            for i in range(count):
                await loop.run_in_executor(
                    executor,
                    lambda uid=user_id, idx=i: svc.record_pipeline(
                        tenant_id="T1",
                        user_id=uid,
                        session_id=f"S-{uid}-{idx}",
                        total_tokens=100,
                        status="success",
                    ),
                )

        await asyncio.gather(
            _record("UA", 10),
            _record("UB", 10),
        )
        executor.shutdown(wait=True)

        ua = svc.get_user_usage("T1", "UA")
        ub = svc.get_user_usage("T1", "UB")
        assert ua["total_requests"] == 10
        assert ub["total_requests"] == 10
        assert ua["total_tokens"] == 1000
        assert ub["total_tokens"] == 1000


# ── 3. Division by zero handling ──


class TestDivisionByZero:
    """Avg fields must be 0 when total_requests is 0 (no division error)."""

    def test_tenant_usage_zero_requests(self, svc):
        result = svc.get_tenant_usage("T1")
        assert result["total_requests"] == 0
        assert result["avg_tokens_per_request"] == 0
        assert result["avg_duration_ms"] == 0

    def test_user_usage_nonexistent_user(self, svc):
        result = svc.get_user_usage("T1", "GHOST")
        assert result["total_requests"] == 0
        assert result["avg_tokens_per_request"] == 0
        assert result["avg_duration_ms"] == 0

    def test_tenant_usage_with_zero_token_records(self, svc):
        """Records with 0 tokens should not cause division issues."""
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            duration_ms=0.0, status="success",
        )
        result = svc.get_tenant_usage("T1")
        assert result["total_requests"] == 1
        assert result["avg_tokens_per_request"] == 0.0
        assert result["avg_duration_ms"] == 0.0


# ── 4. JSON parsing in get_recent_events ──


class TestJsonParsing:
    """Verify tool_names JSON serialization / deserialization."""

    def test_valid_tool_names_parsed(self, svc):
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            tool_names=["arithmetic", "read_reference", "propose_plan"],
        )
        events = svc.get_recent_events("T1")
        assert events[0]["tool_names"] == ["arithmetic", "read_reference", "propose_plan"]

    def test_empty_list_tool_names(self, svc):
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            tool_names=[],
        )
        events = svc.get_recent_events("T1")
        assert events[0]["tool_names"] == []

    def test_none_tool_names_defaults_to_empty(self, svc):
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            tool_names=None,
        )
        events = svc.get_recent_events("T1")
        assert events[0]["tool_names"] == []

    def test_no_tool_names_kwarg_defaults_to_empty(self, svc):
        """Omitting tool_names entirely should still parse as []."""
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
        )
        events = svc.get_recent_events("T1")
        assert events[0]["tool_names"] == []

    def test_single_tool_name(self, svc):
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            tool_names=["arithmetic"],
        )
        events = svc.get_recent_events("T1")
        assert events[0]["tool_names"] == ["arithmetic"]

    def test_tool_usage_stats_with_empty_tool_names(self, svc):
        """Events with empty tool_names should not pollute tool stats."""
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            tool_names=[],
        )
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S2",
            tool_names=["arithmetic"],
        )
        stats = svc.get_tool_usage_stats("T1")
        assert len(stats) == 1
        assert stats[0]["tool_name"] == "arithmetic"
        assert stats[0]["call_count"] == 1


# ── 5. Date range query edge cases ──


class TestDateRangeQueries:
    """Edge cases for start_date / end_date filtering."""

    def test_start_after_end_returns_empty(self, svc):
        """When start_date > end_date, results should be empty, not an error."""
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            total_tokens=100,
        )
        result = svc.get_tenant_usage("T1", start_date="2099-01-01", end_date="2020-01-01")
        assert result["total_requests"] == 0

    def test_same_day_filter_returns_records(self, svc):
        """start_date == end_date should return that day's records."""
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            total_tokens=100,
        )
        today = datetime.now().strftime("%Y-%m-%d")
        result = svc.get_tenant_usage("T1", start_date=today, end_date=today)
        assert result["total_requests"] == 1
        assert result["total_tokens"] == 100

    def test_no_date_filters_returns_all(self, svc):
        """Omitting date filters returns everything."""
        for i in range(5):
            svc.record_pipeline(
                tenant_id="T1", user_id="U1", session_id=f"S{i}",
                total_tokens=10,
            )
        result = svc.get_tenant_usage("T1")
        assert result["total_requests"] == 5
        assert result["total_tokens"] == 50

    def test_daily_start_after_end_returns_empty(self, svc):
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            total_tokens=100,
        )
        daily = svc.get_tenant_daily("T1", start_date="2099-01-01", end_date="2020-01-01")
        assert daily == []

    def test_user_ranking_date_filter(self, svc):
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            total_tokens=500,
        )
        # Far future filter should exclude today's records
        ranking = svc.get_tenant_user_ranking("T1", start_date="2099-01-01")
        assert ranking == []

        # Today should include the record
        today = datetime.now().strftime("%Y-%m-%d")
        ranking = svc.get_tenant_user_ranking("T1", start_date=today, end_date=today)
        assert len(ranking) == 1
        assert ranking[0]["total_tokens"] == 500

    def test_user_daily_date_filter(self, svc):
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            total_tokens=200,
        )
        daily = svc.get_user_daily("T1", "U1", start_date="2099-01-01")
        assert daily == []

        today = datetime.now().strftime("%Y-%m-%d")
        daily = svc.get_user_daily("T1", "U1", start_date=today, end_date=today)
        assert len(daily) == 1

    def test_tool_usage_stats_date_filter(self, svc):
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            tool_names=["arithmetic"],
        )
        # Far future
        stats = svc.get_tool_usage_stats("T1", start_date="2099-01-01")
        assert stats == []

        # Today
        today = datetime.now().strftime("%Y-%m-%d")
        stats = svc.get_tool_usage_stats("T1", start_date=today, end_date=today)
        assert len(stats) == 1

    def test_user_usage_inverted_date_range(self, svc):
        svc.record_pipeline(
            tenant_id="T1", user_id="U1", session_id="S1",
            total_tokens=100,
        )
        result = svc.get_user_usage("T1", "U1", start_date="2099-01-01", end_date="2020-01-01")
        assert result["total_requests"] == 0
        assert result["avg_tokens_per_request"] == 0


# ── 6. Pydantic model validation ──


class TestPydanticModels:
    """Validate all 6 usage Pydantic models."""

    # -- UsageSummary --

    def test_usage_summary_defaults(self):
        m = UsageSummary()
        assert m.total_requests == 0
        assert m.total_prompt_tokens == 0
        assert m.total_completion_tokens == 0
        assert m.total_tokens == 0
        assert m.total_tool_calls == 0
        assert m.total_duration_ms == 0.0
        assert m.success_count == 0
        assert m.failed_count == 0
        assert m.avg_tokens_per_request == 0.0
        assert m.avg_duration_ms == 0.0

    def test_usage_summary_with_values(self):
        m = UsageSummary(
            total_requests=10,
            total_tokens=5000,
            avg_tokens_per_request=500.0,
        )
        assert m.total_requests == 10
        assert m.total_tokens == 5000
        assert m.avg_tokens_per_request == 500.0

    # -- DailyUsage --

    def test_daily_usage_requires_date(self):
        with pytest.raises(ValidationError):
            DailyUsage()  # date is required (no default)

    def test_daily_usage_defaults(self):
        m = DailyUsage(date="2024-06-15")
        assert m.date == "2024-06-15"
        assert m.total_requests == 0
        assert m.total_tokens == 0

    # -- UserRanking --

    def test_user_ranking_requires_user_id(self):
        with pytest.raises(ValidationError):
            UserRanking()  # user_id is required

    def test_user_ranking_defaults(self):
        m = UserRanking(user_id="U1")
        assert m.user_id == "U1"
        assert m.total_requests == 0
        assert m.total_tokens == 0
        assert m.total_tool_calls == 0
        assert m.total_duration_ms == 0.0

    # -- ToolUsageStat --

    def test_tool_usage_stat_requires_tool_name(self):
        with pytest.raises(ValidationError):
            ToolUsageStat()  # tool_name is required

    def test_tool_usage_stat_defaults(self):
        m = ToolUsageStat(tool_name="arithmetic")
        assert m.tool_name == "arithmetic"
        assert m.call_count == 0

    # -- UsageEvent --

    def test_usage_event_requires_all_ids(self):
        with pytest.raises(ValidationError):
            UsageEvent()  # id, tenant_id, user_id, session_id required

    def test_usage_event_minimal(self):
        m = UsageEvent(id=1, tenant_id="T1", user_id="U1", session_id="S1")
        assert m.id == 1
        assert m.tenant_id == "T1"
        assert m.business_type == "general_chat"
        assert m.status == "success"
        assert m.tool_names == []
        assert m.created_at == 0.0

    def test_usage_event_with_tool_names(self):
        m = UsageEvent(
            id=1, tenant_id="T1", user_id="U1", session_id="S1",
            tool_names=["arithmetic", "read_reference"],
        )
        assert m.tool_names == ["arithmetic", "read_reference"]

    def test_usage_event_type_validation(self):
        """String where int is expected should raise ValidationError."""
        with pytest.raises(ValidationError):
            UsageEvent(
                id="not-an-int",  # type: ignore
                tenant_id="T1",
                user_id="U1",
                session_id="S1",
            )

    def test_usage_event_missing_tenant_id(self):
        with pytest.raises(ValidationError):
            UsageEvent(id=1, user_id="U1", session_id="S1")

    def test_usage_event_missing_user_id(self):
        with pytest.raises(ValidationError):
            UsageEvent(id=1, tenant_id="T1", session_id="S1")

    def test_usage_event_missing_session_id(self):
        with pytest.raises(ValidationError):
            UsageEvent(id=1, tenant_id="T1", user_id="U1")

    # -- StorageUsage --

    def test_storage_usage_defaults(self):
        m = StorageUsage()
        assert m.sessions_bytes == 0
        assert m.memory_bytes == 0
        assert m.files_bytes == 0
        assert m.total_bytes == 0

    def test_storage_usage_with_values(self):
        m = StorageUsage(sessions_bytes=100, memory_bytes=200, files_bytes=300, total_bytes=600)
        assert m.total_bytes == 600
