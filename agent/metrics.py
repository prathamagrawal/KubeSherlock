"""
agent.metrics
~~~~~~~~~~~~~

Prometheus metrics collection for investigations and tool calls.

Exposes metrics via a simple HTTP scrape endpoint.
"""

import logging
import time
from typing import Optional

log = logging.getLogger(__name__)


class MetricsCollector:
    """Collects and tracks metrics for investigations."""

    def __init__(self, db=None):
        self.db = db
        self.investigation_duration_seconds = []
        self.tool_call_duration_ms = []
        self.investigation_count = 0
        self.error_count = 0
        self.tool_call_count = 0

    async def record_investigation(
        self,
        duration_seconds: float,
        iterations: int,
        tool_calls_count: int,
        success: bool = True,
    ) -> None:
        """Record investigation metrics."""
        self.investigation_count += 1
        self.investigation_duration_seconds.append(duration_seconds)
        self.tool_call_count += tool_calls_count

        if not success:
            self.error_count += 1

        if self.db:
            await self.db.record_metric(
                "investigation_duration_seconds",
                duration_seconds,
                labels={"iterations": iterations},
            )
            await self.db.record_metric(
                "investigation_total",
                1,
                labels={"status": "success" if success else "error"},
            )
            await self.db.record_metric(
                "investigation_tool_calls_total",
                tool_calls_count,
            )

    async def record_tool_call(
        self,
        tool_name: str,
        duration_ms: int,
        success: bool = True,
    ) -> None:
        """Record tool call metrics."""
        self.tool_call_duration_ms.append(duration_ms)

        if self.db:
            await self.db.record_metric(
                "tool_call_duration_ms",
                duration_ms,
                labels={"tool": tool_name},
            )
            if not success:
                await self.db.record_metric(
                    "tool_call_errors_total",
                    1,
                    labels={"tool": tool_name},
                )

    def get_prometheus_metrics(self) -> str:
        """Generate Prometheus text format metrics."""
        lines = []

        # Investigation metrics
        lines.append("# HELP investigation_total Total investigations")
        lines.append("# TYPE investigation_total counter")
        lines.append(f"investigation_total{{{self._format_labels()}}} {self.investigation_count}")

        lines.append("# HELP investigation_errors_total Total investigation errors")
        lines.append("# TYPE investigation_errors_total counter")
        lines.append(f"investigation_errors_total {self.error_count}")

        lines.append("# HELP investigation_duration_seconds Investigation duration")
        lines.append("# TYPE investigation_duration_seconds summary")
        if self.investigation_duration_seconds:
            avg = sum(self.investigation_duration_seconds) / len(
                self.investigation_duration_seconds
            )
            lines.append(f'investigation_duration_seconds_sum {sum(self.investigation_duration_seconds)}')
            lines.append(f'investigation_duration_seconds_count {len(self.investigation_duration_seconds)}')

        # Tool call metrics
        lines.append("# HELP tool_call_total Total tool calls")
        lines.append("# TYPE tool_call_total counter")
        lines.append(f"tool_call_total {self.tool_call_count}")

        if self.tool_call_duration_ms:
            avg_ms = sum(self.tool_call_duration_ms) / len(self.tool_call_duration_ms)
            lines.append("# HELP tool_call_duration_ms_avg Average tool call duration")
            lines.append("# TYPE tool_call_duration_ms_avg gauge")
            lines.append(f"tool_call_duration_ms_avg {avg_ms:.2f}")

        return "\n".join(lines)

    def _format_labels(self) -> str:
        """Format labels for Prometheus metric."""
        return "app=\"kubesherlock\""
