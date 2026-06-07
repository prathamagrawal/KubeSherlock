"""
agent.mcp_client
~~~~~~~~~~~~~~~~

Async MCP client wrapper.

Connects to the k8s MCP server via stdio transport (server launched as a
subprocess), discovers all available tools, and exposes them in the format
the LLM providers expect.

Uses anyio for transport compatibility with the MCP SDK.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

log = logging.getLogger(__name__)


class MCPClient:
    """Wraps an MCP ClientSession and exposes tools + call_tool.

    Not instantiated directly — use as an argument passed into the
    anyio task via :func:`run_with_mcp`.

    Args:
        session: Active MCP ClientSession.
        tools: Tool definitions in Anthropic/OpenAI compatible format.
    """

    def __init__(self, session: ClientSession, tools: list[dict]) -> None:
        self._session = session
        self._tools = tools

    @property
    def tools(self) -> list[dict]:
        """Tool definitions in LLM-compatible format."""
        return self._tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on the MCP server and return result as JSON string.

        Args:
            tool_name: Name of the MCP tool to call.
            arguments: Tool input arguments dict.

        Returns:
            JSON string of the tool result.
        """
        log.debug("mcp_call  tool=%s  args=%s", tool_name, arguments)
        result = await self._session.call_tool(tool_name, arguments)

        if result.content and hasattr(result.content[0], "text"):
            raw = result.content[0].text
        else:
            raw = json.dumps([c.model_dump() for c in result.content])

        log.info("mcp_call done  tool=%s  bytes=%d", tool_name, len(raw))
        return raw


async def run_with_mcp(server_command: list[str], coro_factory,
                       stderr_log: str | None = None):
    """Run an async coroutine with an active MCPClient inside the anyio task group.

    Args:
        server_command: Command + args to launch the MCP server subprocess.
        coro_factory: Async callable that receives an MCPClient and returns a result.
        stderr_log: Optional path to write server stderr output. Defaults to
            ``/tmp/kubesherlock_mcp.log``.

    Returns:
        Whatever coro_factory returns.
    """
    log_path = stderr_log or "/tmp/kubesherlock_mcp.log"
    params = StdioServerParameters(
        command=server_command[0],
        args=server_command[1:],
        env={**os.environ},
    )

    with open(log_path, "a") as stderr_file:
        params = StdioServerParameters(
            command=server_command[0],
            args=server_command[1:],
            env={**os.environ},
            stderr=stderr_file,
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools_result = await session.list_tools()
                tools = [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "input_schema": t.inputSchema,
                    }
                    for t in tools_result.tools
                ]
                log.info("MCP connected  tools=%d  server_log=%s", len(tools), log_path)

                client = MCPClient(session, tools)
                return await coro_factory(client)
