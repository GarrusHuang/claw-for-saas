"""Tests for core/event_bus.py — EventBus, Event."""
import asyncio
import sys
import os
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.event_bus import EventBus, Event


class TestEvent:
    def test_to_sse_dict(self):
        e = Event(event_type="test", data={"key": "val"}, trace_id="t1")
        d = e.to_sse_dict()
        assert d["event"] == "test"
        assert d["data"]["key"] == "val"
        assert d["data"]["trace_id"] == "t1"
        assert "ts" in d["data"]

    def test_default_timestamp(self):
        before = time.time()
        e = Event(event_type="test", data={}, trace_id="t1")
        after = time.time()
        assert before <= e.timestamp <= after


class TestEventBus:
    def test_init(self):
        bus = EventBus(trace_id="abc")
        assert bus.trace_id == "abc"
        assert bus.is_closed is False
        assert bus.event_count == 0

    def test_emit_and_history(self):
        bus = EventBus(trace_id="t1")
        bus.emit("test_event", {"msg": "hello"})
        assert bus.event_count == 1
        assert bus.history[0].event_type == "test_event"

    def test_emit_after_close_drops(self):
        bus = EventBus(trace_id="t1")
        bus.close()
        bus.emit("should_drop", {})
        # The close() itself puts a pipeline_complete, then further emits drop
        # History may have the close event but not should_drop
        events = [e.event_type for e in bus.history]
        assert "should_drop" not in events

    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self):
        bus = EventBus(trace_id="t1")
        bus.emit("event1", {"a": 1})
        bus.emit("pipeline_complete", {"status": "done"})

        events = []
        async for e in bus.subscribe():
            events.append(e)

        assert len(events) == 2
        assert events[0]["event"] == "event1"
        assert events[1]["event"] == "pipeline_complete"

    @pytest.mark.asyncio
    async def test_subscribe_auto_close_on_pipeline_complete(self):
        bus = EventBus(trace_id="t1")
        bus.emit("step1", {})
        bus.emit("pipeline_complete", {})
        bus.emit("after_close", {})  # should be in history but not yielded

        events = []
        async for e in bus.subscribe():
            events.append(e["event"])

        assert "step1" in events
        assert "pipeline_complete" in events
        assert bus.is_closed is True

    @pytest.mark.asyncio
    async def test_subscribe_keepalive(self):
        bus = EventBus(trace_id="t1", keepalive_interval=0.1)

        async def close_later():
            await asyncio.sleep(0.25)
            bus.close()

        task = asyncio.create_task(close_later())

        events = []
        async for e in bus.subscribe():
            events.append(e["event"])

        await task

        # Should have at least one keepalive
        assert "keepalive" in events

    def test_close_is_idempotent(self):
        bus = EventBus(trace_id="t1")
        bus.close()
        bus.close()  # Should not raise
        assert bus.is_closed is True

    @pytest.mark.asyncio
    async def test_subscribe_fatal_error_closes(self):
        bus = EventBus(trace_id="t1")
        bus.emit("fatal_error", {"msg": "crash"})

        events = []
        async for e in bus.subscribe():
            events.append(e["event"])

        assert "fatal_error" in events
        assert bus.is_closed is True

    def test_emit_default_data(self):
        bus = EventBus(trace_id="t1")
        bus.emit("no_data")
        assert bus.history[0].data == {}
