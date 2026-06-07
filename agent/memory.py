"""
agent.memory
~~~~~~~~~~~~

Investigation history and context retrieval for the ReAct loop.

Allows the agent to learn from past investigations by retrieving similar
incidents and their root causes.
"""

import logging
from typing import Optional

from database.db import Database

log = logging.getLogger(__name__)


class InvestigationMemory:
    """Retrieves past investigations for context in the ReAct loop."""

    def __init__(self, db: Database):
        self.db = db

    async def get_context(
        self,
        namespace: Optional[str] = None,
        resource_name: Optional[str] = None,
        limit: int = 3,
    ) -> str:
        """Retrieve similar past investigations as context for the current investigation.

        Returns a formatted string with past incidents and their resolutions.
        """
        investigations = await self.db.search_investigations(
            namespace=namespace,
            resource_name=resource_name,
            limit=limit,
        )

        if not investigations:
            return ""

        context_lines = ["## Similar past investigations:\n"]
        for inv in investigations:
            if inv.get("root_cause") and inv.get("recommendations"):
                context_lines.append(f"- **{inv['question']}**")
                context_lines.append(f"  Root cause: {inv['root_cause']}")
                context_lines.append(f"  Recommendations: {inv['recommendations']}\n")

        return "\n".join(context_lines)

    async def save_investigation(
        self,
        question: str,
        answer: str,
        namespace: Optional[str],
        resource_name: Optional[str],
        provider: str,
        iterations: int,
        tool_calls_count: int,
        duration_seconds: float,
    ) -> int:
        """Save an investigation to history. Returns investigation ID."""
        inv_id = await self.db.create_investigation(
            question=question,
            namespace=namespace,
            resource_name=resource_name,
            provider=provider,
        )

        # Parse root cause and recommendations from answer
        root_cause = _extract_section(answer, "Root Cause")
        recommendations = _extract_section(answer, "Recommendations")

        await self.db.update_investigation(
            investigation_id=inv_id,
            answer=answer,
            root_cause=root_cause,
            recommendations=recommendations,
            iterations=iterations,
            tool_calls_count=tool_calls_count,
            duration_seconds=duration_seconds,
            status="completed",
        )

        return inv_id

    async def record_tool_call(
        self,
        investigation_id: int,
        tool_name: str,
        arguments: dict,
        result: str,
        execution_time_ms: int,
    ) -> None:
        """Record a tool call for an investigation."""
        summary = result[:500] if result else ""
        await self.db.add_tool_call(
            investigation_id=investigation_id,
            tool_name=tool_name,
            arguments=arguments,
            result_summary=summary,
            execution_time_ms=execution_time_ms,
        )


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
