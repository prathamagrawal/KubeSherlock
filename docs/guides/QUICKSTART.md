# Quick Start — Local Testing

## Setup (1 minute)

```bash
./setup-local.sh
minikube start
```

Then edit `.env`:
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Get a free key at https://console.anthropic.com.

---

## First Test

```bash
# Unit tests
.venv/bin/pytest tests/ -v

# Single investigation
python -m agent "Why is coredns crashing?" --namespaces kube-system

# Continuous watcher
python -m agent.watcher
```

---

## All Commands

```bash
# Server
python -m k8s_mcp.server --namespaces default kube-system

# Agent (Anthropic)
python -m agent "Your question?" --namespaces default

# Agent (OpenAI)
python -m agent "Your question?" --provider openai --namespaces default

# Watcher
python -m agent.watcher

# Logs
tail -f /tmp/kubesherlock_mcp.log
```

See [TESTING.md](TESTING.md) for full test suite.
