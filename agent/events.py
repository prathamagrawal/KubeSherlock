"""
agent.events
~~~~~~~~~~~~

Event stream for real-time monitoring and metrics.

Provides async event publishing for pod failures, investigations, and metrics.
"""

import asyncio
import logging
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

log = logging.getLogger(__name__)


class EventType(Enum):
    """Event types published by the watcher."""
    POD_FAILURE_DETECTED = "pod_failure_detected"
    INVESTIGATION_STARTED = "investigation_started"
    INVESTIGATION_COMPLETED = "investigation_completed"
    INVESTIGATION_FAILED = "investigation_failed"
    TOOL_CALLED = "tool_called"
    METRIC_RECORDED = "metric_recorded"


class Event:
    """A single event in the stream."""

    def __init__(
        self,
        event_type: EventType,
        timestamp: datetime,
        data: dict,
    ):
        self.event_type = event_type
        self.timestamp = timestamp
        self.data = data

    def __repr__(self) -> str:
        return (
            f"Event({self.event_type.value}, {self.timestamp.isoformat()}, "
            f"{self.data})"
        )


class EventStream:
    """Async event stream with subscriber support."""

    def __init__(self):
        self.subscribers: list[Callable[[Event], None]] = []
        self.event_history: list[Event] = []
        self.max_history = 10000

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        """Subscribe to events."""
        self.subscribers.append(callback)
        log.debug("Event subscriber registered  total=%d", len(self.subscribers))

    async def publish(
        self,
        event_type: EventType,
        data: dict,
    ) -> None:
        """Publish an event to all subscribers."""
        event = Event(event_type, datetime.now(), data)
        
        # Store in history
        self.event_history.append(event)
        if len(self.event_history) > self.max_history:
            self.event_history.pop(0)

        # Notify subscribers
        for callback in self.subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                log.error("Subscriber error: %s", e)

    async def publish_pod_failure(
        self,
        namespace: str,
        pod_name: str,
        reason: str,
        restart_count: int,
    ) -> None:
        """Publish a pod failure event."""
        await self.publish(
            EventType.POD_FAILURE_DETECTED,
            {
                "namespace": namespace,
                "pod_name": pod_name,
                "reason": reason,
                "restart_count": restart_count,
            },
        )

    async def publish_investigation_started(
        self,
        investigation_id: Optional[int],
        question: str,
        namespace: Optional[str],
    ) -> None:
        """Publish investigation start event."""
        await self.publish(
            EventType.INVESTIGATION_STARTED,
            {
                "investigation_id": investigation_id,
                "question": question,
                "namespace": namespace,
            },
        )

    async def publish_investigation_completed(
        self,
        investigation_id: Optional[int],
        iterations: int,
        tool_calls_count: int,
        duration_seconds: float,
    ) -> None:
        """Publish investigation completion event."""
        await self.publish(
            EventType.INVESTIGATION_COMPLETED,
            {
                "investigation_id": investigation_id,
                "iterations": iterations,
                "tool_calls_count": tool_calls_count,
                "duration_seconds": duration_seconds,
            },
        )

    async def publish_tool_called(
        self,
        tool_name: str,
        duration_ms: int,
        success: bool,
    ) -> None:
        """Publish a tool call event."""
        await self.publish(
            EventType.TOOL_CALLED,
            {
                "tool_name": tool_name,
                "duration_ms": duration_ms,
                "success": success,
            },
        )

    def get_history(
        self,
        event_type: Optional[EventType] = None,
        limit: int = 100,
    ) -> list[Event]:
        """Retrieve event history."""
        events = self.event_history
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[-limit:]


# Global event stream singleton
_global_stream: Optional[EventStream] = None


def get_event_stream() -> EventStream:
    """Get or create the global event stream."""
    global _global_stream
    if _global_stream is None:
        _global_stream = EventStream()
    return _global_stream
