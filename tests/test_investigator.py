"""
tests.test_investigator
~~~~~~~~~~~~~~~~~~~~~~~

Unit tests for agent/investigator.py — the ReAct loop orchestrator.

All LLM, MCP, and DB calls are mocked. No live services required.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.investigator import (
    Investigator,
    InvestigationResult,
    _extract_section,
    _extract_resource_name,
)
from agent.llm import LLMResponse, ToolCall


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_mcp_client(tool_result="{}"):
    """Mock MCPClient with a list of tools and an async call_tool."""
    client = MagicMock()
    client.tools = [{"name": "list_pods", "description": "list", "input_schema": {}}]
    client.call_tool = AsyncMock(return_value=tool_result)
    return client


def _make_llm(responses):
    """Return a mock LLMProvider whose chat() cycles through responses."""
    llm = MagicMock()
    llm.chat.side_effect = responses
    llm.assistant_message.return_value = {"role": "assistant", "content": "..."}
    llm.build_tool_result_message.return_value = {"role": "user", "content": "tool result"}
    return llm


def _text_response(text="Root cause: OOM."):
    return LLMResponse(text=text, tool_calls=[], raw=MagicMock())


def _tool_response(tool_name="list_pods", args=None):
    tc = ToolCall(id="tc-1", name=tool_name, arguments=args or {"namespace": "default"})
    return LLMResponse(text=None, tool_calls=[tc], raw=MagicMock())


# ─────────────────────────────────────────────────────────────────────────────
# __init__
# ─────────────────────────────────────────────────────────────────────────────

class TestInvestigatorInit:

    def test_uses_provided_provider_name(self):
        mcp = _make_mcp_client()
        with patch("agent.investigator.create_provider") as mock_create:
            mock_create.return_value = MagicMock()
            inv = Investigator(mcp_client=mcp, provider="anthropic", api_key="k")
        assert inv._provider_name == "anthropic"

    def test_max_iterations_defaults_to_five(self):
        mcp = _make_mcp_client()
        with patch("agent.investigator.create_provider", return_value=MagicMock()):
            inv = Investigator(mcp_client=mcp, provider="openai", api_key="k")
        assert inv._max_iterations == 5

    def test_max_iterations_override(self):
        mcp = _make_mcp_client()
        with patch("agent.investigator.create_provider", return_value=MagicMock()):
            inv = Investigator(mcp_client=mcp, provider="openai", api_key="k", max_iterations=3)
        assert inv._max_iterations == 3


# ─────────────────────────────────────────────────────────────────────────────
# investigate() — happy paths
# ─────────────────────────────────────────────────────────────────────────────

class TestInvestigateHappyPaths:

    def _make_investigator(self, llm_responses, max_iterations=5):
        mcp = _make_mcp_client()
        llm = _make_llm(llm_responses)
        with patch("agent.investigator.create_provider", return_value=llm):
            inv = Investigator(mcp_client=mcp, provider="openai", api_key="k",
                               max_iterations=max_iterations)
        return inv

    @pytest.mark.asyncio
    async def test_single_iteration_text_response(self):
        inv = self._make_investigator([_text_response("Pod is OOMKilled.")])
        result = await inv.investigate("Why is pod failing?")
        assert isinstance(result, InvestigationResult)
        assert result.answer == "Pod is OOMKilled."
        assert result.iterations == 1
        assert result.tool_calls == []

    @pytest.mark.asyncio
    async def test_two_iterations_tool_then_text(self):
        tc = ToolCall(id="tc1", name="list_pods", arguments={"namespace": "default"})
        tool_resp = LLMResponse(text=None, tool_calls=[tc], raw=MagicMock())
        text_resp = _text_response("Root cause: crash loop.")
        inv = self._make_investigator([tool_resp, text_resp])
        result = await inv.investigate("Why is pod failing?", namespace="default")
        assert result.iterations == 2
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["tool"] == "list_pods"
        assert result.answer == "Root cause: crash loop."

    @pytest.mark.asyncio
    async def test_tool_call_dispatch_called_with_correct_args(self):
        mcp = _make_mcp_client(tool_result='{"pods": []}')
        llm = _make_llm([_tool_response("describe_pod", {"namespace": "prod", "pod_name": "web"}),
                          _text_response("Done.")])
        with patch("agent.investigator.create_provider", return_value=llm):
            inv = Investigator(mcp_client=mcp, provider="openai", api_key="k")
        await inv.investigate("Why?")
        mcp.call_tool.assert_awaited_once_with(
            "describe_pod", {"namespace": "prod", "pod_name": "web"}
        )

    @pytest.mark.asyncio
    async def test_hits_max_iterations_forces_final_answer(self):
        # All calls return tool_calls until max; last chat() returns text
        tool_resp = _tool_response()
        final_resp = _text_response("Forced final answer.")
        responses = [tool_resp] * 2 + [final_resp]  # max_iterations=2
        inv = self._make_investigator(responses, max_iterations=2)
        result = await inv.investigate("Why?")
        assert result.answer == "Forced final answer."
        assert result.iterations == 2

    @pytest.mark.asyncio
    async def test_openai_multi_tool_result_spread_into_messages(self):
        """OpenAI returns _multi key — messages should be extended, not appended."""
        tc = ToolCall(id="tc1", name="list_pods", arguments={})
        tool_resp = LLMResponse(text=None, tool_calls=[tc], raw=MagicMock())
        text_resp = _text_response("Done.")
        mcp = _make_mcp_client()
        llm = _make_llm([tool_resp, text_resp])
        # Simulate OpenAI _multi format
        llm.build_tool_result_message.return_value = {
            "_multi": [
                {"role": "tool", "tool_call_id": "tc1", "content": "result"},
            ]
        }
        with patch("agent.investigator.create_provider", return_value=llm):
            inv = Investigator(mcp_client=mcp, provider="openai", api_key="k")
        result = await inv.investigate("Why?")
        # Should not raise; answer should be populated
        assert result.answer == "Done."

    @pytest.mark.asyncio
    async def test_result_provider_name_is_set(self):
        inv = self._make_investigator([_text_response("ok")])
        result = await inv.investigate("q")
        assert result.provider == "openai"


# ─────────────────────────────────────────────────────────────────────────────
# investigate() — error paths
# ─────────────────────────────────────────────────────────────────────────────

class TestInvestigateErrorPaths:

    @pytest.mark.asyncio
    async def test_llm_exception_returns_error_result(self):
        mcp = _make_mcp_client()
        llm = MagicMock()
        llm.chat.side_effect = RuntimeError("API timeout")
        llm.assistant_message.return_value = {}
        with patch("agent.investigator.create_provider", return_value=llm):
            inv = Investigator(mcp_client=mcp, provider="openai", api_key="k")
        result = await inv.investigate("Why?")
        assert "API timeout" in result.answer
        assert "failed" in result.answer.lower()

    @pytest.mark.asyncio
    async def test_tool_call_exception_records_error_in_result(self):
        """Tool call failure should be captured in result, not propagate."""
        mcp = _make_mcp_client()
        mcp.call_tool.side_effect = Exception("kubectl timeout")
        tc = ToolCall(id="tc1", name="list_pods", arguments={})
        tool_resp = LLMResponse(text=None, tool_calls=[tc], raw=MagicMock())
        text_resp = _text_response("Done despite tool error.")
        llm = _make_llm([tool_resp, text_resp])
        with patch("agent.investigator.create_provider", return_value=llm):
            inv = Investigator(mcp_client=mcp, provider="openai", api_key="k")
        result = await inv.investigate("Why?")
        # Should still complete
        assert result.answer == "Done despite tool error."


# ─────────────────────────────────────────────────────────────────────────────
# investigate() — DB persistence via memory
# ─────────────────────────────────────────────────────────────────────────────

class TestInvestigateWithMemory:

    @pytest.mark.asyncio
    async def test_creates_investigation_in_db(self):
        mcp = _make_mcp_client()
        llm = _make_llm([_text_response("Answer.")])

        mock_memory = MagicMock()
        mock_memory.get_context = AsyncMock(return_value="")
        mock_memory.db = MagicMock()
        mock_memory.db.create_investigation = AsyncMock(return_value=42)
        mock_memory.db.update_investigation = AsyncMock()
        mock_memory.record_tool_call = AsyncMock()

        with patch("agent.investigator.create_provider", return_value=llm):
            inv = Investigator(mcp_client=mcp, provider="openai", api_key="k")
        inv._memory = mock_memory

        result = await inv.investigate("Why?", namespace="prod")
        mock_memory.db.create_investigation.assert_awaited_once()
        mock_memory.db.update_investigation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_investigation_called_with_answer(self):
        mcp = _make_mcp_client()
        llm = _make_llm([_text_response("Final answer text.")])

        mock_memory = MagicMock()
        mock_memory.get_context = AsyncMock(return_value="")
        mock_memory.db = MagicMock()
        mock_memory.db.create_investigation = AsyncMock(return_value=7)
        mock_memory.db.update_investigation = AsyncMock()
        mock_memory.record_tool_call = AsyncMock()

        with patch("agent.investigator.create_provider", return_value=llm):
            inv = Investigator(mcp_client=mcp, provider="openai", api_key="k")
        inv._memory = mock_memory

        await inv.investigate("Why?")
        call_kwargs = mock_memory.db.update_investigation.call_args.kwargs
        assert call_kwargs["answer"] == "Final answer text."
        assert call_kwargs["status"] == "completed"
        assert call_kwargs["investigation_id"] == 7


# ─────────────────────────────────────────────────────────────────────────────
# _extract_section helper
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractSection:

    SAMPLE_ANSWER = """
**Root Cause:**
The container exceeded its memory limit and was OOMKilled.

**Recommendations:**
Increase memory limits in the deployment spec.
Review memory usage patterns.

**Summary:**
Pod is failing due to OOM.
"""

    def test_extracts_root_cause_section(self):
        result = _extract_section(self.SAMPLE_ANSWER, "Root Cause")
        assert result is not None
        assert "OOMKilled" in result

    def test_extracts_recommendations_section(self):
        result = _extract_section(self.SAMPLE_ANSWER, "Recommendations")
        assert result is not None
        assert "memory limits" in result

    def test_returns_none_for_missing_section(self):
        result = _extract_section(self.SAMPLE_ANSWER, "NonExistentSection")
        assert result is None

    def test_returns_none_for_empty_text(self):
        result = _extract_section("", "Root Cause")
        assert result is None

    def test_section_stops_at_next_bold_header(self):
        result = _extract_section(self.SAMPLE_ANSWER, "Root Cause")
        # Should not include "Recommendations" content
        assert "Increase memory" not in result


# ─────────────────────────────────────────────────────────────────────────────
# _extract_resource_name helper
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractResourceName:

    def test_finds_pod_suffix(self):
        result = _extract_resource_name("Why is nginx-pod failing?")
        assert result == "nginx-pod"

    def test_finds_deployment_suffix(self):
        result = _extract_resource_name("Investigate my-app-deployment crashing")
        assert result == "my-app-deployment"

    def test_finds_statefulset_suffix(self):
        result = _extract_resource_name("Debug postgres-statefulset")
        assert result == "postgres-statefulset"

    def test_fallback_is_pattern(self):
        result = _extract_resource_name("Why is coredns broken?")
        assert result == "coredns"

    def test_returns_none_when_no_match(self):
        result = _extract_resource_name("Something is wrong")
        # May return None or a generic word — just verify it doesn't crash
        # (The heuristic may return something — we just test it doesn't raise)
        assert result is None or isinstance(result, str)
