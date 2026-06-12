"""Email notification for pod failures."""
import logging
import os
import smtplib
import time
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


@dataclass
class PodFailure:
    """Type hint for PodFailure from watcher.py."""
    namespace: str
    pod_name: str
    reason: str
    restart_count: int


@dataclass
class InvestigationResult:
    """Type hint for InvestigationResult from investigator.py."""
    question: str
    answer: str
    tool_calls: list
    iterations: int
    provider: str


@dataclass
class EmailConfig:
    """SMTP email configuration loaded from environment."""
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_use_tls: bool
    alert_email_to: list[str]
    
    @classmethod
    def from_env(cls) -> "EmailConfig":
        """Load email config from environment variables."""
        to_addrs = os.getenv("ALERT_EMAIL_TO", "")
        return cls(
            smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_user=os.getenv("SMTP_USER", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_from=os.getenv("SMTP_FROM", ""),
            smtp_use_tls=os.getenv("SMTP_USE_TLS", "true").lower() == "true",
            alert_email_to=[addr.strip() for addr in to_addrs.split(",") if addr.strip()]
        )


class EmailNotifier:
    """Sends email alerts for pod failures."""
    
    def __init__(self, config: EmailConfig):
        self.config = config
    
    def send_alert(self, failure: PodFailure, result: InvestigationResult, severity: str) -> None:
        """Send email alert with retry logic.
        
        Args:
            failure: Pod failure details
            result: Investigation result
            severity: Severity level (CRITICAL, HIGH, MEDIUM, LOW)
        """
        logger.info(f"Attempting to send email alert for {failure.namespace}/{failure.pod_name} (severity: {severity})")
        
        if not self.config.alert_email_to:
            logger.warning("❌ No email recipients configured (ALERT_EMAIL_TO is empty), skipping alert")
            return
        
        if not self.config.smtp_user or not self.config.smtp_password:
            logger.error("❌ SMTP credentials missing - SMTP_USER or SMTP_PASSWORD not set in config.env")
            logger.error("   Please configure SMTP credentials to enable email alerts")
            return
        
        if not self.config.smtp_from:
            logger.error("❌ SMTP_FROM not configured in config.env")
            return
        
        logger.debug(f"Email config: host={self.config.smtp_host}, port={self.config.smtp_port}, " +
                    f"from={self.config.smtp_from}, to={self.config.alert_email_to}, tls={self.config.smtp_use_tls}")
        
        plain_body = self._format_email(failure, result, severity)
        html_body = self._build_html_body(failure, result, severity)
        subject = f"[{severity}] KubeSherlock Alert: {failure.namespace}/{failure.pod_name}"
        
        logger.info(f"📧 Sending email to {len(self.config.alert_email_to)} recipient(s): {', '.join(self.config.alert_email_to)}")
        
        # Retry with exponential backoff: 0s, 5s, 15s
        delays = [0, 5, 15]
        for attempt, delay in enumerate(delays, 1):
            if delay > 0:
                logger.info(f"⏳ Waiting {delay}s before retry attempt {attempt}...")
                time.sleep(delay)
            
            try:
                logger.debug(f"Attempt {attempt}/{len(delays)}: Connecting to {self.config.smtp_host}:{self.config.smtp_port}")
                self._send_smtp_multipart(subject, plain_body, html_body)
                logger.info(f"✅ Email alert sent successfully on attempt {attempt}")
                return
            except smtplib.SMTPAuthenticationError as e:
                logger.error(f"❌ SMTP Authentication failed (attempt {attempt}/{len(delays)}): {e}")
                logger.error("   Please verify SMTP_USER and SMTP_PASSWORD in config.env")
                if attempt == len(delays):
                    logger.error("🚫 All retry attempts exhausted - alert NOT sent")
                    logger.error("   Check SMTP credentials and try again")
            except smtplib.SMTPException as e:
                logger.error(f"❌ SMTP error (attempt {attempt}/{len(delays)}): {e}")
                if attempt == len(delays):
                    logger.error("🚫 All retry attempts exhausted - alert NOT sent")
            except Exception as e:
                logger.error(f"❌ Failed to send email (attempt {attempt}/{len(delays)}): {type(e).__name__}: {e}")
                if attempt == len(delays):
                    logger.error("🚫 All retry attempts exhausted - alert NOT sent")
    
    def _format_email(self, failure: PodFailure, result: InvestigationResult, severity: str) -> str:
        """Format plain text email body."""
        kubectl_ns = f"kubectl -n {failure.namespace}"
        return f"""KubeSherlock Investigation Report

SEVERITY: {severity}
POD: {failure.namespace}/{failure.pod_name}
REASON: {failure.reason}
RESTART COUNT: {failure.restart_count}
PROVIDER: {result.provider}
ITERATIONS: {result.iterations}

ROOT CAUSE ANALYSIS:
{result.answer}

DIAGNOSTIC COMMANDS:
{kubectl_ns} describe pod {failure.pod_name}
{kubectl_ns} logs {failure.pod_name} --previous
{kubectl_ns} get events --field-selector involvedObject.name={failure.pod_name}
{kubectl_ns} top pod {failure.pod_name}

---
Generated by KubeSherlock
"""
    
    def _build_html_body(self, failure: PodFailure, result: InvestigationResult, severity: str) -> str:
        """Build HTML email body with professional template."""
        kubectl_ns = f"kubectl -n {failure.namespace}"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Semantic severity colors
        severity_config = {
            "CRITICAL": {"bg": "#dc3545", "text": "#ffffff", "icon": "🚨", "border": "#b02a37"},
            "HIGH": {"bg": "#fd7e14", "text": "#ffffff", "icon": "⚠️", "border": "#dc6502"},
            "MEDIUM": {"bg": "#ffc107", "text": "#000000", "icon": "⚡", "border": "#d39e00"},
            "LOW": {"bg": "#17a2b8", "text": "#ffffff", "icon": "ℹ️", "border": "#138496"}
        }
        config = severity_config.get(severity, {"bg": "#6c757d", "text": "#ffffff", "icon": "•", "border": "#545b62"})
        badge_color = config["bg"]
        badge_text = config["text"]
        severity_icon = config["icon"]
        border_color = config["border"]
        
        # Escape HTML in dynamic content
        def escape(text: str) -> str:
            return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;background-color:#f4f4f5;">
<table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f5;padding:40px 20px;">
<tr>
<td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.08);">
<!-- Header -->
<tr>
<td style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:40px 30px;text-align:center;">
<div style="display:inline-block;background-color:rgba(255,255,255,0.2);padding:12px;border-radius:12px;margin-bottom:16px;">
<span style="font-size:32px;">🔍</span>
</div>
<h1 style="margin:0;color:#ffffff;font-size:32px;font-weight:700;letter-spacing:-0.5px;">KubeSherlock</h1>
<p style="margin:8px 0 0 0;color:rgba(255,255,255,0.9);font-size:16px;font-weight:400;">Pod Failure Investigation Report</p>
</td>
</tr>
<!-- Severity Badge -->
<tr>
<td style="padding:32px 30px 24px 30px;text-align:center;">
<div style="display:inline-block;background-color:{badge_color};color:{badge_text};padding:12px 24px;border-radius:24px;font-size:15px;font-weight:700;letter-spacing:0.5px;box-shadow:0 2px 8px rgba(0,0,0,0.15);border:2px solid {border_color};">
<span style="font-size:18px;margin-right:8px;">{severity_icon}</span>{escape(severity)} SEVERITY
</div>
</td>
</tr>
<!-- Pod Details -->
<tr>
<td style="padding:0 30px 24px 30px;">
<div style="background:linear-gradient(to right,#f8f9fa,#ffffff);border:2px solid #e9ecef;border-radius:8px;overflow:hidden;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr style="background-color:#495057;">
<td colspan="2" style="padding:12px 16px;color:#ffffff;font-weight:700;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;">📋 Pod Information</td>
</tr>
<tr>
<td style="padding:14px 16px;font-weight:600;color:#495057;width:35%;border-bottom:1px solid #e9ecef;background-color:#f8f9fa;">Namespace</td>
<td style="padding:14px 16px;color:#212529;border-bottom:1px solid #e9ecef;font-family:'SF Mono',Monaco,Consolas,monospace;font-size:14px;"><span style="background-color:#e7f3ff;padding:4px 8px;border-radius:4px;color:#0969da;">{escape(failure.namespace)}</span></td>
</tr>
<tr>
<td style="padding:14px 16px;font-weight:600;color:#495057;border-bottom:1px solid #e9ecef;background-color:#f8f9fa;">Pod Name</td>
<td style="padding:14px 16px;color:#212529;border-bottom:1px solid #e9ecef;font-family:'SF Mono',Monaco,Consolas,monospace;font-size:14px;"><span style="background-color:#e7f3ff;padding:4px 8px;border-radius:4px;color:#0969da;">{escape(failure.pod_name)}</span></td>
</tr>
<tr>
<td style="padding:14px 16px;font-weight:600;color:#495057;border-bottom:1px solid #e9ecef;background-color:#f8f9fa;">Failure Reason</td>
<td style="padding:14px 16px;color:#dc3545;border-bottom:1px solid #e9ecef;font-weight:600;">{escape(failure.reason)}</td>
</tr>
<tr>
<td style="padding:14px 16px;font-weight:600;color:#495057;border-bottom:1px solid #e9ecef;background-color:#f8f9fa;">Restart Count</td>
<td style="padding:14px 16px;color:#dc3545;border-bottom:1px solid #e9ecef;font-weight:700;font-size:16px;">{failure.restart_count} restarts</td>
</tr>
<tr>
<td style="padding:14px 16px;font-weight:600;color:#495057;border-bottom:1px solid #e9ecef;background-color:#f8f9fa;">LLM Provider</td>
<td style="padding:14px 16px;color:#212529;border-bottom:1px solid #e9ecef;">{escape(result.provider).upper()}</td>
</tr>
<tr>
<td style="padding:14px 16px;font-weight:600;color:#495057;background-color:#f8f9fa;">Iterations</td>
<td style="padding:14px 16px;color:#212529;">{result.iterations}</td>
</tr>
</table>
</div>
</td>
</tr>
<!-- Root Cause Analysis -->
<tr>
<td style="padding:0 30px 24px 30px;">
<h2 style="margin:0 0 16px 0;color:#212529;font-size:20px;font-weight:700;display:flex;align-items:center;">
<span style="font-size:24px;margin-right:8px;">🔬</span>Root Cause Analysis
</h2>
<div style="background:linear-gradient(to right,#fff9e6,#ffffff);border-left:4px solid #667eea;padding:20px;border-radius:6px;color:#212529;line-height:1.8;font-size:15px;box-shadow:0 2px 4px rgba(0,0,0,0.04);">
{escape(result.answer).replace(chr(10), '<br>')}
</div>
</td>
</tr>
<!-- Diagnostic Commands -->
<tr>
<td style="padding:0 30px 32px 30px;">
<h2 style="margin:0 0 16px 0;color:#212529;font-size:20px;font-weight:700;display:flex;align-items:center;">
<span style="font-size:24px;margin-right:8px;">💻</span>Diagnostic Commands
</h2>
<div style="background-color:#0d1117;border-radius:8px;padding:20px;overflow-x:auto;border:1px solid #30363d;">
<pre style="margin:0;color:#c9d1d9;font-family:'SF Mono',Monaco,'Cascadia Code',Consolas,monospace;font-size:13px;line-height:1.8;white-space:pre-wrap;word-wrap:break-word;"><code><span style="color:#8b949e;"># Describe pod details</span>
<span style="color:#79c0ff;">{escape(kubectl_ns)}</span> describe pod <span style="color:#a5d6ff;">{escape(failure.pod_name)}</span>

<span style="color:#8b949e;"># View previous logs</span>
<span style="color:#79c0ff;">{escape(kubectl_ns)}</span> logs <span style="color:#a5d6ff;">{escape(failure.pod_name)}</span> --previous

<span style="color:#8b949e;"># Get pod events</span>
<span style="color:#79c0ff;">{escape(kubectl_ns)}</span> get events --field-selector involvedObject.name=<span style="color:#a5d6ff;">{escape(failure.pod_name)}</span>

<span style="color:#8b949e;"># Check resource usage</span>
<span style="color:#79c0ff;">{escape(kubectl_ns)}</span> top pod <span style="color:#a5d6ff;">{escape(failure.pod_name)}</span></code></pre>
</div>
</td>
</tr>
<!-- Footer -->
<tr>
<td style="padding:24px 30px;background:linear-gradient(to right,#f8f9fa,#e9ecef);border-top:2px solid #dee2e6;text-align:center;">
<p style="margin:0;color:#6c757d;font-size:13px;font-weight:600;">⚡ Generated by KubeSherlock</p>
<p style="margin:8px 0 0 0;color:#6c757d;font-size:12px;">{escape(timestamp)}</p>
</td>
</tr>
</table>
</td>
</tr>
</table>
</body>
</html>"""
        return html
    
    def _send_smtp_multipart(self, subject: str, plain_body: str, html_body: str) -> None:
        """Send multipart email via SMTP with HTML and plain text."""
        # Create message container
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.config.smtp_from
        msg["To"] = ", ".join(self.config.alert_email_to)
        
        # Attach plain text first (fallback)
        msg.attach(MIMEText(plain_body, "plain"))
        # Attach HTML (preferred)
        msg.attach(MIMEText(html_body, "html"))
        
        logger.debug(f"Connecting to SMTP server: {self.config.smtp_host}:{self.config.smtp_port} (TLS: {self.config.smtp_use_tls})")
        
        if self.config.smtp_use_tls:
            server = smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=10)
            logger.debug("Starting TLS...")
            server.starttls()
        else:
            server = smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=10)
        
        try:
            logger.debug(f"Logging in as {self.config.smtp_user}...")
            server.login(self.config.smtp_user, self.config.smtp_password)
            logger.debug(f"Sending email from {self.config.smtp_from} to {self.config.alert_email_to}...")
            server.sendmail(self.config.smtp_from, self.config.alert_email_to, msg.as_string())
            logger.debug("Email sent successfully")
        finally:
            server.quit()
