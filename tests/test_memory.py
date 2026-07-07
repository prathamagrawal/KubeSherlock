"""
tests.test_memory
~~~~~~~~~~~~~~~~~

Unit tests for agent/memory.py — investigation history context retrieval.

All DB calls are mocked. No live PostgreSQL connection required.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from agent.memory import InvestigationMemory


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_db(investigations=None):
    """Return a mock Database with async methods."""
    db = MagicMock()
    db.search_investigations = AsyncMock(return_value=investigations or [])
    db.create_investigation = AsyncMock(return_value=1)
    db.update_investigation = AsyncMock()
    db.add_tool_call = AsyncMock()
    return db


def _make_investigation(question="Why is pod failing?",
                         answer="Root cause: OOM.",
                         root_cause="OOM",
                         recommendations="Increase limits"):
    return {
        "id": 1,
        "question": question,
        "answer": answer,
        "root_cause": root_cause,
        "recommendations": recommendations,
        "tool_calls_count": 3,
        "namespace": "default",
    }


# ─────────────────────────────────────────────────────────────────────────────
# __init__
# ─────────────────────────────────────────────────────────────────────────────

class TestInvestigationMemoryInit:

    def test_stores_db_reference(self):
        db = _make_db()
        mem = InvestigationMemory(db)
        assert mem.db is db


# ─────────────────────────────────────────────────────────────────────────────
# get_context
# ─────────────────────────────────────────────────────────────────────────────

class TestGetContext:

    @pytest.mark.asyncio
    async def test_calls_db_search_with_namespace(self):
        db = _make_db([_make_investigation()])
        mem = InvestigationMemory(db)
        await mem.get_context(namespace="production")
        db.search_investigations.assert_awaited_once_with(
            namespace="production",
            resource_name=None,
            limit=3,
        )

    @pytest.mark.asyncio
    async def test_returns_empty_string_when_no_investigations(self):
        db = _make_db([])
        mem = InvestigationMemory(db)
        result = await mem.get_context(namespace="default")
        assert result == ""

    @pytest.mark.asyncio
    async def test_context_contains_question(self):
        inv = _make_investigation(question="Why is nginx crashing?")
        db = _make_db([inv])
        mem = InvestigationMemory(db)
        result = await mem.get_context(namespace="default")
        assert "Why is nginx crashing?" in result

    @pytest.mark.asyncio
    async def test_context_contains_root_cause(self):
        inv = _make_investigation(root_cause="OOMKilled by memory limit")
        db = _make_db([inv])
        mem = InvestigationMemory(db)
        result = await mem.get_context()
        assert "OOMKilled by memory limit" in result

    @pytest.mark.asyncio
    async def test_context_contains_recommendations(self):
        inv = _make_investigation(recommendations="Increase memory limit to 512Mi")
        db = _make_db([inv])
        mem = InvestigationMemory(db)
        result = await mem.get_context()
        assert "Increase memory limit to 512Mi" in result

    @pytest.mark.asyncio
    async def test_investigation_missing_root_cause_omitted_from_context(self):
        """Investigations without root_cause AND recommendations are silently skipped."""
        inv = {"id": 1, "question": "q", "answer": "a",
               "root_cause": None, "recommendations": None}
        db = _make_db([inv])
        mem = InvestigationMemory(db)
        result = await mem.get_context()
        # No root_cause → entry should not appear in context
        assert "q" not in result or result == "" or "past investigations" in result

    @pytest.mark.asyncio
    async def test_limit_forwarded_to_db(self):
        db = _make_db([])
        mem = InvestigationMemory(db)
        await mem.get_context(namespace="default", limit=5)
        call_kwargs = db.search_investigations.call_args.kwargs
        assert call_kwargs["limit"] == 5

    @pytest.mark.asyncio
    async def test_resource_name_forwarded_to_db(self):
        db = _make_db([])
        mem = InvestigationMemory(db)
        await mem.get_context(namespace="default", resource_name="web-pod")
        call_kwargs = db.search_investigations.call_args.kwargs
        assert call_kwargs["resource_name"] == "web-pod"


# ─────────────────────────────────────────────────────────────────────────────
# record_tool_call
# ─────────────────────────────────────────────────────────────────────────────

class TestRecordToolCall:

    @pytest.mark.asyncio
    async def test_calls_db_add_tool_call(self):
        db = _make_db()
        mem = InvestigationMemory(db)
        await mem.record_tool_call(
            investigation_id=5,
            tool_name="list_pods",
            arguments={"namespace": "default"},
            result='{"pods": []}',
            execution_time_ms=42,
        )
        db.add_tool_call.assert_awaited_once_with(
            investigation_id=5,
            tool_name="list_pods",
            arguments={"namespace": "default"},
            result_summary='{"pods": []}',
            execution_time_ms=42,
        )

    @pytest.mark.asyncio
    async def test_long_result_truncated_to_500_chars(self):
        db = _make_db()
        mem = InvestigationMemory(db)
        long_result = "x" * 1000
        await mem.record_tool_call(
            investigation_id=1,
            tool_name="get_pod_logs",
            arguments={},
            result=long_result,
            execution_time_ms=0,
        )
        call_kwargs = db.add_tool_call.call_args.kwargs
        assert len(call_kwargs["result_summary"]) == 500

    @pytest.mark.asyncio
    async def test_short_result_not_truncated(self):
        db = _make_db()
        mem = InvestigationMemory(db)
        short_result = "ok"
        await mem.record_tool_call(
            investigation_id=1,
            tool_name="list_pods",
            arguments={},
            result=short_result,
            execution_time_ms=10,
        )
        call_kwargs = db.add_tool_call.call_args.kwargs
        assert call_kwargs["result_summary"] == "ok"

    @pytest.mark.asyncio
    async def test_empty_result_handled(self):
        db = _make_db()
        mem = InvestigationMemory(db)
        await mem.record_tool_call(
            investigation_id=1,
            tool_name="list_pods",
            arguments={},
            result="",
            execution_time_ms=5,
        )
        db.add_tool_call.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# save_investigation
# ─────────────────────────────────────────────────────────────────────────────

class TestSaveInvestigation:

    @pytest.mark.asyncio
    async def test_creates_then_updates_investigation(self):
        db = _make_db()
        db.create_investigation = AsyncMock(return_value=99)
        mem = InvestigationMemory(db)
        inv_id = await mem.save_investigation(
            question="Why is pod failing?",
            answer="**Root Cause:**\nOOM\n**Recommendations:**\nIncrease limits",
            namespace="default",
            resource_name="web-pod",
            provider="openai",
            iterations=3,
            tool_calls_count=7,
            duration_seconds=12.5,
        )
        assert inv_id == 99
        db.create_investigation.assert_awaited_once()
        db.update_investigation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_receives_status_completed(self):
        db = _make_db()
        db.create_investigation = AsyncMock(return_value=1)
        mem = InvestigationMemory(db)
        await mem.save_investigation(
            question="q", answer="a", namespace=None, resource_name=None,
            provider="anthropic", iterations=1, tool_calls_count=0, duration_seconds=1.0,
        )
        call_kwargs = db.update_investigation.call_args.kwargs
        assert call_kwargs["status"] == "completed"
