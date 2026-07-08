# KubeSherlock Improvements

## Recent Enhancements (2026-06-12)

### 🎨 Enhanced Email Alerts

**Semantic Color System**
- **CRITICAL**: Red (`#dc3545`) with 🚨 icon - for immediate action required
- **HIGH**: Orange (`#fd7e14`) with ⚠️ icon - for urgent attention
- **MEDIUM**: Yellow (`#ffc107`) with ⚡ icon - for moderate issues
- **LOW**: Blue (`#17a2b8`) with ℹ️ icon - for informational alerts

**Improved Email Template**
- Modern gradient header with KubeSherlock branding
- Color-coded severity badges with icons
- Structured pod information table with syntax-highlighted namespaces
- Enhanced typography and spacing for better readability
- GitHub-style dark code blocks with syntax highlighting for kubectl commands
- Professional footer with timestamp
- Responsive design optimized for mobile and desktop clients

**Preview Files Generated**
- `email_preview_critical_enhanced.html`
- `email_preview_high_enhanced.html`
- `email_preview_medium_enhanced.html`
- `email_preview_low_enhanced.html`

---

### 📊 Comprehensive Logging & Observability

**Watcher Logging**
- ✅ Startup configuration summary (provider, namespaces, intervals, thresholds)
- ✅ Email notification setup status with detailed diagnostics
- ✅ SMTP credential validation with actionable error messages
- ✅ Poll cycle tracking (namespace checks, pod counts)
- ✅ Failure detection logging with full context
- ✅ Investigation lifecycle tracking (start, iterations, completion)
- ✅ Severity assessment logging
- ✅ Email alert status (sent/skipped/failed with reasons)
- ✅ Cooldown tracking for duplicate failures

**Notifier Logging**
- ✅ Email configuration validation (recipients, SMTP credentials, server details)
- ✅ Detailed SMTP connection flow (connecting, TLS handshake, authentication)
- ✅ Retry attempt tracking with exponential backoff logging
- ✅ Specific error types (SMTPAuthenticationError vs generic SMTP errors)
- ✅ Success/failure status with actionable next steps
- ✅ Email size and recipient count tracking

**Investigator Logging**
- ✅ Investigation start with full context (provider, question, max iterations)
- ✅ Database integration status (investigation ID creation)
- ✅ Memory context loading
- ✅ MCP tool availability count
- ✅ ReAct iteration tracking with progress indicators
- ✅ LLM response validation
- ✅ Tool call execution with timing metrics
- ✅ Investigation completion summary (iterations, tool calls, duration)
- ✅ Error handling with exception types

**MCP Client Logging**
- ✅ Server startup command and log file location
- ✅ Transport establishment and session initialization
- ✅ Tool discovery with available tool names
- ✅ Individual tool call tracking with arguments
- ✅ Connection failure diagnostics with log file references

**Log Message Features**
- 🎨 Emoji prefixes for visual scanning (🚀 ✅ ❌ ⚠️ 🔍 📧 🔧 🔄)
- 📝 Structured formatting with indentation for context
- 🔍 DEBUG level for detailed troubleshooting
- ℹ️ INFO level for operational visibility (default)
- ⚠️ WARNING level for non-critical issues
- ❌ ERROR level with actionable guidance

**Key Benefits**
- **Immediate Diagnosis**: Know exactly why emails aren't sending (missing credentials, wrong password, no recipients)
- **Progress Tracking**: See investigation flow in real-time
- **Performance Monitoring**: Tool execution timing and iteration counts
- **Debugging**: Full request/response chains with DEBUG level
- **Production Ready**: INFO level provides clean operational visibility without noise

---

### 📁 Configuration Changes

**Switched from `.env` to `config.env`**
- All code now uses `config.env` directly (no hidden `.env` file)
- Updated all Python modules to load `config.env`
- Updated documentation and setup scripts
- Removed `.env` from `.gitignore`
- Simplified workflow - one config file for all environments

**Files Updated**
- `agent/__main__.py`
- `agent/watcher.py`
- `agent/metrics_server.py`
- `k8s_mcp/server.py`
- `smoke_test.py`
- `examples/full_monitoring_example.py`
- `setup-local.sh`
- All documentation files

---

## Testing the Improvements

### Test Email Alerts
```bash
# View enhanced email templates
open email_preview_critical_enhanced.html
open email_preview_high_enhanced.html
```

### Test Logging
```bash
# Run with INFO logging (default)
python -m agent.watcher

# Run with DEBUG logging for troubleshooting
LOG_LEVEL=DEBUG python -m agent.watcher

# Test SMTP error handling (intentionally wrong password)
# Edit config.env:
WATCHER_EMAIL_ENABLED=true
SMTP_PASSWORD=wrong_password

# Run and observe detailed error messages
python -m agent.watcher
```

### Expected Log Output
```
2026-06-12 15:50:00 [INFO ] agent.watcher - 🚀 Initializing KubeSherlock Watcher
2026-06-12 15:50:00 [INFO ] agent.watcher -    Provider: openai
2026-06-12 15:50:00 [INFO ] agent.watcher -    Namespaces: ['default', 'kube-system']
2026-06-12 15:50:00 [INFO ] agent.watcher -    Poll interval: 30s
2026-06-12 15:50:00 [INFO ] agent.watcher - 📧 Email notifications ENABLED - setting up...
2026-06-12 15:50:00 [INFO ] agent.watcher - ✅ Email notifications configured successfully
2026-06-12 15:50:00 [INFO ] agent.watcher -    Recipients: admin@example.com
2026-06-12 15:50:00 [INFO ] agent.watcher -    SMTP: smtp.gmail.com:587
```

---

## Migration Guide

### For Existing Users

1. **Rename your `.env` file**:
   ```bash
   mv .env config.env
   ```

2. **Verify email configuration** in `config.env`:
   ```bash
   WATCHER_EMAIL_ENABLED=true
   SMTP_USER=your-email@gmail.com
   SMTP_PASSWORD=your-app-password
   ALERT_EMAIL_TO=admin@example.com
   ```

3. **Restart the watcher** to see improved logging:
   ```bash
   python -m agent.watcher
   ```

4. **Monitor logs** for any configuration issues - they will now be clearly reported!

---

## Future Improvements

- [ ] Slack/Teams webhook integration
- [ ] Prometheus metrics for email delivery rates
- [ ] Email template customization via config
- [ ] HTML email preview in terminal (rich library)
- [ ] Investigation history in emails (previous incidents for same pod)
