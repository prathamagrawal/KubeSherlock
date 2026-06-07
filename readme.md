# KubeSherlock

AI-powered Kubernetes incident investigation agent.

Automatically detects pod failures and generates root-cause analysis reports using Claude or GPT.

---

## Quick Start

```bash
./setup-local.sh
minikube start
python -m agent "Why is my pod crashing?" --namespaces default
```

See [docs/guides/QUICKSTART.md](docs/guides/QUICKSTART.md) for details.

---

## Features

- **K8s Abstraction Layer** — 26+ tools via MCP
- **AI Investigation Agent** — Anthropic + OpenAI support
- **Continuous Watcher** — Auto-detects and investigates failures
- **Security** — Namespace isolation, secret redaction
- **Destructive Actions** — Restart, delete, scale pods (gated)

---

## Documentation

| Document | Purpose |
|---|---|
| [QUICKSTART](docs/guides/QUICKSTART.md) | Local setup and first test |
| [TESTING](docs/guides/TESTING.md) | Complete test suite guide |
| [Architecture](docs/architecture/OVERVIEW.md) | System design and components |
| [API Reference](docs/reference/API.md) | Tool definitions and schemas |
| [Configuration](docs/reference/CONFIGURATION.md) | Environment variables |

---

## Project Structure

```
kubesherlock/
├── k8s_mcp/          # Kubernetes abstraction + MCP server
│   ├── client.py     # Singleton K8s client
│   ├── server.py     # FastMCP server
│   ├── security.py   # ACL + redaction
│   └── tools/        # Pod, log, event, metric tools
├── agent/            # AI investigation agent
│   ├── llm.py        # Provider abstraction (Anthropic/OpenAI)
│   ├── investigator.py # ReAct loop
│   ├── watcher.py    # Continuous monitoring
│   └── mcp_client.py # MCP stdio transport
├── tests/            # Unit tests (pytest)
├── smoke_test.py     # Integration test
├── docs/             # Documentation
└── setup-local.sh    # One-command setup
```

---

## Development

```bash
# Setup
./setup-local.sh

# Unit tests
.venv/bin/pytest tests/ -v

# Start server
python -m k8s_mcp.server --namespaces default

# Run agent
python -m agent "Why is X failing?" --namespaces default

# Start watcher
python -m agent.watcher
```

See full docs in [docs/](docs/).
