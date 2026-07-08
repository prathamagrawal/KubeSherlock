"""
tests.test_events
~~~~~~~~~~~~~~~~~

Unit tests for agent/events.py — async event stream and singleton.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from agent.events import Event, EventStream, EventType, get_event_stream
import agent.events as events_module


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    """Reset global event stream singleton before each test."""
    monkeypatch.setattr(events_module, "_global_stream", None)


# ─────────────────────────────────────────────────────────────────────────────
# subscribe / publish
# ─────────────────────────────────────────────────────────────────────────────

class TestSubscribePublish:

    @pytest.mark.asyncio
    async def test_subscribe_adds_callback(self):
        stream = EventStream()
        cb = MagicMock()
        stream.subscribe(cb)
        assert cb in stream.subscribers

    @pytest.mark.asyncio
    async def test_publish_calls_sync_subscriber(self):
        stream = EventStream()
        received = []
        stream.subscribe(lambda e: received.append(e))
        await stream.publish(EventType.POD_FAILURE_DETECTED, {"pod": "x"})
        assert len(received) == 1
        assert received[0].event_type == EventType.POD_FAILURE_DETECTED

    @pytest.mark.asyncio
    async def test_publish_awaits_async_subscriber(self):
        stream = EventStream()
        received = []

        async def async_cb(event):
            received.append(event)

        stream.subscribe(async_cb)
        await stream.publish(EventType.INVESTIGATION_STARTED, {"q": "why?"})
        assert len(received) == 1
        assert received[0].data["q"] == "why?"

    @pytest.mark.asyncio
    async def test_subscriber_exception_does_not_propagate(self):
        stream = EventStream()

        def bad_cb(event):
            raise RuntimeError("subscriber error")

        stream.subscribe(bad_cb)
        # Should not raise
        await stream.publish(EventType.TOOL_CALLED, {"tool": "list_pods"})

    @pytest.mark.asyncio
    async def test_event_stored_in_history(self):
        stream = EventStream()
        await stream.publish(EventType.INVESTIGATION_COMPLETED, {"iterations": 3})
        assert len(stream.event_history) == 1
        assert stream.event_history[0].event_type == EventType.INVESTIGATION_COMPLETED

    @pytest.mark.asyncio
    async def test_history_capped_at_max_history(self):
        stream = EventStream()
        stream.max_history = 5
        for i in range(7):
            await stream.publish(EventType.METRIC_RECORDED, {"i": i})
        assert len(stream.event_history) == 5

    @pytest.mark.asyncio
    async def test_history_retains_most_recent_on_cap(self):
        stream = EventStream()
        stream.max_history = 3
        for i in range(5):
            await stream.publish(EventType.METRIC_RECORDED, {"i": i})
        # Most recent should be kept
        last_data = [e.data["i"] for e in stream.event_history]
        assert last_data == [2, 3, 4]


# ─────────────────────────────────────────────────────────────────────────────
# get_history
# ─────────────────────────────────────────────────────────────────────────────

class TestGetHistory:

    @pytest.mark.asyncio
    async def test_returns_all_events_without_filter(self):
        stream = EventStream()
        await stream.publish(EventType.POD_FAILURE_DETECTED, {})
        await stream.publish(EventType.INVESTIGATION_STARTED, {})
        history = stream.get_history()
        assert len(history) == 2

    @pytest.mark.asyncio
    async def test_filters_by_event_type(self):
        stream = EventStream()
        await stream.publish(EventType.POD_FAILURE_DETECTED, {"pod": "a"})
        await stream.publish(EventType.TOOL_CALLED, {"tool": "x"})
        await stream.publish(EventType.POD_FAILURE_DETECTED, {"pod": "b"})
        history = stream.get_history(event_type=EventType.POD_FAILURE_DETECTED)
        assert len(history) == 2
        assert all(e.event_type == EventType.POD_FAILURE_DETECTED for e in history)

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        stream = EventStream()
        for i in range(10):
            await stream.publish(EventType.METRIC_RECORDED, {"i": i})
        history = stream.get_history(limit=3)
        assert len(history) == 3


# ─────────────────────────────────────────────────────────────────────────────
# Convenience publish methods
# ─────────────────────────────────────────────────────────────────────────────

class TestConveniencePublishMethods:

    @pytest.mark.asyncio
    async def test_publish_pod_failure_correct_type_and_data(self):
        stream = EventStream()
        await stream.publish_pod_failure("default", "web-0", "CrashLoopBackOff", 5)
        event = stream.event_history[0]
        assert event.event_type == EventType.POD_FAILURE_DETECTED
        assert event.data["namespace"] == "default"
        assert event.data["pod_name"] == "web-0"
        assert event.data["reason"] == "CrashLoopBackOff"
        assert event.data["restart_count"] == 5

    @pytest.mark.asyncio
    async def test_publish_investigation_started(self):
        stream = EventStream()
        await stream.publish_investigation_started(42, "Why is pod failing?", "production")
        event = stream.event_history[0]
        assert event.event_type == EventType.INVESTIGATION_STARTED
        assert event.data["investigation_id"] == 42
        assert event.data["question"] == "Why is pod failing?"
        assert event.data["namespace"] == "production"

    @pytest.mark.asyncio
    async def test_publish_investigation_completed(self):
        stream = EventStream()
        await stream.publish_investigation_completed(7, 3, 12, 45.2)
        event = stream.event_history[0]
        assert event.event_type == EventType.INVESTIGATION_COMPLETED
        assert event.data["investigation_id"] == 7
        assert event.data["iterations"] == 3
        assert event.data["tool_calls_count"] == 12
        assert event.data["duration_seconds"] == pytest.approx(45.2)

    @pytest.mark.asyncio
    async def test_publish_tool_called(self):
        stream = EventStream()
        await stream.publish_tool_called("list_pods", 120, True)
        event = stream.event_history[0]
        assert event.event_type == EventType.TOOL_CALLED
        assert event.data["tool_name"] == "list_pods"
        assert event.data["duration_ms"] == 120
        assert event.data["success"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

class TestGetEventStreamSingleton:

    def test_returns_event_stream_instance(self):
        s = get_event_stream()
        assert isinstance(s, EventStream)

    def test_same_instance_on_repeated_calls(self):
        s1 = get_event_stream()
        s2 = get_event_stream()
        assert s1 is s2

    def test_singleton_reset_by_fixture(self):
        # After reset_singleton fixture runs, first call creates a fresh instance
        s = get_event_stream()
        assert s is not None
