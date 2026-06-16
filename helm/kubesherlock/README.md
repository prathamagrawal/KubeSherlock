# KubeSherlock Helm Chart

Deploy KubeSherlock watcher to continuously monitor your Kubernetes cluster.

## Installation

### 1. Create Secret with API Keys

```bash
kubectl create secret generic kubesherlock-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-your-key \
  --from-literal=OPENAI_API_KEY=sk-proj-your-key
```

### 2. Install Chart

```bash
# Default installation (monitors all namespaces)
helm install kubesherlock ./helm/kubesherlock \
  --set secrets.existingSecret=kubesherlock-secrets

# Monitor specific namespaces only
helm install kubesherlock ./helm/kubesherlock \
  --set secrets.existingSecret=kubesherlock-secrets \
  --set config.allowedNamespaces="{production,staging}"

# Enable email alerts
helm install kubesherlock ./helm/kubesherlock \
  --set secrets.existingSecret=kubesherlock-secrets \
  --set config.emailEnabled=true \
  --set email.smtpFrom=kubesherlock@company.com \
  --set email.alertEmailTo=oncall@company.com \
  --set secrets.smtpUser=alerts@company.com \
  --set secrets.smtpPassword=your-app-password
```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `image.repository` | `kubesherlock/kubesherlock` | Image repository |
| `image.tag` | `1.0.0` | Image tag |
| `config.watcherEnabled` | `true` | Enable watcher |
| `config.watcherPollInterval` | `60` | Poll interval (seconds) |
| `config.llmProvider` | `anthropic` | LLM provider (anthropic/openai) |
| `config.allowedNamespaces` | `[]` | Namespaces to monitor (empty = all) |
| `config.emailEnabled` | `false` | Enable email alerts |
| `secrets.existingSecret` | `""` | Use existing secret |
| `resources.limits.cpu` | `500m` | CPU limit |
| `resources.limits.memory` | `512Mi` | Memory limit |

## RBAC

The chart creates a ClusterRole with read-only access to:
- pods, pods/log, events
- nodes, services, endpoints
- deployments, statefulsets
- configmaps, pvcs
- resource quotas, limit ranges

## Security

- Runs as non-root user (UID 1000)
- Read-only root filesystem
- No privilege escalation
- Drops all capabilities

## Uninstall

```bash
helm uninstall kubesherlock
kubectl delete secret kubesherlock-secrets
```
