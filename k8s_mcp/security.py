"""
k8s_mcp.security
~~~~~~~~~~~~~~~~

Per-session security controls for the K8s MCP server.

Two responsibilities:

1. **Namespace isolation** — every tool call must pass through
   ``check_namespace`` before touching the Kubernetes API.

2. **Secret redaction** — environment variables or dict keys whose names
   match common secret patterns are replaced with ``***REDACTED***`` before
   data leaves the server.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

_SECRET_PATTERN = re.compile(
    r".*(KEY|TOKEN|PASSWORD|SECRET|CREDENTIAL).*", re.IGNORECASE
)
_REDACTED = "***REDACTED***"


@dataclass
class SecurityContext:
    """Enforces namespace ACLs and secret redaction for a single session.

    Args:
        allowed_namespaces: Whitelist of namespace names this session may
            access.  An empty list means *all* namespaces are allowed
            (useful for development; not recommended in production).
        destructive_actions_enabled: When ``False`` (default), any call to
            :meth:`check_destructive` raises ``PermissionError``.  Must be
            explicitly set to ``True`` to allow restart/delete/scale/rollback.

    Example::

        ctx = SecurityContext(allowed_namespaces=["payments"], destructive_actions_enabled=True)
        ctx.check_destructive("restart_pod")  # OK
    """

    allowed_namespaces: list[str] = field(default_factory=list)
    destructive_actions_enabled: bool = False

    def check_namespace(self, namespace: str) -> None:
        """Assert that *namespace* is in the allowed list.

        Args:
            namespace: The Kubernetes namespace being requested.

        Raises:
            PermissionError: If ``allowed_namespaces`` is non-empty and
                *namespace* is not in it.
        """
        if self.allowed_namespaces and namespace not in self.allowed_namespaces:
            log.warning(
                "Namespace access denied  namespace=%s  allowed=%s",
                namespace,
                self.allowed_namespaces,
            )
            raise PermissionError(
                f"Namespace '{namespace}' is not in the allowed list: "
                f"{self.allowed_namespaces}"
            )
        log.debug("Namespace access granted  namespace=%s", namespace)

    def check_destructive(self, action: str) -> None:
        """Assert that destructive actions are enabled for this session.

        Args:
            action: Human-readable name of the action being attempted
                (used in the error message and log).

        Raises:
            PermissionError: If ``destructive_actions_enabled`` is ``False``.
        """
        if not self.destructive_actions_enabled:
            log.warning("Destructive action blocked  action=%s", action)
            raise PermissionError(
                f"Action '{action}' is not allowed: set DESTRUCTIVE_ACTIONS_ENABLED=true to enable."
            )
        log.debug("Destructive action permitted  action=%s", action)

    def redact(self, data: Any) -> Any:
        """Recursively replace secret values in *data*.

        Walks dicts and lists.  For each dict key whose name matches the
        pattern ``*KEY``, ``*TOKEN``, ``*PASSWORD``, ``*SECRET``, or
        ``*CREDENTIAL`` the value is replaced with ``***REDACTED***``.

        Args:
            data: Arbitrary Python object (dict, list, scalar).

        Returns:
            A new object of the same shape with sensitive values masked.
        """
        if isinstance(data, dict):
            redacted_keys = []
            result = {}
            for k, v in data.items():
                if _SECRET_PATTERN.match(str(k)):
                    result[k] = _REDACTED
                    redacted_keys.append(k)
                else:
                    result[k] = self.redact(v)
            if redacted_keys:
                log.debug("Redacted secret keys: %s", redacted_keys)
            return result
        if isinstance(data, list):
            return [self.redact(item) for item in data]
        return data
