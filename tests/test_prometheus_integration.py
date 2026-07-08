"""
tests/test_prometheus_integration.py
======================================

Prometheus integration tests for KubeSherlock.

Two layers of tests:

Unit tests (always run — no infra needed)
-----------------------------------------
* MetricsCollector — counter increments, duration tracking, Prometheus text output
* MetricsCollector + DB — verifies DB.record_metric() calls when a db is wired in
* FastAPI /metrics endpoint — verifies the HTTP contract via TestClient
* /health endpoint — basic liveness check

Live integration tests (gated behind INTEGRATION_TEST=1)
---------------------------------------------------------
These require the docker-compose stack to be running:

    docker-compose up -d
    INTEGRATION_TEST=1 pytest tests/test_prometheus_integration.py -v -m integration

They also optionally test scraping the Prometheus server itself if
PROMETHEUS_URL is set (default: http://localhost:9090).
"""

import asyncio
import os
import time
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# ─────────────────────────────────────────────────────────────────────────────
# Helpers / markers
# ─────────────────────────────────────────────────────────────────────────────

INTEGRATION = os.getenv("INTEGRATION_TEST", "0") == "1"
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")

integration = pytest.mark.skipif(
    not INTEGRATION,
    reason="Set INTEGRATION_TEST=1 to run live Prometheus/metrics tests",
)


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — MetricsCollector (pure in-memory, no DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricsCollectorUnit:

    def test_initial_state_is_zero(self):
        """Fresh collector must start at zero for all counters."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()
        assert mc.investigation_count == 0
        assert mc.error_count == 0
        assert mc.tool_call_count == 0
        assert mc.investigation_duration_seconds == []
        assert mc.tool_call_duration_ms == []

    @pytest.mark.asyncio
    async def test_record_investigation_increments_count(self):
        """record_investigation() must bump investigation_count."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()
        await mc.record_investigation(duration_seconds=5.0, iterations=2,
                                      tool_calls_count=4, success=True)
        assert mc.investigation_count == 1
        assert mc.tool_call_count == 4
        assert 5.0 in mc.investigation_duration_seconds

    @pytest.mark.asyncio
    async def test_record_investigation_increments_error_count_on_failure(self):
        """record_investigation(success=False) must increment error_count."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()
        await mc.record_investigation(duration_seconds=2.0, iterations=1,
                                      tool_calls_count=1, success=False)
        assert mc.error_count == 1
        assert mc.investigation_count == 1

    @pytest.mark.asyncio
    async def test_record_investigation_success_does_not_increment_errors(self):
        """Successful recording must not touch error_count."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()
        await mc.record_investigation(duration_seconds=3.0, iterations=3,
                                      tool_calls_count=6, success=True)
        assert mc.error_count == 0

    @pytest.mark.asyncio
    async def test_record_tool_call_appends_duration(self):
        """record_tool_call() must append to tool_call_duration_ms."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()
        await mc.record_tool_call("get_pod_logs", duration_ms=150, success=True)
        await mc.record_tool_call("list_pods", duration_ms=80, success=True)
        assert 150 in mc.tool_call_duration_ms
        assert 80 in mc.tool_call_duration_ms

    @pytest.mark.asyncio
    async def test_multiple_investigations_accumulate(self):
        """Running multiple investigations must accumulate all metrics."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()
        await mc.record_investigation(4.0, 2, 3, success=True)
        await mc.record_investigation(6.0, 3, 5, success=True)
        await mc.record_investigation(1.0, 1, 1, success=False)

        assert mc.investigation_count == 3
        assert mc.error_count == 1
        assert mc.tool_call_count == 9
        assert len(mc.investigation_duration_seconds) == 3


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — Prometheus text format output
# ─────────────────────────────────────────────────────────────────────────────

class TestPrometheusTextFormat:

    @pytest.mark.asyncio
    async def test_output_contains_required_metric_names(self):
        """get_prometheus_metrics() must expose all core metric names."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()
        await mc.record_investigation(3.5, 2, 4, success=True)
        await mc.record_tool_call("summarize_pod_health", 200, success=True)

        output = mc.get_prometheus_metrics()

        assert "investigation_total" in output
        assert "investigation_errors_total" in output
        assert "investigation_duration_seconds" in output
        assert "tool_call_total" in output

    @pytest.mark.asyncio
    async def test_output_has_help_and_type_lines(self):
        """Each metric block must include # HELP and # TYPE metadata lines."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()
        output = mc.get_prometheus_metrics()

        assert "# HELP" in output
        assert "# TYPE" in output

    @pytest.mark.asyncio
    async def test_counter_values_are_correct_in_output(self):
        """Metric values in the text output must match in-memory counters."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()
        await mc.record_investigation(5.0, 3, 7, success=True)
        await mc.record_investigation(2.0, 1, 2, success=False)

        output = mc.get_prometheus_metrics()

        # investigation_total should be 2
        assert "investigation_total" in output
        lines = {l.split(" ")[0]: l.split(" ")[-1]
                 for l in output.splitlines()
                 if l and not l.startswith("#")}
        # error counter should be 1
        assert lines.get("investigation_errors_total") == "1"

    @pytest.mark.asyncio
    async def test_output_contains_duration_sum_and_count(self):
        """Duration summary must include both _sum and _count lines."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()
        await mc.record_investigation(4.0, 2, 3, success=True)
        await mc.record_investigation(6.0, 2, 3, success=True)

        output = mc.get_prometheus_metrics()

        assert "investigation_duration_seconds_sum" in output
        assert "investigation_duration_seconds_count" in output

    @pytest.mark.asyncio
    async def test_output_contains_avg_tool_duration_when_present(self):
        """tool_call_duration_ms_avg should only appear after tool calls."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()

        # Before any tool calls — gauge should be absent
        output_before = mc.get_prometheus_metrics()
        assert "tool_call_duration_ms_avg" not in output_before

        await mc.record_tool_call("list_pods", 100, success=True)
        await mc.record_tool_call("get_events", 200, success=True)

        output_after = mc.get_prometheus_metrics()
        assert "tool_call_duration_ms_avg" in output_after
        # Average should be 150.00
        assert "150.00" in output_after

    def test_output_contains_app_label(self):
        """The kubesherlock app label must be present on the investigation counter."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()
        output = mc.get_prometheus_metrics()
        assert 'kubesherlock' in output


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — MetricsCollector with DB persistence
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricsCollectorWithDB:

    @pytest.mark.asyncio
    async def test_record_investigation_calls_db_record_metric(self):
        """When db is wired, record_investigation must call db.record_metric()."""
        from agent.metrics import MetricsCollector

        mock_db = AsyncMock()
        mc = MetricsCollector(db=mock_db)

        await mc.record_investigation(8.0, 4, 10, success=True)

        # Three DB metric writes expected:
        # investigation_duration_seconds, investigation_total, investigation_tool_calls_total
        assert mock_db.record_metric.await_count == 3

    @pytest.mark.asyncio
    async def test_record_investigation_persists_duration(self):
        """DB should receive the correct duration_seconds value."""
        from agent.metrics import MetricsCollector

        mock_db = AsyncMock()
        mc = MetricsCollector(db=mock_db)

        await mc.record_investigation(12.5, 3, 6, success=True)

        calls = mock_db.record_metric.await_args_list
        duration_call = next(
            (c for c in calls if c.args[0] == "investigation_duration_seconds"),
            None,
        )
        assert duration_call is not None
        assert duration_call.args[1] == 12.5

    @pytest.mark.asyncio
    async def test_record_investigation_marks_error_status(self):
        """DB should receive status='error' label when success=False."""
        from agent.metrics import MetricsCollector

        mock_db = AsyncMock()
        mc = MetricsCollector(db=mock_db)

        await mc.record_investigation(2.0, 1, 1, success=False)

        calls = mock_db.record_metric.await_args_list
        total_call = next(
            (c for c in calls if c.args[0] == "investigation_total"),
            None,
        )
        assert total_call is not None
        assert total_call.kwargs.get("labels", {}).get("status") == "error"

    @pytest.mark.asyncio
    async def test_record_tool_call_persists_to_db(self):
        """record_tool_call() must call db.record_metric() with tool label."""
        from agent.metrics import MetricsCollector

        mock_db = AsyncMock()
        mc = MetricsCollector(db=mock_db)

        await mc.record_tool_call("get_pod_logs", 175, success=True)

        mock_db.record_metric.assert_awaited_once()
        call = mock_db.record_metric.await_args
        assert call.args[0] == "tool_call_duration_ms"
        assert call.args[1] == 175
        assert call.kwargs.get("labels", {}).get("tool") == "get_pod_logs"

    @pytest.mark.asyncio
    async def test_record_tool_call_failure_writes_error_metric(self):
        """Failed tool calls must record an error metric to the DB."""
        from agent.metrics import MetricsCollector

        mock_db = AsyncMock()
        mc = MetricsCollector(db=mock_db)

        await mc.record_tool_call("describe_pod", 50, success=False)

        # Two calls: tool_call_duration_ms + tool_call_errors_total
        assert mock_db.record_metric.await_count == 2
        calls = mock_db.record_metric.await_args_list
        error_call = next(
            (c for c in calls if c.args[0] == "tool_call_errors_total"),
            None,
        )
        assert error_call is not None

    @pytest.mark.asyncio
    async def test_no_db_calls_when_db_is_none(self):
        """Without a DB, record_* methods must not crash and make no DB calls."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector(db=None)
        # Should not raise
        await mc.record_investigation(3.0, 2, 5, success=True)
        await mc.record_tool_call("list_nodes", 90, success=True)


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — FastAPI /metrics and /health endpoints
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricsEndpoints:
    """Tests for the FastAPI metrics server HTTP endpoints."""

    @pytest.fixture
    def client(self):
        """Return a FastAPI test client for the metrics server app."""
        from fastapi.testclient import TestClient
        from agent.metrics_server import app
        return TestClient(app)

    def test_health_endpoint_returns_200(self, client):
        """GET /health must return HTTP 200 with status=ok."""
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body.get("status") == "ok"

    def test_metrics_endpoint_returns_200(self, client):
        """GET /metrics must return HTTP 200."""
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_endpoint_returns_plain_text(self, client):
        """GET /metrics must return content-type text/plain."""
        response = client.get("/metrics")
        assert "text/plain" in response.headers.get("content-type", "")

    def test_metrics_endpoint_output_is_valid_prometheus_format(self, client):
        """GET /metrics output must contain # HELP and # TYPE lines."""
        response = client.get("/metrics")
        body = response.text
        assert "# HELP" in body
        assert "# TYPE" in body

    def test_metrics_endpoint_contains_investigation_counter(self, client):
        """GET /metrics must expose investigation_total metric."""
        response = client.get("/metrics")
        assert "investigation_total" in response.text

    def test_metrics_endpoint_contains_error_counter(self, client):
        """GET /metrics must expose investigation_errors_total metric."""
        response = client.get("/metrics")
        assert "investigation_errors_total" in response.text

    def test_metrics_endpoint_contains_tool_call_counter(self, client):
        """GET /metrics must expose tool_call_total metric."""
        response = client.get("/metrics")
        assert "tool_call_total" in response.text

    def test_health_endpoint_is_not_metrics_format(self, client):
        """GET /health must not return Prometheus text — it's JSON."""
        response = client.get("/health")
        # Should be JSON, not Prometheus text
        assert "# HELP" not in response.text


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — DB-backed MetricsCollector + Prometheus output end-to-end
# ─────────────────────────────────────────────────────────────────────────────

class TestEndToEndMetricsPipeline:
    """
    Simulate what the watcher does:
    1. Investigations are recorded via MetricsCollector
    2. MetricsCollector persists to DB (mocked)
    3. The /metrics endpoint reflects the in-memory counters
    """

    @pytest.mark.asyncio
    async def test_investigation_recorded_appears_in_prometheus_output(self):
        """After recording 3 investigations the output counter should read 3."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()
        await mc.record_investigation(5.0, 3, 6, success=True)
        await mc.record_investigation(3.0, 2, 4, success=True)
        await mc.record_investigation(7.0, 4, 8, success=True)

        output = mc.get_prometheus_metrics()
        lines = {
            l.split("{")[0].strip(): l.rsplit(" ", 1)[-1]
            for l in output.splitlines()
            if l and not l.startswith("#")
        }
        # investigation_total counter value (ignoring label part)
        inv_line = next(
            (l for l in output.splitlines()
             if "investigation_total" in l and not l.startswith("#")),
            ""
        )
        assert inv_line.rsplit(" ", 1)[-1] == "3"

    @pytest.mark.asyncio
    async def test_error_ratio_reflected_correctly(self):
        """2 success + 1 failure → error_count = 1, investigation_count = 3."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()
        await mc.record_investigation(1.0, 1, 2, success=True)
        await mc.record_investigation(2.0, 2, 3, success=True)
        await mc.record_investigation(0.5, 1, 1, success=False)

        output = mc.get_prometheus_metrics()
        error_line = next(
            (l for l in output.splitlines()
             if "investigation_errors_total" in l and not l.startswith("#")),
            "",
        )
        assert error_line.rsplit(" ", 1)[-1] == "1"

    @pytest.mark.asyncio
    async def test_db_write_count_matches_metric_types(self):
        """Each investigation must produce exactly 3 DB metric writes."""
        from agent.metrics import MetricsCollector

        mock_db = AsyncMock()
        mc = MetricsCollector(db=mock_db)

        await mc.record_investigation(4.0, 2, 5, success=True)

        # investigation_duration_seconds + investigation_total + investigation_tool_calls_total
        assert mock_db.record_metric.await_count == 3

    @pytest.mark.asyncio
    async def test_tool_calls_accumulate_across_investigations(self):
        """tool_call_count must be the sum across all investigations."""
        from agent.metrics import MetricsCollector

        mc = MetricsCollector()
        await mc.record_investigation(1.0, 1, 5, success=True)
        await mc.record_investigation(1.0, 1, 8, success=True)

        assert mc.tool_call_count == 13


# ─────────────────────────────────────────────────────────────────────────────
# Live integration tests (INTEGRATION_TEST=1 only)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@integration
async def test_live_metrics_server_health():
    """Live: GET /health on the running metrics server returns ok."""
    import httpx

    metrics_port = int(os.getenv("METRICS_PORT", "8000"))
    async with httpx.AsyncClient(base_url=f"http://localhost:{metrics_port}") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
@integration
async def test_live_metrics_endpoint_returns_prometheus_text():
    """Live: GET /metrics returns valid Prometheus text format."""
    import httpx

    metrics_port = int(os.getenv("METRICS_PORT", "8000"))
    async with httpx.AsyncClient(base_url=f"http://localhost:{metrics_port}") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    body = response.text
    assert "# HELP" in body
    assert "# TYPE" in body
    assert "investigation_total" in body


@pytest.mark.asyncio
@integration
async def test_live_metrics_with_db_round_trip():
    """Live: record metrics via MetricsCollector with real DB, then read back."""
    from agent.metrics import MetricsCollector
    from database.db import Database

    # Reset singleton for a clean connection
    Database._instance = None
    Database._pool = None

    db = Database()
    await db.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        database=os.getenv("DB_NAME", "kubesherlock"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )

    try:
        mc = MetricsCollector(db=db)
        await mc.record_investigation(6.0, 3, 8, success=True)
        await mc.record_tool_call("summarize_pod_health", 220, success=True)

        # Verify in-memory state
        assert mc.investigation_count == 1
        assert mc.tool_call_count == 8

        # Verify Prometheus text output
        output = mc.get_prometheus_metrics()
        assert "investigation_total" in output
        assert "investigation_duration_seconds_sum" in output

        # Verify DB persisted the metric
        rows = await db.get_metrics("investigation_duration_seconds", hours=1)
        values = [r["metric_value"] for r in rows]
        assert 6.0 in values

    finally:
        await db.disconnect()
        Database._instance = None
        Database._pool = None


@pytest.mark.asyncio
@integration
async def test_live_prometheus_server_is_reachable():
    """Live: Prometheus server at PROMETHEUS_URL is up and healthy."""
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{PROMETHEUS_URL}/-/healthy", timeout=5)

    assert response.status_code == 200


@pytest.mark.asyncio
@integration
async def test_live_prometheus_has_kubesherlock_target():
    """Live: Prometheus knows about the kubesherlock-agent scrape target."""
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{PROMETHEUS_URL}/api/v1/targets",
            timeout=10,
        )

    assert response.status_code == 200
    data = response.json()
    targets = data.get("data", {}).get("activeTargets", [])
    job_names = [t.get("labels", {}).get("job", "") for t in targets]
    assert any("kubesherlock" in j for j in job_names), (
        f"Expected a kubesherlock target in Prometheus, got jobs: {job_names}"
    )
