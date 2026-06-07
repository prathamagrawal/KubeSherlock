"""
agent.investigator
~~~~~~~~~~~~~~~~~~

ReAct loop orchestrator.

Provider-agnostic: works with Anthropic (Claude) or OpenAI (GPT).
The LLM provider is injected — the loop itself never imports an SDK directly.

Loop behaviour:
- Each iteration: LLM reasons, picks tools, we call them, LLM observes.
- Stops when LLM produces a final text answer (no tool calls).
- Forces a final answer after max_iterations.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from .llm import LLMProvider, create_provider
from .mcp_client import MCPClient
from .prompts import SYSTEM_PROMPT

# Lazy import to avoid circular dependency
InvestigationMemory = None

log = logging.getLogger(__name__)

MAX_ITERATIONS = 5


@dataclass
class InvestigationResult:
    """Output of a completed investigation.

    Attributes:
        question: Original user question.
        answer: Final root cause report from the agent.
        tool_calls: Ordered list of tool calls made during investigation.
        iterations: Number of ReAct iterations used.
        provider: LLM provider used (e.g. ``"anthropic"``).
    """
    question: str
    answer: str
    tool_calls: list[dict] = field(default_factory=list)
    iterations: int = 0
    provider: str = ""


class Investigator:
    """Runs the ReAct loop to investigate a Kubernetes incident.

    Args:
        mcp_client: Connected :class:`~agent.mcp_client.MCPClient` instance.
        provider: LLM provider name: ``"anthropic"`` or ``"openai"``.
        api_key: API key for the chosen provider.
        model: Model name override (uses provider default if omitted).
        max_iterations: Maximum ReAct loop iterations before forcing a final answer.
        memory: Optional InvestigationMemory for history context.
    """

    def __init__(
        self,
        mcp_client: MCPClient,
        provider: str = "anthropic",
        api_key: str | None = None,
        model: str | None = None,
        max_iterations: int = MAX_ITERATIONS,
        memory: Optional["InvestigationMemory"] = None,
    ) -> None:
        self._mcp = mcp_client
        self._max_iterations = max_iterations
        self._provider_name = provider
        self._memory = memory
        self._investigation_id: Optional[int] = None
        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if model:
            kwargs["model"] = model
        self._llm: LLMProvider = create_provider(provider, **kwargs)

    async def investigate(self, question: str, namespace: Optional[str] = None) -> InvestigationResult:
        """Investigate *question* using the ReAct loop.

        Args:
            question: Natural language question, e.g.
                ``"Why is postgres-nodes-3 crashing in the db namespace?"``
            namespace: Optional namespace for context retrieval.

        Returns:
            :class:`InvestigationResult` with the final report and call history.
        """
        log.info("Investigation started  provider=%s  question=%r",
                 self._provider_name, question)

        start_time = time.time()
        
        # Create investigation record if memory is available
        if self._memory:
            resource_name = _extract_resource_name(question)
            self._investigation_id = await self._memory.db.create_investigation(
                question=question,
                namespace=namespace,
                resource_name=resource_name,
                provider=self._provider_name,
            )

        system = SYSTEM_PROMPT.format(max_iterations=self._max_iterations)
        messages: list[dict] = [{"role": "user", "content": question}]
        
        # Add memory context if available
        if self._memory:
            context = await self._memory.get_context(namespace, limit=2)
            if context:
                system += "\n\n" + context

        tools = self._mcp.tools
        tool_calls_made: list[dict] = []
        iterations = 0

        while iterations < self._max_iterations:
            iterations += 1
            log.debug("ReAct iteration %d/%d", iterations, self._max_iterations)

            try:
                response = self._llm.chat(system, messages, tools)
            except Exception as e:
                err = str(e)
                log.error("LLM call failed: %s", err)
                return InvestigationResult(
                    question=question,
                    answer=f"Investigation failed: LLM error — {err}",
                    tool_calls=tool_calls_made,
                    iterations=iterations,
                    provider=self._provider_name,
                )

            # Append assistant turn to history
            messages.append(self._llm.assistant_message(response.raw))

            # Final answer — no tool calls
            if response.text is not None:
                log.info("Investigation complete  iterations=%d", iterations)
                duration = time.time() - start_time
                result = InvestigationResult(
                    question=question,
                    answer=response.text,
                    tool_calls=tool_calls_made,
                    iterations=iterations,
                    provider=self._provider_name,
                )
                
                # Save to history
                if self._memory and self._investigation_id:
                    await self._memory.db.update_investigation(
                        investigation_id=self._investigation_id,
                        answer=response.text,
                        root_cause=_extract_section(response.text, "Root Cause"),
                        recommendations=_extract_section(response.text, "Recommendations"),
                        iterations=iterations,
                        tool_calls_count=len(tool_calls_made),
                        duration_seconds=duration,
                        status="completed",
                    )
                
                return result

            # Execute tool calls
            results: list[str] = []
            for tc in response.tool_calls:
                tool_start = time.time()
                log.info("Tool call  tool=%s  args=%s", tc.name, tc.arguments)
                try:
                    result_str = await self._mcp.call_tool(tc.name, tc.arguments)
                except Exception as e:
                    result_str = json.dumps({"error": str(e)})
                    log.warning("Tool call failed  tool=%s  error=%s", tc.name, e)

                tool_time_ms = int((time.time() - tool_start) * 1000)
                tool_calls_made.append({
                    "tool": tc.name,
                    "arguments": tc.arguments,
                    "result_preview": result_str[:200],
                })
                
                # Record tool call to history
                if self._memory and self._investigation_id:
                    await self._memory.record_tool_call(
                        investigation_id=self._investigation_id,
                        tool_name=tc.name,
                        arguments=tc.arguments,
                        result=result_str,
                        execution_time_ms=tool_time_ms,
                    )
                
                results.append(result_str)

            # Append tool results — handle OpenAI's multi-message format
            tool_result_msg = self._llm.build_tool_result_message(response.tool_calls, results)
            if "_multi" in tool_result_msg:
                messages.extend(tool_result_msg["_multi"])
            else:
                messages.append(tool_result_msg)

        # Hit iteration limit — force final answer
        log.warning("Max iterations reached (%d), forcing final answer", self._max_iterations)
        messages.append({
            "role": "user",
            "content": (
                f"You have used {self._max_iterations} iterations. "
                "Produce your final incident report now based on the evidence gathered so far."
            ),
        })
        response = self._llm.chat(system, messages, tools=[])
        answer = response.text or ""
        duration = time.time() - start_time

        # Save to history
        if self._memory and self._investigation_id:
            await self._memory.db.update_investigation(
                investigation_id=self._investigation_id,
                answer=answer,
                root_cause=_extract_section(answer, "Root Cause"),
                recommendations=_extract_section(answer, "Recommendations"),
                iterations=iterations,
                tool_calls_count=len(tool_calls_made),
                duration_seconds=duration,
                status="completed",
            )

        return InvestigationResult(
            question=question,
            answer=answer,
            tool_calls=tool_calls_made,
            iterations=iterations,
            provider=self._provider_name,
        )


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _extract_resource_name(question: str) -> Optional[str]:
    """Extract resource name from question. Simple heuristic."""
    # Look for common patterns like "pod-name", "deployment-name", etc.
    words = question.split()
    for word in words:
        if any(word.endswith(suffix) for suffix in ["-pod", "-deployment", "-statefulset", "-service"]):
            return word
    # Try first noun after "is" or "of"
    for i, word in enumerate(words):
        if word in ["is", "of"] and i + 1 < len(words):
            candidate = words[i + 1].rstrip("?.,;:")
            if candidate and len(candidate) > 2:
                return candidate
    return None


def _extract_section(text: str, section_name: str) -> Optional[str]:
    """Extract a section from the answer (e.g., 'Root Cause', 'Recommendations')."""
    lines = text.split("\n")
    start_idx = None
    for i, line in enumerate(lines):
        if section_name.lower() in line.lower():
            start_idx = i
            break

    if start_idx is None:
        return None

    # Collect lines until next section (starts with **) or end
    result = []
    for i in range(start_idx + 1, len(lines)):
        if lines[i].startswith("**") and ":" in lines[i]:
            break
        if lines[i].strip():
            result.append(lines[i])

    return "\n".join(result).strip() if result else None
