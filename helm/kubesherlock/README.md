# KubeSherlock Helm Chart

Deploy KubeSherlock — an AI-powered Kubernetes incident investigation agent — using Helm.
The chart deploys the watcher process and an optional Prometheus metrics sidecar.
It does **not** bundle PostgreSQL or Prometheus; point it at your existing instances.

---

## Quick Start

### 1. Create the application secret

```bash
kubectl create secret generic kubesherlock-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=OPENAI_API_KEY=sk-proj-... \
  --from-literal=DB_PASSWORD=your-db-password \
  --from-literal=SMTP_USER=alerts@yourdomain.com \
  --from-literal=SMTP_PASSWORD=your-smtp-password
```

> **Tip:** `DB_PASSWORD` and SMTP keys are optional — only needed when PostgreSQL
> (`postgresql.enabled=true`) or email alerts (`config.emailEnabled=true`) are active.

### 2. Install the chart

```bash
# Minimal — watcher only, no DB, no metrics
helm install kubesherlock ./helm/kubesherlock \
  --set secrets.existingSecret=kubesherlock-secrets

# Full stack — watcher + PostgreSQL integration + Prometheus metrics sidecar
helm install kubesherlock ./helm/kubesherlock \
  --set secrets.existingSecret=kubesherlock-secrets \
  --set postgresql.enabled=true \
  --set postgresql.host=my-postgres-host \
  --set metrics.enabled=true

# Using the test-values file (for local testing with test-stack.yaml)
kubectl apply -f helm/test-stack.yaml
kubectl rollout status statefulset/kubesherlock-postgres
helm install kubesherlock ./helm/kubesherlock -f helm/test-values.yaml
```

---

## Configuration Reference

### Core

| Parameter | Default | Description |
|---|---|---|
| `image.repository` | `prathamagrawal/kubesherlock` | Container image |
| `image.tag` | `1.0.0` | Image tag |
| `image.pullPolicy` | `IfNotPresent` | Pull policy |
| `replicaCount` | `1` | Number of replicas |

### Watcher

| Parameter | Default | Description |
|---|---|---|
| `config.watcherEnabled` | `true` | Enable the watcher loop |
| `config.watcherPollInterval` | `60` | Seconds between pod scans |
| `config.watcherRestartThreshold` | `3` | Restart count that triggers investigation |
| `config.watcherCooldown` | `300` | Seconds before re-investigating same pod |
| `config.llmProvider` | `openai` | `openai` or `anthropic` |
| `config.allowedNamespaces` | `["default"]` | Namespaces to watch (empty = all) |
| `config.logLevel` | `INFO` | Log level |

### Secrets

| Parameter | Default | Description |
|---|---|---|
| `secrets.existingSecret` | `""` | Pre-created k8s Secret name **(recommended)** |
| `secrets.anthropicApiKey` | `""` | Inline Anthropic key (not recommended for prod) |
| `secrets.openaiApiKey` | `""` | Inline OpenAI key |
| `secrets.smtpUser` | `""` | SMTP username |
| `secrets.smtpPassword` | `""` | SMTP password |
| `secrets.dbPassword` | `""` | PostgreSQL password |

### Email Alerts

| Parameter | Default | Description |
|---|---|---|
| `config.emailEnabled` | `false` | Enable email alerts |
| `email.smtpHost` | `smtp.gmail.com` | SMTP host |
| `email.smtpPort` | `587` | SMTP port |
| `email.smtpUseTls` | `true` | Use STARTTLS |
| `email.smtpFrom` | `""` | Sender address |
| `email.alertEmailTo` | `""` | Recipient address |

### PostgreSQL

| Parameter | Default | Description |
|---|---|---|
| `postgresql.enabled` | `false` | Enable DB persistence |
| `postgresql.host` | `""` | Hostname or service name |
| `postgresql.port` | `5432` | Port |
| `postgresql.database` | `kubesherlock` | Database (catalog) name |
| `postgresql.user` | `postgres` | Database user |
| `postgresql.schema` | `kubesherlock` | PostgreSQL schema (not `public`) |

> The chart **does not deploy PostgreSQL**. Point `postgresql.host` at an existing
> instance — a cloud managed DB, a StatefulSet, or the one from `helm/test-stack.yaml`.

### Prometheus Metrics

| Parameter | Default | Description |
|---|---|---|
| `metrics.enabled` | `false` | Enable metrics sidecar container |
| `metrics.port` | `8000` | Port exposed by the sidecar |
| `metrics.serviceMonitor.enabled` | `false` | Create a Prometheus Operator ServiceMonitor |
| `metrics.serviceMonitor.interval` | `30s` | Scrape interval |
| `metrics.serviceMonitor.namespace` | `""` | ServiceMonitor namespace (defaults to release namespace) |

When `metrics.enabled=true` the chart creates:
- A second container (`metrics-server`) in the same pod running `python -m agent.metrics_server`
- A `ClusterIP` Service (`<release>-kubesherlock-metrics`) exposing port 8000

### Resources

| Parameter | Default | Description |
|---|---|---|
| `resources.limits.cpu` | `500m` | Watcher CPU limit |
| `resources.limits.memory` | `512Mi` | Watcher memory limit |
| `metricsResources.limits.cpu` | `100m` | Metrics sidecar CPU limit |
| `metricsResources.limits.memory` | `64Mi` | Metrics sidecar memory limit |

---

## Testing Locally (with test-stack.yaml)

`helm/test-stack.yaml` deploys a self-contained PostgreSQL StatefulSet and Prometheus
Deployment inside the cluster so you can exercise the full chart without external deps.

```bash
# 1. Deploy infra
kubectl apply -f helm/test-stack.yaml

# 2. Wait for postgres to be ready
kubectl rollout status statefulset/kubesherlock-postgres

# 3. Install KubeSherlock pointing at it
helm install kubesherlock ./helm/kubesherlock -f helm/test-values.yaml

# 4. Verify all pods are running
kubectl get pods

# 5. Port-forward to check metrics
kubectl port-forward svc/kubesherlock-kubesherlock-metrics 8000:8000
curl http://localhost:8000/metrics

# 6. Port-forward to check Prometheus
kubectl port-forward svc/kubesherlock-prometheus 9090:9090
# Open http://localhost:9090 → Status → Targets → kubesherlock-agent should be UP

# 7. Teardown
helm uninstall kubesherlock
kubectl delete -f helm/test-stack.yaml
kubectl delete pvc postgres-data-kubesherlock-postgres-0
```

---

## RBAC

The chart creates a `ClusterRole` with **read-only** access to:

- `pods`, `pods/log`, `events`, `nodes`
- `services`, `endpoints`, `configmaps`
- `persistentvolumeclaims`, `resourcequotas`, `limitranges`
- `deployments`, `statefulsets` (apps group)
- `pods`, `nodes` (metrics.k8s.io group)

---

## Security

- Runs as non-root (UID 1000)
- Read-only root filesystem (`/tmp` via `emptyDir`)
- `allowPrivilegeEscalation: false`
- All Linux capabilities dropped

---

## Uninstall

```bash
helm uninstall kubesherlock
kubectl delete secret kubesherlock-secrets     # if you created it manually
```
