"""
tests.test_llm
~~~~~~~~~~~~~~

Unit tests for agent/llm.py — LLM provider abstraction.

All external SDK calls (anthropic, openai) are mocked.
No live API calls are made.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent.llm import (
    AnthropicProvider,
    LLMResponse,
    OpenAIProvider,
    ToolCall,
    _to_openai_tool,
    create_provider,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_anthropic_text_response(text="The pod is OOMKilled."):
    """Fake Anthropic end_turn response."""
    block = MagicMock()
    block.text = text
    block.type = "text"
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    return resp


def _make_anthropic_tool_response(tool_id="t1", tool_name="list_pods", arguments=None):
    """Fake Anthropic tool_use response."""
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = tool_name
    block.input = arguments or {"namespace": "default"}
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [block]
    return resp


def _make_openai_text_response(text="Root cause: OOM."):
    """Fake OpenAI stop response."""
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = None
    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_openai_tool_response(tool_id="tc1", name="describe_pod", args=None):
    """Fake OpenAI tool_calls response."""
    tc = MagicMock()
    tc.id = tool_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args or {"namespace": "default", "pod_name": "my-pod"})
    msg = MagicMock()
    msg.content = None
    msg.tool_calls = [tc]
    choice = MagicMock()
    choice.finish_reason = "tool_calls"
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# AnthropicProvider
# ─────────────────────────────────────────────────────────────────────────────

class TestAnthropicProvider:

    def _make_provider(self):
        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_anthropic.return_value = MagicMock()
            provider = AnthropicProvider(api_key="test-key")
            provider._client = MagicMock()
            return provider

    def test_chat_end_turn_returns_text(self):
        provider = self._make_provider()
        provider._client.messages.create.return_value = _make_anthropic_text_response("All good.")
        result = provider.chat("system", [], [])
        assert isinstance(result, LLMResponse)
        assert result.text == "All good."
        assert result.tool_calls == []

    def test_chat_tool_use_returns_tool_calls(self):
        provider = self._make_provider()
        provider._client.messages.create.return_value = _make_anthropic_tool_response(
            tool_id="abc", tool_name="list_pods", arguments={"namespace": "kube-system"}
        )
        result = provider.chat("system", [], [])
        assert result.text is None
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert isinstance(tc, ToolCall)
        assert tc.id == "abc"
        assert tc.name == "list_pods"
        assert tc.arguments == {"namespace": "kube-system"}

    def test_chat_passes_system_and_tools(self):
        provider = self._make_provider()
        provider._client.messages.create.return_value = _make_anthropic_text_response()
        tools = [{"name": "list_pods", "description": "...", "input_schema": {}}]
        provider.chat("my-system", [{"role": "user", "content": "hi"}], tools)
        call_kwargs = provider._client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "my-system"
        assert call_kwargs["tools"] == tools

    def test_build_tool_result_message_single(self):
        provider = self._make_provider()
        tc = ToolCall(id="t1", name="list_pods", arguments={})
        msg = provider.build_tool_result_message([tc], ["result-1"])
        assert msg["role"] == "user"
        assert len(msg["content"]) == 1
        assert msg["content"][0]["tool_use_id"] == "t1"
        assert msg["content"][0]["content"] == "result-1"
        assert msg["content"][0]["type"] == "tool_result"

    def test_build_tool_result_message_multiple(self):
        provider = self._make_provider()
        tcs = [ToolCall(id=f"t{i}", name="tool", arguments={}) for i in range(3)]
        msg = provider.build_tool_result_message(tcs, ["r0", "r1", "r2"])
        assert len(msg["content"]) == 3
        assert msg["content"][2]["tool_use_id"] == "t2"
        assert msg["content"][2]["content"] == "r2"

    def test_assistant_message_returns_role_and_content(self):
        provider = self._make_provider()
        raw = _make_anthropic_text_response()
        msg = provider.assistant_message(raw)
        assert msg["role"] == "assistant"
        assert msg["content"] == raw.content


# ─────────────────────────────────────────────────────────────────────────────
# OpenAIProvider
# ─────────────────────────────────────────────────────────────────────────────

class TestOpenAIProvider:

    def _make_provider(self):
        with patch("openai.OpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            provider = OpenAIProvider(api_key="test-key")
            provider._client = MagicMock()
            return provider

    def test_chat_stop_returns_text(self):
        provider = self._make_provider()
        provider._client.chat.completions.create.return_value = _make_openai_text_response("Root cause found.")
        result = provider.chat("system", [], [])
        assert isinstance(result, LLMResponse)
        assert result.text == "Root cause found."
        assert result.tool_calls == []

    def test_chat_tool_calls_returns_tool_calls(self):
        provider = self._make_provider()
        provider._client.chat.completions.create.return_value = _make_openai_tool_response(
            tool_id="tc1", name="describe_pod", args={"namespace": "prod", "pod_name": "web-0"}
        )
        result = provider.chat("system", [], [{"name": "describe_pod"}])
        assert result.text is None
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.id == "tc1"
        assert tc.name == "describe_pod"
        assert tc.arguments == {"namespace": "prod", "pod_name": "web-0"}

    def test_chat_prepends_system_message(self):
        provider = self._make_provider()
        provider._client.chat.completions.create.return_value = _make_openai_text_response()
        provider.chat("my-system", [{"role": "user", "content": "hello"}], [])
        call_kwargs = provider._client.chat.completions.create.call_args.kwargs
        msgs = call_kwargs["messages"]
        assert msgs[0] == {"role": "system", "content": "my-system"}
        assert msgs[1] == {"role": "user", "content": "hello"}

    def test_chat_empty_tools_passes_none(self):
        provider = self._make_provider()
        provider._client.chat.completions.create.return_value = _make_openai_text_response()
        provider.chat("sys", [], [])
        call_kwargs = provider._client.chat.completions.create.call_args.kwargs
        assert call_kwargs["tools"] is None
        assert call_kwargs["tool_choice"] is None

    def test_build_tool_result_message_returns_multi(self):
        provider = self._make_provider()
        tcs = [ToolCall(id="tc1", name="t", arguments={}), ToolCall(id="tc2", name="t2", arguments={})]
        msg = provider.build_tool_result_message(tcs, ["res1", "res2"])
        assert "_multi" in msg
        multi = msg["_multi"]
        assert len(multi) == 2
        assert multi[0] == {"role": "tool", "tool_call_id": "tc1", "content": "res1"}
        assert multi[1] == {"role": "tool", "tool_call_id": "tc2", "content": "res2"}

    def test_assistant_message_with_tool_calls(self):
        provider = self._make_provider()
        raw = _make_openai_tool_response()
        msg = provider.assistant_message(raw)
        assert msg["role"] == "assistant"
        assert msg["tool_calls"] is not None
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["type"] == "function"

    def test_assistant_message_without_tool_calls(self):
        provider = self._make_provider()
        raw = _make_openai_text_response("Final answer.")
        msg = provider.assistant_message(raw)
        assert msg["role"] == "assistant"
        assert msg["content"] == "Final answer."
        # tool_calls is None or empty list when no tool calls
        assert not msg.get("tool_calls")


# ─────────────────────────────────────────────────────────────────────────────
# create_provider factory
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateProvider:

    def test_anthropic_returns_anthropic_provider(self):
        with patch("anthropic.Anthropic"):
            p = create_provider("anthropic", api_key="sk-ant")
        assert isinstance(p, AnthropicProvider)

    def test_openai_returns_openai_provider(self):
        with patch("openai.OpenAI"):
            p = create_provider("openai", api_key="sk-openai")
        assert isinstance(p, OpenAIProvider)

    def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("gemini")

    def test_error_message_lists_valid_providers(self):
        with pytest.raises(ValueError) as exc_info:
            create_provider("xyz")
        assert "anthropic" in str(exc_info.value)
        assert "openai" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────────────────────
# _to_openai_tool helper
# ─────────────────────────────────────────────────────────────────────────────

class TestToOpenAITool:

    def test_correct_function_format(self):
        mcp_tool = {
            "name": "list_pods",
            "description": "List pods in a namespace",
            "input_schema": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
            },
        }
        result = _to_openai_tool(mcp_tool)
        assert result["type"] == "function"
        assert result["function"]["name"] == "list_pods"
        assert result["function"]["description"] == "List pods in a namespace"
        assert result["function"]["parameters"]["properties"]["namespace"]["type"] == "string"

    def test_missing_description_defaults_to_empty_string(self):
        mcp_tool = {"name": "no_desc", "input_schema": {"type": "object", "properties": {}}}
        result = _to_openai_tool(mcp_tool)
        assert result["function"]["description"] == ""

    def test_missing_input_schema_defaults_to_empty_object(self):
        mcp_tool = {"name": "no_schema", "description": "desc"}
        result = _to_openai_tool(mcp_tool)
        assert result["function"]["parameters"] == {"type": "object", "properties": {}}

    def test_name_preserved_exactly(self):
        mcp_tool = {"name": "get_pod_logs", "description": "", "input_schema": {}}
        result = _to_openai_tool(mcp_tool)
        assert result["function"]["name"] == "get_pod_logs"
