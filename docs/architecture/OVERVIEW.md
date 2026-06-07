# Architecture Overview

## System Components

```
┌─────────────────────────────────────────────────────────┐
│                  User / Watcher                         │
└────────┬──────────────────────────────────┬─────────────┘
         │                                  │
    ┌────▼─────────┐           ┌───────────▼────────┐
    │ Agent CLI    │           │ Watcher (poller)   │
    │ __main__.py  │           │ watcher.py         │
    └────┬─────────┘           └───────────┬────────┘
         │                                  │
         └──────────────┬───────────────────┘
                        │
              ┌─────────▼──────────┐
              │  Investigator      │
              │  ReAct Loop (max 5)│
              │  investigator.py   │
              └─────────┬──────────┘
                        │
         ┌──────────────┼──────────────┐
         │              │              │
    ┌────▼────┐   ┌────▼─────┐  ┌────▼──────┐
    │ Claude  │   │ GPT-4o   │  │ Tool Calls│
    │ Haiku   │   │ Models   │  │ (26 tools)│
    │ Sonnet  │   │ (OpenAI) │  └────┬──────┘
    └────┬────┘   └────┬─────┘       │
         └──────────────┼─────────────┘
                        │
              ┌─────────▼──────────┐
              │  MCP Client        │
              │  stdio transport   │
              │  mcp_client.py     │
              └─────────┬──────────┘
                        │
              ┌─────────▼──────────┐
              │  MCP Server        │
              │  FastMCP           │
              │  server.py         │
              └─────────┬──────────┘
                        │
         ┌──────────────┼──────────────┐
         │              │              │
    ┌────▼────┐   ┌────▼─────┐  ┌────▼──────┐
    │ K8s API │   │ Security │  │ Tools     │
    │ Client  │   │ Context  │  │ pods/logs/│
    │         │   │ (ACL+    │  │ events    │
    └─────────┘   │ redact)  │  └───────────┘
                  └──────────┘
```

---

## Modules

### k8s_mcp/ — Kubernetes Abstraction Layer

| Module | Purpose |
|---|---|
| `client.py` | Singleton K8s API wrapper (CoreV1Api, AppsV1Api) |
| `security.py` | Namespace ACL + secret redaction |
| `server.py` | FastMCP server, tool registration |
| `tools/pods.py` | list_pods, describe_pod |
| `tools/logs.py` | get_pod_logs (capped 500 lines) |
| `tools/events.py` | get_events (warnings_only filter) |
| `tools/metrics.py` | get_pod_metrics, get_node_metrics |
| `tools/nodes.py` | list_nodes (ready/pressure status) |
| `tools/workloads.py` | Deployment/StatefulSet status |
| `tools/config.py` | ConfigMap inspection (redacted) |
| `tools/network.py` | Service/Endpoint inspection |
| `tools/storage.py` | PVC/PV status |
| `tools/quota.py` | ResourceQuota + LimitRange |
| `tools/summary.py` | summarize_pod_health (composite) |
| `tools/actions.py` | restart_pod, delete_pod, scale, rollback |
| `tools/exec.py` | exec_in_pod (run commands) |

**Total: 26 tools exposed via MCP**

### agent/ — AI Investigation Agent

| Module | Purpose |
|---|---|
| `llm.py` | Provider abstraction (Anthropic, OpenAI) |
| `investigator.py` | ReAct loop orchestrator (max 5 iterations) |
| `watcher.py` | Continuous poller, auto-investigator |
| `mcp_client.py` | MCP stdio transport wrapper |
| `prompts.py` | System prompt, formatting |
| `__main__.py` | CLI entrypoint (agent command) |

---

## Data Flow: Single Investigation

```
User Question
    ↓
Agent CLI (__main__.py)
    ↓
Investigator ReAct Loop
    1. System prompt + message history
    2. LLM (Claude/GPT) calls
    3. Parse tool calls from response
    ↓
MCP Client (stdio)
    ↓
MCP Server (FastMCP)
    ↓
Tool Dispatch → K8s API
    ↓
Security Context
    • Namespace check
    • Secret redaction
    ↓
Tool Execution (e.g., list_pods)
    ↓
Result back to Investigator
    ↓
ReAct: Reason + Observe + Continue
    ↓
Final Answer (Root Cause Report)
```

---

## Data Flow: Continuous Watcher

```
Watcher Loop (30s interval)
    ↓
Poll all namespaces
    ↓
PodsTool.list_pods() per namespace
    ↓
Detect failures
    • CrashLoopBackOff
    • High restart count
    • Failed phase
    ↓
Check cooldown (300s)
    ↓
Auto-trigger Investigator
    ↓
Same ReAct loop as single investigation
    ↓
Print report to stdout + logs
```

---

## Security Model

### Namespace Isolation
- `SecurityContext.check_namespace()` called before every K8s API call
- `allowed_namespaces` list enforced via permission check, not LLM judgment
- Fails-closed: empty allowlist = only dev mode

### Secret Redaction
- Pattern-based: keys matching `*KEY`, `*TOKEN`, `*PASSWORD`, etc. → `***REDACTED***`
- Recursive: walks dicts and lists
- Applied to all data leaving MCP server before returning to agent

### Destructive Actions Gate
- All mutations (restart, delete, scale) checked against `DESTRUCTIVE_ACTIONS_ENABLED` flag
- Server-side guard — agent cannot bypass
- Off by default (dev safety)

---

## Extensibility

To add a new tool:

1. Create `k8s_mcp/tools/newtool.py` with a class inheriting pattern
2. Inject `K8sClient` + `SecurityContext` in `__init__`
3. Add `@mcp.tool()` in `server.py`
4. Tool auto-discovered by MCP client

Example:
```python
class NewTool:
    def __init__(self, client: K8sClient, security: SecurityContext):
        self._client = client
        self._security = security
    
    def do_something(self, namespace: str):
        self._security.check_namespace(namespace)
        # API call
```

---

## Performance Considerations

- **Singleton K8sClient**: Single HTTP connection pool across all tools
- **Log cap (500 lines)**: Prevents context explosion in LLM
- **Event warnings-only filter**: Reduces noise
- **Watcher cooldown (300s)**: Prevents spam investigations of same pod
