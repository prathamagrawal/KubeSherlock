#!/usr/bin/env python
"""
Example: Using all monitoring features together.

Usage:
    python examples/full_monitoring_example.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / "config.env")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-5s] %(name)s - %(message)s",
)
log = logging.getLogger(__name__)


async def main():
    """Demonstrates full monitoring setup."""
    
    # 1. Initialize monitoring context
    log.info("Initializing monitoring context...")
    from agent.integration import get_monitoring_context
    
    ctx = await get_monitoring_context()
    log.info("✓ Database connected")
    log.info("✓ Memory initialized")
    log.info("✓ Metrics configured")
    log.info("✓ Event stream ready")
    
    # 2. Set up event subscribers
    log.info("\nSetting up event subscribers...")
    from agent.events import EventType
    
    async def on_pod_failure(event):
        data = event.data
        log.info(f"🚨 POD FAILURE: {data['namespace']}/{data['pod_name']} - {data['reason']}")
    
    async def on_investigation_start(event):
        data = event.data
        log.info(f"🔍 INVESTIGATION START: {data['question'][:50]}...")
    
    async def on_investigation_complete(event):
        data = event.data
        log.info(
            f"✅ INVESTIGATION COMPLETE: "
            f"{data['iterations']} iterations, "
            f"{data['tool_calls_count']} tools, "
            f"{data['duration_seconds']:.2f}s"
        )
    
    ctx.events.subscribe(on_pod_failure)
    ctx.events.subscribe(on_investigation_start)
    ctx.events.subscribe(on_investigation_complete)
    
    # 3. Simulate investigation
    log.info("\nSimulating investigation...")
    
    # Create a mock investigation record
    inv_id = await ctx.db.create_investigation(
        question="Why is my pod crashing?",
        namespace="default",
        resource_name="my-pod",
        provider="anthropic",
    )
    log.info(f"✓ Created investigation record: {inv_id}")
    
    # Simulate tool calls
    await ctx.db.add_tool_call(
        investigation_id=inv_id,
        tool_name="describe_pod",
        arguments={"namespace": "default", "pod_name": "my-pod"},
        result_summary="Pod is in CrashLoopBackOff state",
        execution_time_ms=250,
    )
    log.info("✓ Recorded tool call")
    
    # Simulate investigation completion
    answer = """
    **Summary:** Pod is crashing due to memory exhaustion.
    
    **Evidence:**
    - Pod showing CrashLoopBackOff status
    - Last log: Out of memory killed
    - Memory limit: 256Mi, usage spike detected
    
    **Root Cause:** Application memory leak causing OOMKilled
    
    **Recommendations:**
    1. Increase memory limit to 512Mi
    2. Review application logs for memory leaks
    3. Monitor memory usage over time
    """
    
    await ctx.db.update_investigation(
        investigation_id=inv_id,
        answer=answer,
        root_cause="Application memory leak causing OOMKilled",
        recommendations="Increase memory limit and review app logs",
        iterations=2,
        tool_calls_count=3,
        duration_seconds=5.2,
        status="completed",
    )
    log.info("✓ Investigation saved to database")
    
    # Record metrics
    await ctx.metrics.record_investigation(
        duration_seconds=5.2,
        iterations=2,
        tool_calls_count=3,
        success=True,
    )
    log.info("✓ Metrics recorded")
    
    # Publish events
    await ctx.events.publish_investigation_completed(
        investigation_id=inv_id,
        iterations=2,
        tool_calls_count=3,
        duration_seconds=5.2,
    )
    log.info("✓ Events published")
    
    # 4. Query history
    log.info("\nQuerying investigation history...")
    past = await ctx.db.search_investigations(namespace="default", limit=5)
    for inv in past:
        log.info(f"  • {inv['question']}")
        log.info(f"    Root cause: {inv['root_cause']}")
        log.info(f"    Duration: {inv['duration_seconds']}s")
    
    # 5. Show metrics
    log.info("\nPrometheus metrics:")
    metrics_text = ctx.metrics.get_prometheus_metrics()
    for line in metrics_text.split("\n")[:10]:
        if line.strip() and not line.startswith("#"):
            log.info(f"  {line}")
    
    # 6. Show event history
    log.info("\nEvent history:")
    events = ctx.events.get_history(limit=5)
    for event in events[-3:]:
        log.info(f"  • {event.event_type.value} @ {event.timestamp.isoformat()}")
    
    # Cleanup
    await ctx.cleanup()
    log.info("\n✓ All done!")


if __name__ == "__main__":
    asyncio.run(main())
