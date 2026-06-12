"""
agent.__main__
~~~~~~~~~~~~~~

CLI entrypoint for the KubeSherlock agent.

Usage:
    python -m agent "Why is postgres-nodes-3 crashing?" --provider openai --namespaces db
    python -m agent "Fix the crashing pod" --provider openai --namespaces db --destructive
    python -m agent "Why is X failing?" --provider anthropic --namespaces db
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import anyio
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / "config.env")

from .investigator import Investigator
from .mcp_client import run_with_mcp

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "WARNING").upper(),
    format="%(asctime)s [%(levelname)-5s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _build_server_command(namespaces: list[str], destructive: bool) -> list[str]:
    cmd = [sys.executable, "-m", "k8s_mcp.server"]
    if namespaces:
        cmd += ["--namespaces"] + namespaces
    if destructive:
        os.environ["DESTRUCTIVE_ACTIONS_ENABLED"] = "true"
    return cmd


async def _run(question: str, namespaces: list[str], destructive: bool,
               provider: str, model: str | None) -> None:
    server_cmd = _build_server_command(namespaces, destructive)

    print(f"\n🔍 KubeSherlock investigating: {question!r}")
    print(f"🤖 Provider: {provider}" + (f"  model: {model}" if model else ""))
    if destructive:
        print("⚠️  Destructive actions enabled.")
    print()

    async def run_investigation(client):
        print(f"📡 Connected to MCP server — {len(client.tools)} tools available")
        print(f"📋 Server logs: /tmp/kubesherlock_mcp.log\n")
        investigator = Investigator(mcp_client=client, provider=provider, model=model)
        return await investigator.investigate(question)

    result = await run_with_mcp(server_cmd, run_investigation)

    print("─" * 60)
    print(f"Iterations : {result.iterations}  |  Tool calls: {len(result.tool_calls)}")
    for tc in result.tool_calls:
        print(f"  → {tc['tool']}({tc['arguments']})")
    print("─" * 60)
    print("\n" + result.answer + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="KubeSherlock — AI-powered Kubernetes incident investigator"
    )
    parser.add_argument("question", nargs="+", help="Investigation question")
    parser.add_argument("--namespaces", nargs="*", default=[],
                        help="Allowed namespaces (default: all)")
    parser.add_argument("--destructive", action="store_true",
                        help="Enable destructive actions (restart, exec, scale)")
    parser.add_argument("--provider", default="anthropic", choices=["anthropic", "openai"],
                        help="LLM provider (default: anthropic)")
    parser.add_argument("--model", default=None,
                        help="Model name override (e.g. gpt-4o, claude-sonnet-4-5)")
    args = parser.parse_args()

    env_key = "ANTHROPIC_API_KEY" if args.provider == "anthropic" else "OPENAI_API_KEY"
    if not os.environ.get(env_key):
        print(f"Error: {env_key} not set in environment or config.env file")
        sys.exit(1)

    anyio.run(_run, " ".join(args.question), args.namespaces,
              args.destructive, args.provider, args.model)


if __name__ == "__main__":
    main()
