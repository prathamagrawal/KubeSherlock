#!/usr/bin/env python3
"""Generate sample HTML email to preview the template."""
from agent.notifier import EmailNotifier, EmailConfig, PodFailure, InvestigationResult

# Create sample data
config = EmailConfig(
    smtp_host="smtp.gmail.com",
    smtp_port=587,
    smtp_user="test@example.com",
    smtp_password="password",
    smtp_from="kubesherlock@example.com",
    smtp_use_tls=True,
    alert_email_to=["oncall@example.com"]
)

failure = PodFailure(
    namespace="production",
    pod_name="api-server-7b8f9d-xyz",
    reason="CrashLoopBackOff",
    restart_count=12
)

result = InvestigationResult(
    question="Why is api-server-7b8f9d-xyz crashing?",
    answer="""The pod is crashing due to a missing DATABASE_URL environment variable.

Analysis:
1. Container exits with code 1 immediately after startup
2. Application logs show: "Error: DATABASE_URL environment variable not set"
3. ConfigMap 'app-config' exists but is not mounted to the pod
4. Deployment manifest is missing the envFrom section

Recommended fix:
Add the ConfigMap reference to the deployment spec under containers.envFrom""",
    tool_calls=[
        {"tool": "get_pod_logs", "result": "Error: DATABASE_URL not set"},
        {"tool": "get_pod_events", "result": "Back-off restarting failed container"},
        {"tool": "describe_pod", "result": "Container exit code: 1"}
    ],
    iterations=4,
    provider="anthropic/claude-3.5-sonnet"
)

# Test different severity levels
notifier = EmailNotifier(config)

print("Generating HTML template previews...\n")

for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
    html = notifier._build_html_body(failure, result, severity)
    filename = f"email_preview_{severity.lower()}.html"
    
    with open(filename, "w") as f:
        f.write(html)
    
    print(f"✓ Generated {filename}")

print("\nPlain text version:")
print("=" * 80)
print(notifier._format_email(failure, result, "HIGH"))
print("=" * 80)

print("\nOpen the .html files in your browser to preview the templates.")
