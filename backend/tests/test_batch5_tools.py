"""
Batch 5 tests: #17+40 BM25 tool_search + tool_suggest, #19 MetricsCollector, #11 CancellationToken
"""

import asyncio
import pytest

from core.tracing import MetricsCollector
from core.runtime import CancellationToken


# ── #17+40: BM25 tool_search + tool_suggest ──

class TestBM25ToolSearch:

    def test_bm25_score_basic(self):
        from tools.builtin.tool_search import _bm25_score
        score = _bm25_score(["file", "read"], "read_uploaded_file Read file content", avg_dl=5.0)
        assert score > 0

    def test_bm25_score_no_match(self):
        from tools.builtin.tool_search import _bm25_score
        score = _bm25_score(["database"], "read_uploaded_file Read file content", avg_dl=5.0)
        assert score == 0

    def test_bm25_higher_for_better_match(self):
        from tools.builtin.tool_search import _bm25_score
        s1 = _bm25_score(["calculate"], "calculate_ratio Calculate ratio between numbers", avg_dl=5.0)
        s2 = _bm25_score(["calculate"], "read_uploaded_file Read file content", avg_dl=5.0)
        assert s1 > s2

    def test_tool_suggest_registered(self):
        """tool_suggest 工具已注册。"""
        from tools.builtin.tool_search import tool_search_registry
        names = tool_search_registry.get_tool_names()
        assert "tool_suggest" in names
        assert "tool_search" in names


# ── #19: MetricsCollector ──

class TestMetricsCollector:

    def test_increment(self):
        m = MetricsCollector()
        m.increment("test.counter")
        m.increment("test.counter")
        m.increment("test.counter", 3)
        assert m.get_counter("test.counter") == 5

    def test_record_and_stats(self):
        m = MetricsCollector()
        for v in [10, 20, 30, 40, 50]:
            m.record("test.latency", v)
        stats = m.get_histogram_stats("test.latency")
        assert stats["count"] == 5
        assert stats["min"] == 10
        assert stats["max"] == 50
        assert stats["avg"] == 30

    def test_histogram_cap_1000(self):
        m = MetricsCollector()
        for i in range(1100):
            m.record("big", float(i))
        stats = m.get_histogram_stats("big")
        assert stats["count"] == 1000

    def test_snapshot(self):
        m = MetricsCollector()
        m.increment("a", 5)
        m.record("b", 100.0)
        snap = m.snapshot()
        assert "uptime_s" in snap
        assert snap["counters"]["a"] == 5
        assert "b" in snap["histograms"]

    def test_empty_histogram(self):
        m = MetricsCollector()
        stats = m.get_histogram_stats("nonexistent")
        assert stats == {"count": 0}

    def test_get_metrics_singleton(self):
        from core.tracing import get_metrics
        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2


# ── #11: CancellationToken ──

class TestCancellationToken:

    def test_initial_state(self):
        token = CancellationToken()
        assert not token.is_cancelled

    def test_cancel(self):
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled

    def test_check_raises_when_cancelled(self):
        token = CancellationToken()
        token.cancel()
        with pytest.raises(asyncio.CancelledError):
            token.check()

    def test_check_ok_when_not_cancelled(self):
        token = CancellationToken()
        token.check()  # should not raise

    @pytest.mark.asyncio
    async def test_wait_returns_true_on_cancel(self):
        token = CancellationToken()

        async def _cancel_later():
            await asyncio.sleep(0.01)
            token.cancel()

        asyncio.create_task(_cancel_later())
        result = await token.wait(timeout=1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_returns_false_on_timeout(self):
        token = CancellationToken()
        result = await token.wait(timeout=0.01)
        assert result is False
