"""
agent.integration
~~~~~~~~~~~~~~~~~

Integrates database, memory, metrics, and event stream for full monitoring.

Provides a simple interface to initialize all components.
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)


class MonitoringContext:
    """Bundles database, memory, metrics, and events for easy initialization."""

    def __init__(self):
        self.db = None
        self.memory = None
        self.metrics = None
        self.events = None

    async def initialize(self):
        """Initialize all components."""
        from database.db import get_db
        from .memory import InvestigationMemory
        from .metrics import MetricsCollector
        from .events import get_event_stream

        self.db = await get_db()
        self.memory = InvestigationMemory(self.db)
        self.metrics = MetricsCollector(self.db)
        self.events = get_event_stream()

        log.info("Monitoring context initialized")

    async def cleanup(self):
        """Close connections."""
        if self.db:
            await self.db.disconnect()
            log.info("Monitoring context cleaned up")


async def get_monitoring_context() -> MonitoringContext:
    """Get initialized monitoring context."""
    ctx = MonitoringContext()
    await ctx.initialize()
    return ctx
