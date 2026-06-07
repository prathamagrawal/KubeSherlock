"""
agent.llm
~~~~~~~~~

LLM provider abstraction for the ReAct loop.

Both Anthropic and OpenAI are supported. The investigator works with a
unified response format regardless of provider.

Unified response:
    LLMResponse(
        text:       str | None        # final text answer (if no tool calls)
        tool_calls: list[ToolCall]    # tool calls requested by the model
        raw:        any               # original SDK response (for message history)
    )
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """A single tool call requested by the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    text: str | None
    tool_calls: list[ToolCall]
    raw: Any  # original SDK response object


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    @abstractmethod
    def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send a chat request and return a unified response."""

    @abstractmethod
    def build_tool_result_message(
        self, tool_calls: list[ToolCall], results: list[str]
    ) -> dict:
        """Build the message to send back after tool execution."""

    @abstractmethod
    def assistant_message(self, raw: Any) -> dict:
        """Convert a raw LLM response to an assistant message dict."""


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

class AnthropicProvider(LLMProvider):
    """Claude via the Anthropic SDK.

    Args:
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
        model: Claude model name.
    """

    DEFAULT_MODEL = "claude-sonnet-4-5"

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL) -> None:
        import anthropic
        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ["ANTHROPIC_API_KEY"]
        )
        self._model = model

    def chat(self, system, messages, tools, max_tokens=4096) -> LLMResponse:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )
        log.debug("Anthropic response  stop_reason=%s", response.stop_reason)

        if response.stop_reason == "end_turn":
            text = "\n".join(
                b.text for b in response.content if hasattr(b, "text")
            ).strip()
            return LLMResponse(text=text, tool_calls=[], raw=response)

        tool_calls = [
            ToolCall(id=b.id, name=b.name, arguments=b.input)
            for b in response.content
            if b.type == "tool_use"
        ]
        return LLMResponse(text=None, tool_calls=tool_calls, raw=response)

    def build_tool_result_message(self, tool_calls, results) -> dict:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result,
                }
                for tc, result in zip(tool_calls, results)
            ],
        }

    def assistant_message(self, raw) -> dict:
        return {"role": "assistant", "content": raw.content}


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

class OpenAIProvider(LLMProvider):
    """GPT via the OpenAI SDK.

    Converts MCP tool schemas (JSON Schema style) to OpenAI function format.

    Args:
        api_key: OpenAI API key. Falls back to OPENAI_API_KEY env var.
        model: OpenAI model name.
    """

    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL) -> None:
        from openai import OpenAI
        self._client = OpenAI(
            api_key=api_key or os.environ["OPENAI_API_KEY"]
        )
        self._model = model

    def chat(self, system, messages, tools, max_tokens=4096) -> LLMResponse:
        oai_tools = [_to_openai_tool(t) for t in tools]
        oai_messages = [{"role": "system", "content": system}] + messages

        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            tools=oai_tools or None,
            tool_choice="auto" if oai_tools else None,
            messages=oai_messages,
        )
        msg = response.choices[0].message
        log.debug("OpenAI response  finish_reason=%s", response.choices[0].finish_reason)

        if response.choices[0].finish_reason == "stop" or not msg.tool_calls:
            return LLMResponse(text=msg.content or "", tool_calls=[], raw=response)

        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments),
            )
            for tc in msg.tool_calls
        ]
        return LLMResponse(text=None, tool_calls=tool_calls, raw=response)

    def build_tool_result_message(self, tool_calls, results) -> dict:
        # OpenAI expects one message per tool result
        # We return the first; caller must handle multiple
        # Actually OpenAI accepts them as separate messages — we bundle into list
        return {
            "_multi": [
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                }
                for tc, result in zip(tool_calls, results)
            ]
        }

    def assistant_message(self, raw) -> dict:
        msg = raw.choices[0].message
        return {
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in (msg.tool_calls or [])
            ] or None,
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_provider(provider: str, **kwargs) -> LLMProvider:
    """Instantiate an LLM provider by name.

    Args:
        provider: ``"anthropic"`` or ``"openai"``.
        **kwargs: Passed to the provider constructor (api_key, model).

    Returns:
        Configured :class:`LLMProvider` instance.
    """
    providers = {
        "anthropic": AnthropicProvider,
        "openai": OpenAIProvider,
    }
    if provider not in providers:
        raise ValueError(f"Unknown provider {provider!r}. Choose from: {list(providers)}")
    return providers[provider](**kwargs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_openai_tool(mcp_tool: dict) -> dict:
    """Convert an MCP tool definition to OpenAI function format."""
    return {
        "type": "function",
        "function": {
            "name": mcp_tool["name"],
            "description": mcp_tool.get("description", ""),
            "parameters": mcp_tool.get("input_schema", {"type": "object", "properties": {}}),
        },
    }
