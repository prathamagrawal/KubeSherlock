# KubeSherlock Deployment Guide

Three deployment options: Python package, Docker container, or Kubernetes Helm chart.

---

## Option 1: Python Package (pip install)

### Installation

```bash
pip install kubesherlock
```

### Usage

```bash
# One-time investigation
kubesherlock "Why is my pod crashing?" --namespaces production

# Continuous watcher
kubesherlock-watcher

# MCP server (for custom integrations)
kubesherlock-server --namespaces default
```

### Configuration

Create `~/.kubesherlock/config.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-your-key
ALLOWED_NAMESPACES=production,staging
WATCHER_POLL_INTERVAL=60
```

---

## Option 2: Docker Container

### Build Image

```bash
docker build -t kubesherlock:latest .
```

### Run Watcher

```bash
docker run -d \
  --name kubesherlock \
  -v ~/.kube/config:/home/kubesherlock/.kube/config:ro \
  -e ANTHROPIC_API_KEY=sk-ant-your-key \
  -e WATCHER_POLL_INTERVAL=60 \
  -e ALLOWED_NAMESPACES=production,staging \
  kubesherlock:latest
```

### Run One-Time Investigation

```bash
docker run --rm \
  -v ~/.kube/config:/home/kubesherlock/.kube/config:ro \
  -e OPENAI_API_KEY=sk-proj-your-key \
  kubesherlock:latest \
  python -m agent "Why is nginx-pod failing?" --provider openai --namespaces default
```

### View Logs

```bash
docker logs -f kubesherlock
```

---

## Option 3: Kubernetes (Helm Chart)

### Prerequisites

- Kubernetes cluster with RBAC enabled
- Helm 3.x installed
- API keys for Claude or GPT

### Quick Start

```bash
# 1. Create secret with API keys
kubectl create secret generic kubesherlock-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-your-key \
  --from-literal=OPENAI_API_KEY=sk-proj-your-key

# 2. Install chart
helm install kubesherlock ./helm/kubesherlock \
  --set secrets.existingSecret=kubesherlock-secrets \
  --set config.llmProvider=anthropic \
  --set config.watcherPollInterval=60
```

### Monitor Specific Namespaces

```bash
helm install kubesherlock ./helm/kubesherlock \
  --set secrets.existingSecret=kubesherlock-secrets \
  --set config.allowedNamespaces="{production,staging}"
```

### Enable Email Alerts

```bash
# Add SMTP credentials to secret
kubectl create secret generic kubesherlock-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-your-key \
  --from-literal=SMTP_USER=alerts@company.com \
  --from-literal=SMTP_PASSWORD=app-password

# Install with email enabled
helm install kubesherlock ./helm/kubesherlock \
  --set secrets.existingSecret=kubesherlock-secrets \
  --set config.emailEnabled=true \
  --set email.smtpFrom=kubesherlock@company.com \
  --set email.alertEmailTo=oncall@company.com
```

### Custom Configuration

Create `custom-values.yaml`:

```yaml
config:
  watcherPollInterval: 120
  watcherRestartThreshold: 5
  llmProvider: openai
  allowedNamespaces:
    - production
    - staging
  emailEnabled: true

email:
  smtpHost: smtp.gmail.com
  smtpPort: 587
  smtpFrom: kubesherlock@mycompany.com
  alertEmailTo: oncall@mycompany.com,devops@mycompany.com

resources:
  limits:
    cpu: 1000m
    memory: 1Gi
  requests:
    cpu: 200m
    memory: 256Mi
```

Install with custom values:

```bash
helm install kubesherlock ./helm/kubesherlock \
  -f custom-values.yaml \
  --set secrets.existingSecret=kubesherlock-secrets
```

### Verification

```bash
# Check deployment
kubectl get pods -l app.kubernetes.io/name=kubesherlock

# View logs
kubectl logs -f deployment/kubesherlock-kubesherlock

# Check RBAC
kubectl auth can-i list pods --as=system:serviceaccount:default:kubesherlock
```

### Upgrade

```bash
helm upgrade kubesherlock ./helm/kubesherlock \
  -f custom-values.yaml \
  --set secrets.existingSecret=kubesherlock-secrets
```

### Uninstall

```bash
helm uninstall kubesherlock
kubectl delete secret kubesherlock-secrets
```

---

## Security Considerations

### API Keys
- **Never commit** API keys to version control
- Use Kubernetes Secrets or external secret managers (Vault, AWS Secrets Manager)
- Rotate keys regularly

### RBAC
- Chart creates read-only ClusterRole by default
- For namespace-scoped deployments, modify RBAC to use Role instead of ClusterRole
- Audit permissions regularly

### Network Policies
- Watcher only needs egress to:
  - Kubernetes API server
  - LLM provider APIs (api.anthropic.com or api.openai.com)
  - SMTP server (if email enabled)

Example NetworkPolicy:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: kubesherlock-egress
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: kubesherlock
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 443  # HTTPS
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 6443  # K8s API
```

---

## Production Recommendations

### High Availability
```yaml
replicaCount: 2
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchLabels:
            app.kubernetes.io/name: kubesherlock
        topologyKey: kubernetes.io/hostname
```

### Resource Limits
```yaml
resources:
  limits:
    cpu: 1000m
    memory: 1Gi
  requests:
    cpu: 250m
    memory: 256Mi
```

### Monitoring
- Export Prometheus metrics on port 8000
- Alert on investigation failures
- Track investigation latency

### Cost Control
```yaml
config:
  watcherPollInterval: 300  # Less frequent polling
  watcherRestartThreshold: 5  # Only critical issues
  allowedNamespaces:        # Scope to important namespaces
    - production
```

---

## Troubleshooting

### Watcher Not Detecting Failures
```bash
# Check logs
kubectl logs -f deployment/kubesherlock-kubesherlock

# Verify RBAC
kubectl auth can-i list pods --as=system:serviceaccount:default:kubesherlock

# Check config
kubectl get configmap kubesherlock-kubesherlock -o yaml
```

### API Key Issues
```bash
# Verify secret exists
kubectl get secret kubesherlock-secrets

# Check secret content (base64 encoded)
kubectl get secret kubesherlock-secrets -o jsonpath='{.data.ANTHROPIC_API_KEY}' | base64 -d
```

### Email Not Sending
```bash
# Check SMTP configuration
kubectl get configmap kubesherlock-kubesherlock -o yaml | grep SMTP

# Test SMTP manually
kubectl exec deployment/kubesherlock-kubesherlock -- \
  python -c "import smtplib; smtplib.SMTP('smtp.gmail.com', 587).starttls()"
```
