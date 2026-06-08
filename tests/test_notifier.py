"""Unit tests for email notifier."""
import os
import smtplib
from unittest.mock import Mock, patch, MagicMock
import pytest
from agent.notifier import EmailConfig, EmailNotifier, PodFailure, InvestigationResult


@pytest.fixture
def email_config():
    """Email configuration for testing."""
    return EmailConfig(
        smtp_host="smtp.test.com",
        smtp_port=587,
        smtp_user="test@test.com",
        smtp_password="password123",
        smtp_from="kubesherlock@test.com",
        smtp_use_tls=True,
        alert_email_to=["oncall@test.com", "devops@test.com"]
    )


@pytest.fixture
def pod_failure():
    """Sample pod failure."""
    return PodFailure(
        namespace="production",
        pod_name="api-server-xyz",
        reason="CrashLoopBackOff",
        restart_count=5
    )


@pytest.fixture
def investigation_result():
    """Sample investigation result."""
    return InvestigationResult(
        question="Why is api-server-xyz failing?",
        answer="Container is crashing due to missing environment variable DATABASE_URL",
        tool_calls=[{"tool": "get_pod_logs"}],
        iterations=3,
        provider="anthropic"
    )


def test_email_config_from_env():
    """Test loading config from environment variables."""
    with patch.dict(os.environ, {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "465",
        "SMTP_USER": "user@example.com",
        "SMTP_PASSWORD": "pass",
        "SMTP_FROM": "from@example.com",
        "SMTP_USE_TLS": "false",
        "ALERT_EMAIL_TO": "admin@example.com, ops@example.com"
    }):
        config = EmailConfig.from_env()
        assert config.smtp_host == "smtp.example.com"
        assert config.smtp_port == 465
        assert config.smtp_user == "user@example.com"
        assert config.smtp_password == "pass"
        assert config.smtp_from == "from@example.com"
        assert config.smtp_use_tls is False
        assert config.alert_email_to == ["admin@example.com", "ops@example.com"]


def test_email_config_defaults():
    """Test default values when env vars are missing."""
    with patch.dict(os.environ, {}, clear=True):
        config = EmailConfig.from_env()
        assert config.smtp_host == "smtp.gmail.com"
        assert config.smtp_port == 587
        assert config.smtp_use_tls is True
        assert config.alert_email_to == []


def test_send_alert_success(email_config, pod_failure, investigation_result):
    """Test successful email sending."""
    notifier = EmailNotifier(email_config)
    
    with patch("agent.notifier.smtplib.SMTP") as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value = mock_server
        
        notifier.send_alert(pod_failure, investigation_result, "HIGH")
        
        # Verify SMTP was called correctly
        mock_smtp.assert_called_once_with("smtp.test.com", 587, timeout=10)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("test@test.com", "password123")
        mock_server.sendmail.assert_called_once()
        mock_server.quit.assert_called_once()


def test_send_alert_no_recipients(email_config, pod_failure, investigation_result):
    """Test alert skips when no recipients configured."""
    email_config.alert_email_to = []
    notifier = EmailNotifier(email_config)
    
    with patch("agent.notifier.smtplib.SMTP") as mock_smtp:
        notifier.send_alert(pod_failure, investigation_result, "HIGH")
        mock_smtp.assert_not_called()


def test_send_alert_no_credentials(email_config, pod_failure, investigation_result):
    """Test alert skips when credentials missing."""
    email_config.smtp_user = ""
    email_config.smtp_password = ""
    notifier = EmailNotifier(email_config)
    
    with patch("agent.notifier.smtplib.SMTP") as mock_smtp:
        notifier.send_alert(pod_failure, investigation_result, "HIGH")
        mock_smtp.assert_not_called()


def test_send_alert_retry_logic(email_config, pod_failure, investigation_result):
    """Test retry with exponential backoff."""
    notifier = EmailNotifier(email_config)
    
    with patch("agent.notifier.smtplib.SMTP") as mock_smtp, \
         patch("agent.notifier.time.sleep") as mock_sleep:
        
        mock_server = MagicMock()
        mock_smtp.return_value = mock_server
        
        # Fail twice, succeed on third attempt
        mock_server.login.side_effect = [
            smtplib.SMTPAuthenticationError(535, b"Bad credentials"),
            smtplib.SMTPAuthenticationError(535, b"Bad credentials"),
            None  # Success
        ]
        
        notifier.send_alert(pod_failure, investigation_result, "CRITICAL")
        
        # Should retry with correct delays
        assert mock_sleep.call_count == 2  # No sleep on first attempt
        mock_sleep.assert_any_call(5)
        mock_sleep.assert_any_call(15)
        assert mock_server.login.call_count == 3


def test_send_alert_all_retries_fail(email_config, pod_failure, investigation_result):
    """Test graceful failure when all retries exhausted."""
    notifier = EmailNotifier(email_config)
    
    with patch("agent.notifier.smtplib.SMTP") as mock_smtp, \
         patch("agent.notifier.time.sleep"):
        
        mock_server = MagicMock()
        mock_smtp.return_value = mock_server
        mock_server.login.side_effect = smtplib.SMTPException("Connection failed")
        
        # Should not raise exception
        notifier.send_alert(pod_failure, investigation_result, "CRITICAL")
        
        # Verify 3 attempts were made
        assert mock_server.login.call_count == 3


def test_format_email_content(email_config, pod_failure, investigation_result):
    """Test email body formatting."""
    notifier = EmailNotifier(email_config)
    body = notifier._format_email(pod_failure, investigation_result, "HIGH")
    
    # Check all required elements are present
    assert "HIGH" in body
    assert "production/api-server-xyz" in body
    assert "CrashLoopBackOff" in body
    assert "5" in body  # restart count
    assert "missing environment variable DATABASE_URL" in body
    assert "kubectl -n production describe pod api-server-xyz" in body
    assert "kubectl -n production logs api-server-xyz --previous" in body
    assert "anthropic" in body
    assert "KubeSherlock" in body


def test_smtp_without_tls(email_config, pod_failure, investigation_result):
    """Test SMTP without TLS."""
    email_config.smtp_use_tls = False
    notifier = EmailNotifier(email_config)
    
    with patch("agent.notifier.smtplib.SMTP") as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value = mock_server
        
        notifier.send_alert(pod_failure, investigation_result, "HIGH")
        
        # Should not call starttls
        mock_server.starttls.assert_not_called()
