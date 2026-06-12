# KubeSherlock Testing Guide - Token Optimized
**Recipient**: prathamagrawal1205@gmail.com

---

## Pre-requisites ✓
- ✓ OpenAI API key configured in `.env`
- ✓ Email recipient set to `prathamagrawal1205@gmail.com`
- ⚠️ You need to add your SMTP credentials to `.env`

---

## Step 1: Verify Minikube Cluster
**Purpose**: Ensure Kubernetes is running  
**Token Cost**: None

```bash
minikube status
# If not running:
minikube start
```

**Expected Output**: `host: Running, kubelet: Running, apiserver: Running`

---

## Step 2: Unit Tests (No LLM Tokens)
**Purpose**: Test core functionality without API calls  
**Token Cost**: 0 tokens

```bash
.venv/bin/pytest tests/ -v
```

**Expected**: All tests pass (security, tools, client)

---

## Step 3: MCP Server Test (No LLM Tokens)
**Purpose**: Verify Kubernetes tool layer  
**Token Cost**: 0 tokens

**Terminal 1** - Start MCP server:
```bash
python -m k8s_mcp.server --namespaces kube-system
```

**Terminal 2** - Run smoke test:
```bash
python smoke_test.py --namespace kube-system --allowed kube-system
```

**Expected**: ✓ 14/14 checks pass (list_pods, describe_pod, list_nodes, etc.)

---

## Step 4: Minimal LLM Agent Test
**Purpose**: Test LLM integration with minimal tokens  
**Token Cost**: ~500-1000 tokens (simple question)

```bash
python -m agent "List pods in kube-system" \
  --provider openai \
  --model gpt-4o-mini \
  --namespaces kube-system
```

**Why gpt-4o-mini?** 
- 60% cheaper than gpt-4o
- 128k context window
- Perfect for testing

**Expected Output**:
- Investigation starts
- Tool calls to list_pods
- Final answer with pod names
- Token usage displayed

---

## Step 5: Token-Efficient Investigation Test
**Purpose**: Test full investigation with controlled scope  
**Token Cost**: ~1500-3000 tokens

Create a test pod that will fail:

```bash
kubectl run failing-pod --image=invalid-image:latest -n default
```

Wait 30 seconds, then investigate:

```bash
python -m agent "Why is failing-pod crashing?" \
  --provider openai \
  --model gpt-4o-mini \
  --namespaces default
```

**Expected**:
- Checks pod status
- Gets pod events  
- Identifies ImagePullBackOff
- Provides root cause analysis

**Token Optimization Tips**:
- Use specific pod names (not "why are my pods failing?")
- Limit to one namespace
- Use gpt-4o-mini instead of gpt-4o

---

## Step 6: Email Notification Test
**Purpose**: Test email alerts  
**Token Cost**: ~2000-4000 tokens (includes investigation)

### 6a. Configure Email in `.env`:

You need to fill in these values:
```bash
SMTP_USER=your-gmail@gmail.com
SMTP_PASSWORD=your-gmail-app-password  # NOT your regular password!
SMTP_FROM=kubesherlock@yourdomain.com
```

**Gmail App Password Setup**:
1. Go to Google Account → Security
2. Enable 2-Factor Authentication
3. Search "App passwords"
4. Generate password for "Mail"
5. Use that 16-character password in `SMTP_PASSWORD`

### 6b. Enable Email in Watcher:

```bash
# Edit .env and change:
WATCHER_EMAIL_ENABLED=true
WATCHER_LLM_PROVIDER=openai
```

### 6c. Test Email Template (No Tokens):

```bash
python test_html_template.py
```

This generates preview HTML files without sending emails or using tokens.

### 6d. Run Watcher with Email:

```bash
python -m agent.watcher
```

In another terminal, crash a pod:
```bash
kubectl delete pod failing-pod -n default
kubectl run failing-pod --image=invalid-image:latest -n default
```

**Expected**:
- Watcher detects failure after 30s
- Runs investigation using OpenAI
- Sends email to prathamagrawal1205@gmail.com
- Email contains:
  - Pod name, namespace, restart count
  - Root cause analysis
  - Recommended actions
  - Tool calls made

---

## Step 7: Token Usage Monitoring

Check token usage after each test:

```bash
# OpenAI Dashboard: https://platform.openai.com/usage
```

**Estimated Total for Complete Testing**:
- Unit tests: 0 tokens
- Smoke test: 0 tokens  
- Minimal LLM test: ~1,000 tokens
- Investigation test: ~3,000 tokens
- Email test: ~4,000 tokens
- **Total: ~8,000 tokens = $0.01-0.02**

---

## Token Optimization Strategies

### 1. Use gpt-4o-mini for Testing
```bash
--model gpt-4o-mini  # 60% cheaper
```

### 2. Limit Max Iterations
Edit `agent/investigator.py` line 18:
```python
MAX_ITERATIONS = 3  # Default is 5
```

### 3. Reduce Tool Call Context
Shorter tool descriptions = fewer input tokens.

### 4. Use Specific Questions
❌ Bad (wastes tokens): "What's wrong with my cluster?"
✓ Good: "Why is pod X failing in namespace Y?"

### 5. Test with Known Failures
Pre-create failures rather than exploring unknown issues.

---

## Quick Command Reference

```bash
# Start everything fresh
minikube delete && minikube start

# Run unit tests
.venv/bin/pytest tests/ -v

# Test single investigation (minimal tokens)
python -m agent "Why is coredns failing?" \
  --provider openai \
  --model gpt-4o-mini \
  --namespaces kube-system

# Check logs
tail -f /tmp/kubesherlock_mcp.log

# Debug mode (see token usage)
LOG_LEVEL=DEBUG python -m agent "test" --namespaces default

# Stop watcher
pkill -f "python -m agent.watcher"
```

---

## Next Steps After Testing

Once basic testing passes:

1. **Production Readiness**:
   - Set proper SMTP credentials
   - Configure allowed namespaces
   - Set `DESTRUCTIVE_ACTIONS_ENABLED=false`

2. **Cost Optimization**:
   - Switch to gpt-4o-mini for production watcher
   - Set cooldown to avoid duplicate investigations
   - Use namespace filtering

3. **Advanced Testing**:
   - Test with real production-like failures
   - Test namespace isolation
   - Test secret redaction

---

## Troubleshooting

**"No module named anthropic"**:
```bash
.venv/bin/pip install anthropic openai
```

**"Error connecting to MCP server"**:
Check `/tmp/kubesherlock_mcp.log` for errors.

**Email not sending**:
1. Verify SMTP credentials
2. Check `WATCHER_EMAIL_ENABLED=true`
3. Verify recipient email format
4. Check Gmail app password (not regular password)

**High token usage**:
1. Use gpt-4o-mini
2. Reduce MAX_ITERATIONS
3. Be more specific in questions
4. Check that watcher cooldown is set (300s)
