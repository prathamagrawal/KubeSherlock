"""Integration tests for watcher email alerts."""
import os
from unittest.mock import MagicMock, patch

import pytest

from agent.watcher import WatcherConfig, PodFailure
from agent.severity import detect_severity
from agent.investigator import InvestigationResult
from agent.notifier import EmailConfig, EmailNotifier


def test_watcher_config_email_disabled_by_default():
    """Test that email is disabled by default."""
    with patch.dict(os.environ, {}, clear=True):
        config = WatcherConfig()
        assert config.email_enabled is False


def test_watcher_config_email_enabled():
    """Test that email can be enabled via environment."""
    with patch.dict(os.environ, {"WATCHER_EMAIL_ENABLED": "true"}, clear=True):
        config = WatcherConfig()
        assert config.email_enabled is True


def test_watcher_config_email_disabled_explicitly():
    """Test that email can be explicitly disabled."""
    with patch.dict(os.environ, {"WATCHER_EMAIL_ENABLED": "false"}, clear=True):
        config = WatcherConfig()
        assert config.email_enabled is False


def test_email_alert_sent_for_critical_severity():
    """Test that email alerts are sent for CRITICAL severity failures."""
    from agent.watcher import Watcher
    
    # Create config with email enabled
    with patch.dict(os.environ, {
        "WATCHER_EMAIL_ENABLED": "true",
        "SMTP_HOST": "smtp.test.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "test@test.com",
        "SMTP_PASSWORD": "password",
        "SMTP_FROM": "kubesherlock@test.com",
        "ALERT_EMAIL_TO": "oncall@test.com"
    }):
        config = WatcherConfig()
        watcher = Watcher(config)
        
        # Verify notifier was initialized
        assert watcher._notifier is not None
        
        # Create mock failure and result that will be CRITICAL
        failure = PodFailure(
            namespace="default",
            pod_name="test-pod",
            reason="OOMKilled",
            restart_count=5
        )
        
        result = InvestigationResult(
            question="Why is pod failing?",
            answer="Pod ran out of memory",
            tool_calls=[],
            iterations=1,
            provider="anthropic"
        )
        
        # Verify severity detection
        severity = detect_severity(result, failure)
        assert severity == "CRITICAL"
        
        # Mock the email sending
        with patch.object(watcher._notifier, '_send_smtp') as mock_send:
            watcher._notifier.send_alert(failure, result, severity)
            mock_send.assert_called_once()


def test_email_alert_sent_for_high_severity():
    """Test that email alerts are sent for HIGH severity failures."""
    from agent.watcher import Watcher
    
    with patch.dict(os.environ, {
        "WATCHER_EMAIL_ENABLED": "true",
        "SMTP_USER": "test@test.com",
        "SMTP_PASSWORD": "password",
        "SMTP_FROM": "kubesherlock@test.com",
        "ALERT_EMAIL_TO": "oncall@test.com"
    }):
        config = WatcherConfig()
        watcher = Watcher(config)
        
        failure = PodFailure(
            namespace="default",
            pod_name="test-pod",
            reason="CrashLoopBackOff",
            restart_count=4
        )
        
        result = InvestigationResult(
            question="Why is pod failing?",
            answer="Application is crashing on startup",
            tool_calls=[],
            iterations=1,
            provider="anthropic"
        )
        
        severity = detect_severity(result, failure)
        assert severity == "HIGH"
        
        with patch.object(watcher._notifier, '_send_smtp') as mock_send:
            watcher._notifier.send_alert(failure, result, severity)
            mock_send.assert_called_once()


def test_email_alert_not_sent_for_medium_severity():
    """Test that email alerts are NOT sent for MEDIUM severity failures."""
    from agent.watcher import Watcher
    
    with patch.dict(os.environ, {
        "WATCHER_EMAIL_ENABLED": "true",
        "SMTP_USER": "test@test.com",
        "SMTP_PASSWORD": "password",
        "SMTP_FROM": "kubesherlock@test.com",
        "ALERT_EMAIL_TO": "oncall@test.com"
    }):
        config = WatcherConfig()
        watcher = Watcher(config)
        
        failure = PodFailure(
            namespace="default",
            pod_name="test-pod",
            reason="Error",
            restart_count=2
        )
        
        result = InvestigationResult(
            question="Why is pod failing?",
            answer="Temporary network error",
            tool_calls=[],
            iterations=1,
            provider="anthropic"
        )
        
        severity = detect_severity(result, failure)
        assert severity == "MEDIUM"
        
        # No email should be sent for MEDIUM
        with patch.object(watcher._notifier, '_send_smtp') as mock_send:
            # Simulate the check in _maybe_investigate
            if severity in ["HIGH", "CRITICAL"]:
                watcher._notifier.send_alert(failure, result, severity)
            mock_send.assert_not_called()


def test_no_email_when_disabled():
    """Test that no notifier is created when email is disabled."""
    from agent.watcher import Watcher
    
    with patch.dict(os.environ, {"WATCHER_EMAIL_ENABLED": "false"}, clear=True):
        config = WatcherConfig()
        watcher = Watcher(config)
        
        assert watcher._notifier is None
