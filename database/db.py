"""
database.db
~~~~~~~~~~~

Minimal async database abstraction layer for investigations and metrics.

Handles connection pooling, investigations CRUD, and metrics storage.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

import asyncpg

log = logging.getLogger(__name__)


class Database:
    """Async PostgreSQL connection pool wrapper."""

    _instance: Optional["Database"] = None
    _pool: Optional[asyncpg.Pool] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def connect(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "kubesherlock",
        user: str = "postgres",
        password: str = "postgres",
        min_size: int = 5,
        max_size: int = 20,
    ) -> None:
        """Initialize connection pool."""
        if self._pool:
            return
        self._pool = await asyncpg.create_pool(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            min_size=min_size,
            max_size=max_size,
        )
        log.info("Database connected  pool_size=%d-%d", min_size, max_size)

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            log.info("Database disconnected")

    async def _execute(self, query: str, *args) -> Any:
        """Execute a query and return result."""
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def _execute_one(self, query: str, *args) -> Optional[dict]:
        """Execute a query and return first row."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    async def _execute_scalar(self, query: str, *args) -> Any:
        """Execute a query and return scalar value."""
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    # ─────────────────────────────────────────────────────────────────────
    # Investigations CRUD
    # ─────────────────────────────────────────────────────────────────────

    async def create_investigation(
        self,
        question: str,
        namespace: Optional[str] = None,
        resource_name: Optional[str] = None,
        provider: str = "anthropic",
    ) -> int:
        """Create a new investigation record. Returns investigation ID."""
        query = """
        INSERT INTO investigations (question, namespace, resource_name, provider, status)
        VALUES ($1, $2, $3, $4, 'in_progress')
        RETURNING id
        """
        return await self._execute_scalar(query, question, namespace, resource_name, provider)

    async def update_investigation(
        self,
        investigation_id: int,
        root_cause: Optional[str] = None,
        recommendations: Optional[str] = None,
        answer: Optional[str] = None,
        iterations: Optional[int] = None,
        tool_calls_count: Optional[int] = None,
        duration_seconds: Optional[float] = None,
        status: str = "completed",
    ) -> None:
        """Update investigation with results."""
        updates = []
        params = [investigation_id]
        idx = 2

        if root_cause is not None:
            updates.append(f"root_cause = ${idx}")
            params.append(root_cause)
            idx += 1
        if recommendations is not None:
            updates.append(f"recommendations = ${idx}")
            params.append(recommendations)
            idx += 1
        if answer is not None:
            updates.append(f"answer = ${idx}")
            params.append(answer)
            idx += 1
        if iterations is not None:
            updates.append(f"iterations = ${idx}")
            params.append(iterations)
            idx += 1
        if tool_calls_count is not None:
            updates.append(f"tool_calls_count = ${idx}")
            params.append(tool_calls_count)
            idx += 1
        if duration_seconds is not None:
            updates.append(f"duration_seconds = ${idx}")
            params.append(duration_seconds)
            idx += 1

        updates.append(f"status = ${idx}")
        params.append(status)
        updates.append(f"updated_at = CURRENT_TIMESTAMP")

        query = f"UPDATE investigations SET {', '.join(updates)} WHERE id = $1"
        async with self._pool.acquire() as conn:
            await conn.execute(query, *params)

    async def get_investigation(self, investigation_id: int) -> Optional[dict]:
        """Fetch a single investigation."""
        query = "SELECT * FROM investigations WHERE id = $1"
        return await self._execute_one(query, investigation_id)

    async def search_investigations(
        self,
        namespace: Optional[str] = None,
        resource_name: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """Search past investigations. Used for context/memory."""
        query = "SELECT * FROM investigations WHERE 1=1"
        params = []
        idx = 1

        if namespace:
            query += f" AND namespace = ${idx}"
            params.append(namespace)
            idx += 1
        if resource_name:
            query += f" AND resource_name = ${idx}"
            params.append(resource_name)
            idx += 1

        query += " ORDER BY created_at DESC LIMIT $" + str(idx)
        params.append(limit)

        rows = await self._execute(query, *params)
        return [dict(row) for row in rows]

    async def add_tool_call(
        self,
        investigation_id: int,
        tool_name: str,
        arguments: dict,
        result_summary: str,
        execution_time_ms: int,
    ) -> None:
        """Record a tool call for an investigation."""
        query = """
        INSERT INTO investigation_tool_calls 
        (investigation_id, tool_name, arguments, result_summary, execution_time_ms)
        VALUES ($1, $2, $3, $4, $5)
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                query,
                investigation_id,
                tool_name,
                json.dumps(arguments),
                result_summary,
                execution_time_ms,
            )

    async def add_finding(
        self,
        investigation_id: int,
        finding_type: str,
        severity: str,
        content: str,
    ) -> None:
        """Record a finding from an investigation."""
        query = """
        INSERT INTO investigation_findings 
        (investigation_id, finding_type, severity, content)
        VALUES ($1, $2, $3, $4)
        """
        async with self._pool.acquire() as conn:
            await conn.execute(query, investigation_id, finding_type, severity, content)

    # ─────────────────────────────────────────────────────────────────────
    # Metrics
    # ─────────────────────────────────────────────────────────────────────

    async def record_metric(
        self,
        metric_name: str,
        metric_value: float,
        labels: Optional[dict] = None,
    ) -> None:
        """Record a metric value."""
        query = """
        INSERT INTO metrics (metric_name, metric_value, labels)
        VALUES ($1, $2, $3)
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                query,
                metric_name,
                metric_value,
                json.dumps(labels or {}),
            )

    async def get_metrics(
        self,
        metric_name: str,
        hours: int = 24,
    ) -> list[dict]:
        """Fetch metrics from last N hours."""
        query = """
        SELECT metric_name, metric_value, labels, timestamp
        FROM metrics
        WHERE metric_name = $1 AND timestamp > NOW() - INTERVAL '1 hour' * $2
        ORDER BY timestamp DESC
        LIMIT 1000
        """
        rows = await self._execute(query, metric_name, hours)
        return [dict(row) for row in rows]


# Singleton access
async def get_db() -> Database:
    """Get or create the database singleton."""
    db = Database()
    if db._pool is None:
        await db.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
            database=os.getenv("DB_NAME", "kubesherlock"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres"),
        )
    return db
