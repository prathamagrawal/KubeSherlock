# Configuration Reference

All configuration via environment variables or `.env` file.

---

## Kubernetes

| Variable | Default | Description |
|---|---|---|
| `KUBECONFIG` | `~/.kube/config` | Path to kubeconfig file |
| `KUBE_CONTEXT` | (current-context) | Kubernetes context name |
| `ALLOWED_NAMESPACES` | (empty = all) | Comma-separated namespaces allowed |

Example:
```
KUBECONFIG=/path/to/kubeconfig
KUBE_CONTEXT=minikube
ALLOWED_NAMESPACES=default,kube-system,prod
```

---

## LLM Providers

### Anthropic

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |

Get key: https://console.anthropic.com/keys

### OpenAI

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | GPT API key |

Get key: https://platform.openai.com/api-keys

---

## Logging

| Variable | Default | Valid Values |
|---|---|---|
| `LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING, ERROR, CRITICAL |

Use `LOG_LEVEL=DEBUG` for verbose output.

---

## MCP Server

| Variable | Default | Description |
|---|---|---|
| `DESTRUCTIVE_ACTIONS_ENABLED` | `false` | Enable restart/delete/scale/rollback (dev only) |

---

## Agent

### CLI Flags (Override env vars)

```bash
python -m agent <question> \
  --provider anthropic|openai \
  --model claude-haiku-4-5 \
  --namespaces ns1 ns2
```

---

## Watcher

| Variable | Default | Description |
|---|---|---|
| `WATCHER_ENABLED` | `true` | Enable continuous monitoring |
| `WATCHER_POLL_INTERVAL` | `30` | Seconds between polls |
| `WATCHER_NAMESPACES` | (ALLOWED_NAMESPACES) | Comma-separated namespaces to watch |
| `WATCHER_LLM_PROVIDER` | `anthropic` | Which LLM for auto-investigations |
| `WATCHER_RESTART_THRESHOLD` | `3` | Restart count to trigger investigation |
| `WATCHER_COOLDOWN` | `300` | Seconds before re-investigating same pod |

Example:
```
WATCHER_ENABLED=true
WATCHER_POLL_INTERVAL=30
WATCHER_NAMESPACES=default,prod
WATCHER_RESTART_THRESHOLD=2
WATCHER_COOLDOWN=60
WATCHER_LLM_PROVIDER=anthropic
```

---

## Complete .env Example

```
# Kubernetes
KUBECONFIG=~/.kube/config
KUBE_CONTEXT=minikube
ALLOWED_NAMESPACES=default,kube-system

# LLM
ANTHROPIC_API_KEY=sk-ant-your-key
OPENAI_API_KEY=sk-proj-your-key

# Logging
LOG_LEVEL=INFO

# Server
DESTRUCTIVE_ACTIONS_ENABLED=false

# Watcher
WATCHER_ENABLED=true
WATCHER_POLL_INTERVAL=30
WATCHER_NAMESPACES=default,kube-system
WATCHER_RESTART_THRESHOLD=3
WATCHER_COOLDOWN=300
WATCHER_LLM_PROVIDER=anthropic
```
