"""
tests/test_postgres_integration.py
===================================

PostgreSQL integration tests for the Database abstraction layer.

There are two layers of tests here:

Unit tests (always run — asyncpg fully mocked)
----------------------------------------------
These validate logic and SQL structure without needing a real database.
They are safe to run in any environment and in CI without any infra.

Live integration tests (gated behind INTEGRATION_TEST=1)
---------------------------------------------------------
These hit a real PostgreSQL instance.  They are designed to run as part
of a post-Helm-deploy smoke test with the docker-compose stack:

    docker-compose up -d
    INTEGRATION_TEST=1 pytest tests/test_postgres_integration.py -v -m integration

Environment variables used by live tests:
    DB_HOST      (default: localhost)
    DB_PORT      (default: 5432)
    DB_NAME      (default: kubesherlock)
    DB_USER      (default: postgres)
    DB_PASSWORD  (default: postgres)
    DB_SCHEMA    (default: kubesherlock)
"""

import json
import os
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

INTEGRATION = os.getenv("INTEGRATION_TEST", "0") == "1"
integration = pytest.mark.skipif(
    not INTEGRATION,
    reason="Set INTEGRATION_TEST=1 to run live DB tests",
)


def _make_mock_pool():
    """Return a mock asyncpg pool whose acquire() context manager works."""
    mock_conn = AsyncMock()
    mock_pool = MagicMock()

    # Make `async with pool.acquire()` yield mock_conn
    acquire_ctx = MagicMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_pool.acquire.return_value = acquire_ctx

    return mock_pool, mock_conn


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_db_singleton():
    """Reset the Database singleton between tests to avoid state leaking."""
    from database.db import Database
    Database._instance = None
    Database._pool = None
    yield
    Database._instance = None
    Database._pool = None


@pytest_asyncio.fixture
async def mock_db():
    """Database instance wired to a fully mocked asyncpg pool."""
    from database.db import Database

    db = Database()
    mock_pool, mock_conn = _make_mock_pool()
    db._pool = mock_pool
    return db, mock_conn


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — Connection
# ─────────────────────────────────────────────────────────────────────────────

class TestConnection:

    @pytest.mark.asyncio
    async def test_connect_creates_pool(self):
        """connect() should call asyncpg.create_pool with the right args."""
        from database.db import Database

        db = Database()
        with patch("database.db.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = MagicMock()
            await db.connect(
                host="myhost",
                port=5433,
                database="mydb",
                user="myuser",
                password="mypass",
            )
            mock_create.assert_awaited_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["host"] == "myhost"
            assert call_kwargs["port"] == 5433
            assert call_kwargs["database"] == "mydb"
            assert call_kwargs["user"] == "myuser"
            assert call_kwargs["password"] == "mypass"
            # search_path must be pinned via server_settings so all connections
            # in the pool resolve unqualified table names to the right schema.
            assert call_kwargs["server_settings"]["search_path"] == "kubesherlock"

    @pytest.mark.asyncio
    async def test_connect_pins_search_path_to_custom_schema(self):
        """connect(schema=...) must pass that schema as the search_path."""
        from database.db import Database

        db = Database()
        with patch("database.db.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = MagicMock()
            await db.connect(schema="myapp")
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["server_settings"]["search_path"] == "myapp"

    @pytest.mark.asyncio
    async def test_connect_skips_if_pool_exists(self):
        """connect() must be idempotent — no second pool created."""
        from database.db import Database

        db = Database()
        db._pool = MagicMock()  # simulate existing pool
        with patch("database.db.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            await db.connect()
            mock_create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disconnect_closes_pool(self):
        """disconnect() should call close() on the pool and clear it."""
        from database.db import Database

        db = Database()
        mock_pool = AsyncMock()
        db._pool = mock_pool

        await db.disconnect()

        mock_pool.close.assert_awaited_once()
        assert db._pool is None

    @pytest.mark.asyncio
    async def test_disconnect_noop_when_not_connected(self):
        """disconnect() is safe to call when there is no pool."""
        from database.db import Database

        db = Database()
        db._pool = None
        # Should not raise
        await db.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — Investigations CRUD
# ─────────────────────────────────────────────────────────────────────────────

class TestInvestigationsCRUD:

    @pytest.mark.asyncio
    async def test_create_investigation_returns_id(self, mock_db):
        """create_investigation() should issue an INSERT and return the scalar ID."""
        db, mock_conn = mock_db
        mock_conn.fetchval = AsyncMock(return_value=42)

        result = await db.create_investigation(
            question="Why is pod X crashing?",
            namespace="production",
            resource_name="pod-x",
            provider="openai",
        )

        assert result == 42
        mock_conn.fetchval.assert_awaited_once()
        sql = mock_conn.fetchval.call_args.args[0]
        assert "INSERT INTO investigations" in sql
        assert "RETURNING id" in sql

    @pytest.mark.asyncio
    async def test_update_investigation_builds_correct_sql(self, mock_db):
        """update_investigation() should include only the fields that are provided."""
        db, mock_conn = mock_db
        mock_conn.execute = AsyncMock()

        await db.update_investigation(
            investigation_id=1,
            answer="OOMKilled due to high memory usage",
            iterations=3,
            status="completed",
        )

        mock_conn.execute.assert_awaited_once()
        sql = mock_conn.execute.call_args.args[0]
        assert "UPDATE investigations" in sql
        assert "answer" in sql
        assert "iterations" in sql
        assert "status" in sql
        # Fields not passed should not appear
        assert "root_cause" not in sql

    @pytest.mark.asyncio
    async def test_get_investigation_returns_dict(self, mock_db):
        """get_investigation() should return a dict for an existing row."""
        db, mock_conn = mock_db
        fake_row = {"id": 7, "question": "test?", "namespace": "default",
                    "resource_name": "pod-abc", "answer": "answer", "status": "completed"}
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        result = await db.get_investigation(7)

        assert result is not None
        assert result["id"] == 7
        assert result["namespace"] == "default"
        mock_conn.fetchrow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_investigation_returns_none_for_missing(self, mock_db):
        """get_investigation() should return None when no row matches."""
        db, mock_conn = mock_db
        mock_conn.fetchrow = AsyncMock(return_value=None)

        result = await db.get_investigation(9999)
        assert result is None

    @pytest.mark.asyncio
    async def test_search_investigations_no_filters(self, mock_db):
        """search_investigations() with no filters should still execute and return list."""
        db, mock_conn = mock_db
        mock_conn.fetch = AsyncMock(return_value=[
            {"id": 1, "question": "q1", "namespace": "ns1", "resource_name": "pod-1",
             "answer": "a1", "status": "completed"},
        ])

        results = await db.search_investigations()

        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0]["id"] == 1

    @pytest.mark.asyncio
    async def test_search_investigations_with_namespace_filter(self, mock_db):
        """search_investigations() should include namespace in the query."""
        db, mock_conn = mock_db
        mock_conn.fetch = AsyncMock(return_value=[])

        await db.search_investigations(namespace="production")

        sql = mock_conn.fetch.call_args.args[0]
        assert "namespace" in sql

    @pytest.mark.asyncio
    async def test_add_tool_call_serialises_arguments(self, mock_db):
        """add_tool_call() should serialise arguments to JSON."""
        db, mock_conn = mock_db
        mock_conn.execute = AsyncMock()

        args = {"pod_name": "nginx-xyz", "namespace": "default"}
        await db.add_tool_call(
            investigation_id=1,
            tool_name="get_pod_logs",
            arguments=args,
            result_summary="Found OOM error in logs",
            execution_time_ms=250,
        )

        mock_conn.execute.assert_awaited_once()
        # The serialised JSON should be in the call args
        call_args = mock_conn.execute.call_args.args
        # Fourth positional arg (index 3) is the serialised arguments
        assert json.loads(call_args[3]) == args

    @pytest.mark.asyncio
    async def test_add_finding(self, mock_db):
        """add_finding() should issue an INSERT into investigation_findings."""
        db, mock_conn = mock_db
        mock_conn.execute = AsyncMock()

        await db.add_finding(
            investigation_id=2,
            finding_type="root_cause",
            severity="HIGH",
            content="Container ran out of memory",
        )

        mock_conn.execute.assert_awaited_once()
        sql = mock_conn.execute.call_args.args[0]
        assert "investigation_findings" in sql


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — Metrics recording
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricsRecording:

    @pytest.mark.asyncio
    async def test_record_metric_with_labels(self, mock_db):
        """record_metric() should serialise labels to JSON."""
        db, mock_conn = mock_db
        mock_conn.execute = AsyncMock()

        labels = {"status": "success", "provider": "openai"}
        await db.record_metric("investigation_total", 1.0, labels=labels)

        mock_conn.execute.assert_awaited_once()
        call_args = mock_conn.execute.call_args.args
        # Third positional arg is the serialised labels
        assert json.loads(call_args[3]) == labels

    @pytest.mark.asyncio
    async def test_record_metric_without_labels(self, mock_db):
        """record_metric() should use an empty dict when labels is None."""
        db, mock_conn = mock_db
        mock_conn.execute = AsyncMock()

        await db.record_metric("tool_call_total", 5.0)

        call_args = mock_conn.execute.call_args.args
        assert json.loads(call_args[3]) == {}

    @pytest.mark.asyncio
    async def test_get_metrics_returns_list(self, mock_db):
        """get_metrics() should return a list of dicts."""
        db, mock_conn = mock_db
        mock_conn.fetch = AsyncMock(return_value=[
            {"metric_name": "investigation_total", "metric_value": 3.0,
             "labels": "{}", "timestamp": "2026-01-01T00:00:00"},
        ])

        results = await db.get_metrics("investigation_total", hours=24)

        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0]["metric_name"] == "investigation_total"

    @pytest.mark.asyncio
    async def test_get_metrics_query_contains_time_filter(self, mock_db):
        """get_metrics() SQL must include a time-window filter."""
        db, mock_conn = mock_db
        mock_conn.fetch = AsyncMock(return_value=[])

        await db.get_metrics("some_metric", hours=6)

        sql = mock_conn.fetch.call_args.args[0]
        assert "INTERVAL" in sql
        assert "metric_name" in sql


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — get_db helper
# ─────────────────────────────────────────────────────────────────────────────

class TestGetDbHelper:

    @pytest.mark.asyncio
    async def test_get_db_uses_env_vars(self):
        """get_db() should read DB_* env vars and pass them to connect()."""
        from database.db import Database

        with patch.dict(os.environ, {
            "DB_HOST": "pg-host",
            "DB_PORT": "5433",
            "DB_NAME": "testdb",
            "DB_USER": "testuser",
            "DB_PASSWORD": "testpass",
        }, clear=False):
            with patch.object(Database, "connect", new_callable=AsyncMock) as mock_connect:
                from database.db import get_db
                await get_db()
                mock_connect.assert_awaited_once_with(
                    host="pg-host",
                    port=5433,
                    database="testdb",
                    user="testuser",
                    password="testpass",
                    schema="kubesherlock",   # DB_SCHEMA defaults to kubesherlock
                )

    @pytest.mark.asyncio
    async def test_get_db_reads_db_schema_env_var(self):
        """get_db() must forward DB_SCHEMA to connect(schema=...)."""
        from database.db import Database

        with patch.dict(os.environ, {"DB_SCHEMA": "custom_schema"}, clear=False):
            with patch.object(Database, "connect", new_callable=AsyncMock) as mock_connect:
                from database.db import get_db
                await get_db()
                call_kwargs = mock_connect.call_args.kwargs
                assert call_kwargs["schema"] == "custom_schema"

    @pytest.mark.asyncio
    async def test_get_db_skips_connect_if_pool_exists(self):
        """get_db() must not reconnect if the pool is already initialised."""
        from database.db import Database, get_db

        db = Database()
        db._pool = MagicMock()

        with patch.object(Database, "connect", new_callable=AsyncMock) as mock_connect:
            result = await get_db()
            mock_connect.assert_not_awaited()
            assert result is db


# ─────────────────────────────────────────────────────────────────────────────
# Live integration tests (INTEGRATION_TEST=1 only)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@integration
async def test_live_connect_and_disconnect():
    """Live: pool connects and disconnects cleanly."""
    from database.db import Database

    db = Database()
    await db.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        database=os.getenv("DB_NAME", "kubesherlock"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )
    assert db._pool is not None
    await db.disconnect()
    assert db._pool is None


@pytest.mark.asyncio
@integration
async def test_live_investigation_full_lifecycle():
    """Live: create → update → get → search → tool_call → finding lifecycle."""
    from database.db import Database

    db = Database()
    await db.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        database=os.getenv("DB_NAME", "kubesherlock"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )

    try:
        # Create
        inv_id = await db.create_investigation(
            question="Helm integration test — why is test-pod failing?",
            namespace="helm-test",
            resource_name="test-pod",
            provider="openai",
        )
        assert isinstance(inv_id, int)
        assert inv_id > 0

        # Update
        await db.update_investigation(
            investigation_id=inv_id,
            answer="OOMKilled — memory limit too low",
            root_cause="Container exceeded 128Mi memory limit",
            recommendations="Increase memory limit to 512Mi",
            iterations=2,
            tool_calls_count=4,
            duration_seconds=12.5,
            status="completed",
        )

        # Get
        record = await db.get_investigation(inv_id)
        assert record is not None
        assert record["id"] == inv_id
        assert record["namespace"] == "helm-test"
        assert record["status"] == "completed"
        assert record["answer"] == "OOMKilled — memory limit too low"

        # Search by namespace
        results = await db.search_investigations(namespace="helm-test")
        assert any(r["id"] == inv_id for r in results)

        # Tool call
        await db.add_tool_call(
            investigation_id=inv_id,
            tool_name="get_pod_logs",
            arguments={"pod_name": "test-pod", "namespace": "helm-test"},
            result_summary="OOMKilled in container logs",
            execution_time_ms=180,
        )

        # Finding
        await db.add_finding(
            investigation_id=inv_id,
            finding_type="root_cause",
            severity="HIGH",
            content="Memory limit exceeded — OOMKilled",
        )

    finally:
        await db.disconnect()


@pytest.mark.asyncio
@integration
async def test_live_metrics_record_and_retrieve():
    """Live: record a metric, then retrieve it within the same time window."""
    from database.db import Database

    db = Database()
    await db.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        database=os.getenv("DB_NAME", "kubesherlock"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )

    try:
        metric_name = "helm_test_investigation_total"
        labels = {"status": "success", "provider": "openai", "test": "helm_integration"}

        await db.record_metric(metric_name, 1.0, labels=labels)
        await db.record_metric(metric_name, 2.0, labels={"status": "error"})

        rows = await db.get_metrics(metric_name, hours=1)
        assert len(rows) >= 2

        values = [r["metric_value"] for r in rows]
        assert 1.0 in values
        assert 2.0 in values

    finally:
        await db.disconnect()


@pytest.mark.asyncio
@integration
async def test_live_search_no_results_for_unknown_namespace():
    """Live: searching an unknown namespace must return an empty list, not an error."""
    from database.db import Database

    db = Database()
    await db.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        database=os.getenv("DB_NAME", "kubesherlock"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )

    try:
        results = await db.search_investigations(
            namespace="this-namespace-does-not-exist-xyz"
        )
        assert results == []
    finally:
        await db.disconnect()


@pytest.mark.asyncio
@integration
async def test_live_schema_isolation():
    """
    Live: all four KubeSherlock tables must exist in the 'kubesherlock'
    schema — not in 'public' or any other schema.
    Queries information_schema.tables directly to verify placement.
    """
    from database.db import Database

    db = Database()
    await db.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        database=os.getenv("DB_NAME", "kubesherlock"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
        schema=os.getenv("DB_SCHEMA", "kubesherlock"),
    )

    expected_tables = {
        "investigations",
        "investigation_findings",
        "investigation_tool_calls",
        "metrics",
    }

    try:
        # Query information_schema directly — bypasses search_path entirely
        rows = await db._execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'kubesherlock'
              AND table_type = 'BASE TABLE'
            """
        )
        found = {r["table_name"] for r in rows}
        assert expected_tables == found, (
            f"Expected tables in kubesherlock schema: {expected_tables}\n"
            f"Found: {found}"
        )

        # Also confirm none of them leaked into public
        rows_public = await db._execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = ANY($1::text[])
            """,
            list(expected_tables),
        )
        leaked = {r["table_name"] for r in rows_public}
        assert leaked == set(), (
            f"These tables leaked into the public schema: {leaked}"
        )
    finally:
        await db.disconnect()
