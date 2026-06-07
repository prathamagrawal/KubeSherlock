"""
k8s_mcp.tools.exec
~~~~~~~~~~~~~~~~~~

Run commands inside pod containers via the Kubernetes exec API.

Gated by ``destructive_actions_enabled`` — exec can modify state inside
containers, so it is treated as a potentially destructive operation.

Safety limits:
- Command must be a list (no shell string injection).
- Output capped at MAX_OUTPUT_BYTES.
"""

import logging
from dataclasses import dataclass

from kubernetes.stream import stream

from ..client import K8sClient
from ..security import SecurityContext

log = logging.getLogger(__name__)

MAX_OUTPUT_BYTES = 32_768  # 32 KB


@dataclass
class ExecResult:
    """Result of a command run inside a container.

    Attributes:
        pod_name: Pod the command was run in.
        container: Container name.
        command: Command that was executed.
        stdout: Standard output (truncated to MAX_OUTPUT_BYTES).
        stderr: Standard error output.
        truncated: True if output was truncated.
    """
    pod_name: str
    container: str
    command: list[str]
    stdout: str
    stderr: str
    truncated: bool


class ExecTool:
    """Executes commands inside pod containers.

    Gated by destructive_actions_enabled — exec can modify container state.

    Args:
        client: Shared :class:`~k8s_mcp.client.K8sClient` instance.
        security: :class:`~k8s_mcp.security.SecurityContext` for the current session.
    """

    def __init__(self, client: K8sClient, security: SecurityContext) -> None:
        self._client = client
        self._security = security

    def exec(
        self,
        namespace: str,
        pod_name: str,
        command: list[str],
        container: str | None = None,
    ) -> ExecResult:
        """Run *command* inside a container and return stdout/stderr.

        Args:
            namespace: Kubernetes namespace.
            pod_name: Pod to exec into.
            command: Command as a list, e.g. ``["pg_autoctl", "show", "state"]``.
                Must NOT be a shell string to prevent injection.
            container: Container name. Auto-selects first container if omitted.

        Returns:
            :class:`ExecResult` with stdout, stderr, and truncation flag.

        Raises:
            PermissionError: If destructive actions are disabled or namespace not allowed.
            ValueError: If command is empty or passed as a string.
        """
        if not command or isinstance(command, str):
            raise ValueError("command must be a non-empty list of strings")

        self._security.check_destructive("exec")
        self._security.check_namespace(namespace)

        log.warning("exec  namespace=%s  pod=%s  container=%s  command=%s",
                    namespace, pod_name, container, command)

        resp = stream(
            self._client.core.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=namespace,
            command=command,
            container=container,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )

        stdout = resp if isinstance(resp, str) else ""
        stderr = ""

        # stream() can return a WSClient — handle both cases
        if hasattr(resp, "read_all"):
            stdout = resp.read_all()
        if hasattr(resp, "read_channel"):
            stderr = resp.read_channel(2)  # channel 2 = stderr

        truncated = len(stdout) > MAX_OUTPUT_BYTES
        if truncated:
            stdout = stdout[:MAX_OUTPUT_BYTES]
            log.warning("exec output truncated to %d bytes", MAX_OUTPUT_BYTES)

        log.info("exec succeeded  namespace=%s  pod=%s  stdout_bytes=%d  stderr_bytes=%d",
                 namespace, pod_name, len(stdout), len(stderr))

        return ExecResult(
            pod_name=pod_name,
            container=container or "(auto)",
            command=command,
            stdout=stdout,
            stderr=stderr,
            truncated=truncated,
        )
