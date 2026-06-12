# KubeSherlock — Testing Commands

Complete guide to testing every layer of the project. Start from the top and work down.

---

## Prerequisites

```bash
# One-time setup
./setup-local.sh          # creates .venv, installs all deps, copies config.env → .env
minikube start            # only needed for integration/cluster tests
```

Edit `.env` and set at least one LLM key:
```
ANTHROPIC_API_KEY=sk-ant-...
# or
OPENAI_API_KEY=sk-proj-...
```

---

## 1. Unit Tests (No cluster needed)

### Run all unit tests

```bash
.venv/bin/pytest tests/ -v
```

### Run individual test modules

```bash
# Kubernetes tool layer (pods, logs, events, nodes, actions, security)
.venv/bin/pytest tests/test_k8s_mcp.py -v

# Security context — namespace ACL + secret redaction
.venv/bin/pytest tests/test_k8s_mcp.py::TestSecurityContext -v

# Pods tool
.venv/bin/pytest tests/test_k8s_mcp.py::TestPodsTool -v

# Logs tool
.venv/bin/pytest tests/test_k8s_mcp.py::TestLogsTool -v

# Events tool
.venv/bin/pytest tests/test_k8s_mcp.py::TestEventsTool -v

# Destructive actions gate
.venv/bin/pytest tests/test_k8s_mcp.py::TestCheckDestructive -v
.venv/bin/pytest tests/test_k8s_mcp.py::TestActionsTool -v

# Severity detection (CRITICAL / HIGH / MEDIUM / LOW logic)
.venv/bin/pytest tests/test_severity.py -v

# Email notifier (SMTP, retry logic, config loading)
.venv/bin/pytest tests/test_notifier.py -v

# Watcher + email integration (severity gating, notifier init)
.venv/bin/pytest tests/test_watcher_email_integration.py -v
```

### Run with coverage

```bash
.venv/bin/pytest tests/ -v --cov=agent --cov=k8s_mcp --cov-report=term-missing
```

---

## 2. Security Layer

### Namespace isolation (manual)

```bash
python -c "
from k8s_mcp.security import SecurityContext
ctx = SecurityContext(allowed_namespaces=['default'])
ctx.check_namespace('default')   # passes
print('default: OK')
try:
    ctx.check_namespace('kube-system')
except PermissionError as e:
    print(f'kube-system: blocked — {e}')
"
```

### Secret redaction (manual)

```bash
python -c "
from k8s_mcp.security import SecurityContext
ctx = SecurityContext()
data = {'API_KEY': 'secret123', 'DB_PASSWORD': 'pass', 'host': 'localhost'}
print(ctx.redact(data))
# API_KEY and DB_PASSWORD should show ***REDACTED***, host should be unchanged
"
```

---

## 3. Severity Detection

```bash
python -c "
from agent.severity import detect_severity, PodFailure, InvestigationResult

def check(reason, restarts, answer=''):
    f = PodFailure('default', 'pod', reason, restarts)
    r = InvestigationResult('q', answer or 'generic error', [], 1, 'anthropic')
    print(f'{reason:25s} restarts={restarts:2d} → {detect_severity(r, f)}')

check('OOMKilled',        1)          # CRITICAL
check('Error',           15)          # CRITICAL
check('CrashLoopBackOff', 4)          # HIGH
check('ImagePullBackOff', 2)          # HIGH
check('ErrImagePull',    2)           # HIGH
check('Error',           7)           # MEDIUM
check('Error',           2)           # MEDIUM
check('Unknown',         1)           # LOW
"
```

---

## 4. Email Preview (HTML Templates)

Generates `mail/email_preview_*.html` for all four severity levels.

```bash
cd /path/to/kubesherlock
.venv/bin/python tests/test_html_template.py
# Opens: mail/email_preview_critical.html
# Opens: mail/email_preview_high.html
# Opens: mail/email_preview_medium.html
# Opens: mail/email_preview_low.html
```

Open any file in a browser to preview the HTML email template.

---

## 5. MCP Server (Standalone)

### Start the server

```bash
# Terminal 1
python -m k8s_mcp.server --namespaces default kube-system

# With destructive actions enabled (dev only)
DESTRUCTIVE_ACTIONS_ENABLED=true python -m k8s_mcp.server --namespaces default
```

Server logs go to `/tmp/kubesherlock_mcp.log`:
```bash
tail -f /tmp/kubesherlock_mcp.log
```

---

## 6. Smoke Test (Integration — Needs Cluster)

Spins up the MCP server internally, runs 14 tool checks against a live cluster.

```bash
# Basic run against default namespace
python smoke_test.py --namespace default

# Target specific namespace
python smoke_test.py --namespace kube-system --allowed kube-system

# Target specific pod
python smoke_test.py --namespace default --pod <pod-name>

# With destructive actions
python smoke_test.py --namespace default --pod <pod-name> --destructive

# With a deployment rollback test
python smoke_test.py --namespace default --deployment <deploy-name> --destructive
```

Expected output: all 14 sections marked `✓`.

---

## 7. Agent — Single Investigation (Needs Cluster + LLM Key)

```bash
# Anthropic (default)
python -m agent "Why is coredns crashing?" --namespaces kube-system

# OpenAI
python -m agent "Why is X failing?" --provider openai --namespaces default

# Specific model
python -m agent "What's wrong with nginx?" \
  --provider anthropic \
  --model claude-haiku-4-5 \
  --namespaces default

# Enable destructive actions (dev only)
python -m agent "Restart the failing pod" --namespaces default --destructive

# Verbose debug output
LOG_LEVEL=DEBUG python -m agent "Why is pod failing?" --namespaces default
```

---

## 8. Watcher — Continuous Monitoring (Needs Cluster + LLM Key)

```bash
# Start watcher
python -m agent.watcher

# With debug logging
LOG_LEVEL=DEBUG python -m agent.watcher

# Trigger a detection — crash a pod in another terminal
kubectl delete pod <pod-name> -n default

# OOMKilled test pod (triggers CRITICAL investigation + email if configured)
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: oom-test
spec:
  containers:
  - name: stress
    image: polinux/stress
    resources:
      limits:
        memory: "50Mi"
    command: ["stress"]
    args: ["--vm", "1", "--vm-bytes", "100M"]
EOF

# CrashLoopBackOff test pod (triggers HIGH investigation + email if configured)
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: crash-test
spec:
  containers:
  - name: crash
    image: busybox
    command: ["sh", "-c", "exit 1"]
EOF
```

Expected watcher console output:
```
🚨 Failure detected: default/oom-test (OOMKilled, 1 restarts)
🔍 Investigating: default/oom-test
📋 Investigation report: default/oom-test
Severity: CRITICAL  |  Iterations: 3  |  Tools used: 5
```

Cleanup:
```bash
kubectl delete pod oom-test crash-test
```

---

## 9. Email Alerts

### Verify config loads correctly

```bash
python -c "
import os
os.environ.update({
    'SMTP_HOST': 'smtp.gmail.com',
    'SMTP_PORT': '587',
    'SMTP_USER': 'you@gmail.com',
    'SMTP_PASSWORD': 'app-password',
    'SMTP_FROM': 'kubesherlock@yourdomain.com',
    'ALERT_EMAIL_TO': 'oncall@yourdomain.com'
})
from agent.notifier import EmailConfig
cfg = EmailConfig.from_env()
print(cfg)
"
```

### Send a test alert (real SMTP)

```bash
python -c "
from agent.notifier import EmailConfig, EmailNotifier, PodFailure, InvestigationResult
from agent.severity import detect_severity

config = EmailConfig.from_env()   # reads .env
notifier = EmailNotifier(config)

failure = PodFailure('default', 'test-pod', 'OOMKilled', 5)
result  = InvestigationResult('Why crashing?', 'Pod ran out of memory', [], 2, 'anthropic')
severity = detect_severity(result, failure)

print(f'Severity: {severity}')
notifier.send_alert(failure, result, severity)
print('Done — check your inbox')
"
```

### Enable email in watcher

Add to `.env`:
```
WATCHER_EMAIL_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=kubesherlock@yourdomain.com
ALERT_EMAIL_TO=oncall@yourdomain.com
```

Then start the watcher and trigger a HIGH/CRITICAL failure (see section 8).

---

## 10. Metrics Server

```bash
# Start server (port 8000 by default)
python -m agent.metrics_server

# Or custom port
METRICS_PORT=9100 python -m agent.metrics_server

# Check health
curl http://localhost:8000/health

# Scrape metrics
curl http://localhost:8000/metrics
```

---

## 11. Database Layer (Needs Docker)

```bash
# Start PostgreSQL
docker-compose up -d postgres

# Verify schema initialises
docker exec kubesherlock-db psql -U postgres -d kubesherlock -c "\dt"
# Expected: investigations, metrics tables

# Run the full monitoring example
python examples/full_monitoring_example.py
```

### Test database methods directly

```bash
python -c "
import asyncio
from database.db import Database

async def test():
    db = Database()
    await db.connect()
    print('Connected:', db._pool is not None)
    await db.disconnect()

asyncio.run(test())
"
```

---

## 12. Full Infrastructure (Docker)

```bash
# Start everything
docker-compose up -d

# Verify services
docker-compose ps

# PostgreSQL
docker exec kubesherlock-db psql -U postgres -d kubesherlock -c "SELECT version();"

# Prometheus
curl http://localhost:9090/-/healthy

# Prometheus targets
open http://localhost:9090/targets    # browser

# Tear down
docker-compose down
```

---

## Quick Reference

| What | Command |
|---|---|
| All unit tests | `.venv/bin/pytest tests/ -v` |
| With coverage | `.venv/bin/pytest tests/ -v --cov=agent --cov=k8s_mcp --cov-report=term-missing` |
| Severity only | `.venv/bin/pytest tests/test_severity.py -v` |
| Email only | `.venv/bin/pytest tests/test_notifier.py -v` |
| Watcher+email | `.venv/bin/pytest tests/test_watcher_email_integration.py -v` |
| K8s tools only | `.venv/bin/pytest tests/test_k8s_mcp.py -v` |
| HTML previews | `.venv/bin/python tests/test_html_template.py` |
| Smoke test | `python smoke_test.py --namespace kube-system --allowed kube-system` |
| Single investigation | `python -m agent "Why is X crashing?" --namespaces default` |
| Watcher | `python -m agent.watcher` |
| Metrics server | `python -m agent.metrics_server` |
| MCP server | `python -m k8s_mcp.server --namespaces default` |
| Infrastructure | `docker-compose up -d` |
