# Testing Guide

## Unit Tests (No Cluster)

```bash
.venv/bin/pytest tests/ -v
.venv/bin/pytest tests/test_k8s_mcp.py::TestPodsTool -v
```

---

## Integration Tests

### Smoke Test (All Layers)

Terminal 1:
```bash
python -m k8s_mcp.server --namespaces kube-system
```

Terminal 2:
```bash
python smoke_test.py --namespace kube-system --allowed kube-system
```

Expected: ✓ list_pods, describe_pod, list_nodes, summarize_pod_health, all 14 sections pass.

---

### Agent Tests

```bash
# Anthropic
python -m agent "Why is coredns failing?" --namespaces kube-system

# OpenAI
python -m agent "Why is X crashing?" --provider openai --namespaces kube-system

# With logging
LOG_LEVEL=DEBUG python -m agent "test?" --namespaces default
```

---

### Watcher Test

```bash
python -m agent.watcher
```

In another terminal, crash a pod:
```bash
kubectl delete pod <pod-name> -n default
```

Watcher detects restart and auto-investigates.

---

## Manual Tests

### Namespace isolation
```bash
python -c "
from k8s_mcp.tools import PodsTool
from k8s_mcp.security import SecurityContext
from k8s_mcp.client import K8sClient

ctx = SecurityContext(allowed_namespaces=['default'])
tool = PodsTool(K8sClient(), ctx)
tool.list_pods('default')  # OK
tool.list_pods('kube-system')  # PermissionError
"
```

### Secret redaction
```bash
python -c "
from k8s_mcp.security import SecurityContext
ctx = SecurityContext()
data = {'API_KEY': 'secret', 'host': 'localhost'}
print(ctx.redact(data))
# Output: API_KEY shows as ***REDACTED***
"
```

---

## Debugging

**Server logs:**
```bash
tail -f /tmp/kubesherlock_mcp.log
```

**Agent debug:**
```bash
LOG_LEVEL=DEBUG python -m agent "test?" --namespaces default 2>&1 | grep "Tool call"
```

**Watcher debug:**
```bash
LOG_LEVEL=DEBUG python -m agent.watcher 2>&1 | grep "Poll\|failure"
```
