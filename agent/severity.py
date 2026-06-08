"""Severity detection for pod failures."""
from dataclasses import dataclass


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


def detect_severity(result: InvestigationResult, failure: PodFailure) -> str:
    """Detect severity level from failure reason and investigation result.
    
    Args:
        result: Investigation result containing root cause analysis
        failure: Pod failure details
        
    Returns:
        Severity level: CRITICAL, HIGH, MEDIUM, or LOW
    """
    reason = failure.reason.lower()
    answer = result.answer.lower()
    
    # CRITICAL: Resource exhaustion or persistent failures
    if any(k in reason for k in ["oomkilled", "outofmemory"]):
        return "CRITICAL"
    if "disk" in answer and any(k in answer for k in ["full", "pressure", "space"]):
        return "CRITICAL"
    if failure.restart_count >= 10:
        return "CRITICAL"
    
    # HIGH: Crash loops and config errors
    if "crashloopbackoff" in reason:
        return "HIGH"
    if any(k in reason for k in ["imagepullbackoff", "errimagepull"]):
        return "HIGH"
    if any(k in answer for k in ["panic", "segfault", "fatal", "error exit"]):
        return "HIGH"
    
    # MEDIUM: Recoverable errors
    if "error" in reason or failure.restart_count >= 5:
        return "MEDIUM"
    
    # LOW: Everything else
    return "LOW"
