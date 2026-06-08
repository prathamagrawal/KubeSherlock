# Email Alerts Integration - Verification Guide

## Overview
Email alerts have been integrated into the KubeSherlock watcher. Alerts are sent for HIGH and CRITICAL severity pod failures.

## Changes Made

### 1. WatcherConfig (`agent/watcher.py`)
- Added `WATCHER_EMAIL_ENABLED` flag (default: `false`)
- Loads `email_enabled` from environment

### 2. Watcher.__init__() (`agent/watcher.py`)
- Conditionally instantiates `EmailNotifier` when email is enabled
- Loads `EmailConfig.from_env()` when enabled
- Logs "Email notifications enabled" on startup

### 3. Watcher._maybe_investigate() (`agent/watcher.py`)
- Calls `detect_severity(result, failure)` after investigation
- Sends email alert if `email_enabled` AND `severity in ["HIGH", "CRITICAL"]`
- Logs "Email alert sent" with severity level

### 4. Watcher._print_report() (`agent/watcher.py`)
- Updated to include severity level in console output
- Format: `Severity: {severity}  |  Iterations: {n}  |  Tools used: {n}`

### 5. Environment Variables (`.env`)
- Added `WATCHER_EMAIL_ENABLED=false`
- Added commented SMTP configuration template

### 6. Tests (`tests/test_watcher_email_integration.py`)
- 7 comprehensive integration tests
- Verifies config loading, notifier instantiation, and alert behavior

## Configuration

### Required Environment Variables (when email enabled)
```bash
WATCHER_EMAIL_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=kubesherlock@yourdomain.com
ALERT_EMAIL_TO=oncall@example.com,devops@example.com
```

### Optional Environment Variables
```bash
SMTP_USE_TLS=true  # default: true
```

## Testing

### Run Unit Tests
```bash
.venv/bin/pytest tests/test_watcher_email_integration.py -v
```

### Manual Verification Steps

#### 1. Test with Email Disabled (Default)
```bash
# Ensure .env has WATCHER_EMAIL_ENABLED=false or not set
python -m agent.watcher
# Expected: No "Email notifications enabled" log
# Expected: Watcher starts normally
```

#### 2. Test with Email Enabled (Mock SMTP)
```bash
# Update .env:
# WATCHER_EMAIL_ENABLED=true
# SMTP_USER=test@test.com
# SMTP_PASSWORD=dummy
# SMTP_FROM=kubesherlock@test.com
# ALERT_EMAIL_TO=oncall@test.com

python -m agent.watcher
# Expected: "Email notifications enabled" in logs
# Expected: Watcher starts normally (email won't send without real SMTP)
```

#### 3. Test Severity Detection
Create a test pod that will trigger HIGH/CRITICAL severity:

**OOMKilled Pod (CRITICAL)**
```bash
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
      requests:
        memory: "50Mi"
    command: ["stress"]
    args: ["--vm", "1", "--vm-bytes", "100M"]
EOF
```

**CrashLoopBackOff Pod (HIGH)**
```bash
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

Monitor watcher output:
```bash
python -m agent.watcher
# Expected: Investigation triggers
# Expected: Severity displayed in output
# Expected: Email alert sent (if SMTP configured) for HIGH/CRITICAL only
```

#### 4. Verify Console Output
After investigation completes, verify output includes severity:
```
📋 Investigation report: default/oom-test
Severity: CRITICAL  |  Iterations: 3  |  Tools used: 5
```

## Email Alert Format

Emails sent for HIGH/CRITICAL severity include:
- Subject: `[SEVERITY] KubeSherlock Alert: namespace/pod-name`
- Severity level
- Pod details (namespace, name, reason, restart count)
- Root cause analysis
- Diagnostic kubectl commands
- Investigation metadata (provider, iterations)

## Severity Levels

| Severity | Triggers | Email Alert |
|----------|----------|-------------|
| CRITICAL | OOMKilled, disk full, restarts ≥ 10 | ✅ Yes |
| HIGH | CrashLoopBackOff, ImagePullBackOff, panic/fatal errors | ✅ Yes |
| MEDIUM | Generic errors, restarts ≥ 5 | ❌ No |
| LOW | Everything else | ❌ No |

## Troubleshooting

### Email Alerts Not Sending
1. Check `WATCHER_EMAIL_ENABLED=true` in `.env`
2. Verify SMTP credentials are correct
3. Check logs for "Email notifications enabled"
4. Verify severity is HIGH or CRITICAL (check console output)
5. Check logs for "Email alert sent" or error messages

### SMTP Authentication Issues
- For Gmail: Use App Password, not account password
- Enable "Less secure app access" if using basic auth
- Check firewall rules for SMTP port (587/465)

### Testing SMTP Connection
```python
from agent.notifier import EmailConfig, EmailNotifier
from agent.watcher import PodFailure
from agent.investigator import InvestigationResult

config = EmailConfig.from_env()
notifier = EmailNotifier(config)

failure = PodFailure("default", "test-pod", "OOMKilled", 5)
result = InvestigationResult(
    question="Test",
    answer="Test alert",
    tool_calls=[],
    iterations=1,
    provider="test"
)

notifier.send_alert(failure, result, "CRITICAL")
```

## Production Considerations

1. **Use Secret Manager**: Store SMTP credentials in Kubernetes Secrets or AWS Secrets Manager
2. **Rate Limiting**: Consider adding rate limiting for email alerts
3. **Alert Aggregation**: For high-volume clusters, consider batching alerts
4. **Monitoring**: Monitor email delivery success rates
5. **Failover**: Configure backup SMTP server if primary fails

## Success Criteria

✅ All 7 integration tests pass  
✅ Watcher starts with email disabled (default)  
✅ Watcher starts with email enabled (logs confirmation)  
✅ Severity level displayed in console output  
✅ Email sent only for HIGH/CRITICAL severity  
✅ Email contains full investigation report  
✅ .env updated with configuration template
