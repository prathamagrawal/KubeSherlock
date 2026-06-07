"""
agent.metrics_server
~~~~~~~~~~~~~~~~~~~~

Simple FastAPI server for Prometheus metrics scraping.

Usage:
    python -m agent.metrics_server
    # Metrics available at: http://localhost:8000/metrics
"""

import logging
import os
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .metrics import MetricsCollector

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="KubeSherlock Metrics")
_metrics = MetricsCollector()


@app.get("/metrics", response_class=PlainTextResponse)
async def get_metrics():
    """Prometheus scrape endpoint."""
    return _metrics.get_prometheus_metrics()


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}


def get_metrics_collector() -> MetricsCollector:
    """Get metrics collector instance."""
    return _metrics


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("METRICS_PORT", "8000"))
    log.info("Starting metrics server on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
