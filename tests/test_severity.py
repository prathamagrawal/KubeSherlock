"""Unit tests for severity detection."""
import pytest
from agent.severity import detect_severity, PodFailure, InvestigationResult


@pytest.fixture
def base_result():
    """Basic investigation result."""
    return InvestigationResult(
        question="Why is pod failing?",
        answer="Pod is failing due to application error",
        tool_calls=[],
        iterations=1,
        provider="anthropic"
    )


@pytest.fixture
def base_failure():
    """Basic pod failure."""
    return PodFailure(
        namespace="default",
        pod_name="test-pod",
        reason="Error",
        restart_count=1
    )


def test_severity_oomkilled_critical(base_result, base_failure):
    """OOMKilled failures should be CRITICAL."""
    base_failure.reason = "OOMKilled"
    assert detect_severity(base_result, base_failure) == "CRITICAL"


def test_severity_outofmemory_critical(base_result, base_failure):
    """OutOfMemory failures should be CRITICAL."""
    base_failure.reason = "OutOfMemory"
    assert detect_severity(base_result, base_failure) == "CRITICAL"


def test_severity_disk_full_critical(base_result, base_failure):
    """Disk full issues should be CRITICAL."""
    base_result.answer = "The node disk is full and pod cannot write logs"
    assert detect_severity(base_result, base_failure) == "CRITICAL"


def test_severity_high_restart_count_critical(base_result, base_failure):
    """10+ restarts should be CRITICAL."""
    base_failure.restart_count = 15
    assert detect_severity(base_result, base_failure) == "CRITICAL"


def test_severity_crashloop_high(base_result, base_failure):
    """CrashLoopBackOff should be HIGH."""
    base_failure.reason = "CrashLoopBackOff"
    assert detect_severity(base_result, base_failure) == "HIGH"


def test_severity_imagepull_high(base_result, base_failure):
    """Image pull errors should be HIGH."""
    base_failure.reason = "ImagePullBackOff"
    assert detect_severity(base_result, base_failure) == "HIGH"
    
    base_failure.reason = "ErrImagePull"
    assert detect_severity(base_result, base_failure) == "HIGH"


def test_severity_panic_high(base_result, base_failure):
    """Panic in logs should be HIGH."""
    base_result.answer = "Application panic detected in container logs"
    assert detect_severity(base_result, base_failure) == "HIGH"


def test_severity_medium_restart_count(base_result, base_failure):
    """5+ restarts (but <10) should be MEDIUM."""
    base_failure.restart_count = 7
    assert detect_severity(base_result, base_failure) == "MEDIUM"


def test_severity_error_reason_medium(base_result, base_failure):
    """Generic error should be MEDIUM."""
    base_failure.reason = "Error"
    assert detect_severity(base_result, base_failure) == "MEDIUM"


def test_severity_low_default(base_result, base_failure):
    """Unknown reasons with low restart count should be LOW."""
    base_failure.reason = "Unknown"
    base_failure.restart_count = 1
    assert detect_severity(base_result, base_failure) == "LOW"


def test_severity_case_insensitive(base_result, base_failure):
    """Severity detection should be case insensitive."""
    base_failure.reason = "crashloopbackoff"  # lowercase
    assert detect_severity(base_result, base_failure) == "HIGH"
    
    base_failure.reason = "OOMKILLED"  # uppercase
    assert detect_severity(base_result, base_failure) == "CRITICAL"
