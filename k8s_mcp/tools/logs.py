"""
k8s_mcp.tools.logs
~~~~~~~~~~~~~~~~~~

Pod log retrieval with:
- Auto-detection of the crashing container (init containers first)
- previous=True support to fetch logs from the last crashed instance
- Hard cap on tail lines to prevent context explosion

Constants:
    MAX_TAIL_LINES: Hard upper bound on lines returned (500).
"""

import logging
from dataclasses import dataclass

from ..client import K8sClient
from ..security import SecurityContext

log = logging.getLogger(__name__)

MAX_TAIL_LINES = 500


@dataclass
class ContainerLogs:
    """Logs from a single container.

    Attributes:
        pod_name: Pod the container belongs to.
        container: Container name.
        is_init: Whether this is an init container.
        previous: Whether these are logs from the previous (crashed) instance.
        lines: Log output as a list of lines.
    """
    pod_name: str
    container: str
    is_init: bool
    previous: bool
    lines: list[str]


class LogsTool:
    """Fetches pod logs from the Kubernetes API.

    Handles multi-container pods by auto-detecting which container is
    crashing and optionally fetching previous-run logs.

    Args:
        client: Shared :class:`~k8s_mcp.client.K8sClient` instance.
        security: :class:`~k8s_mcp.security.SecurityContext` for the current session.
    """

    def __init__(self, client: K8sClient, security: SecurityContext) -> None:
        self._client = client
        self._security = security

    def get_pod_logs(
        self,
        namespace: str,
        pod_name: str,
        tail: int = 100,
        container: str | None = None,
        previous: bool = False,
    ) -> str:
        """Return logs for a container in a pod.

        If *container* is omitted, the crashing container is auto-detected:
        init containers are checked first (in order), then app containers.
        Falls back to the first container if none are in a failed state.

        Args:
            namespace: Kubernetes namespace.
            pod_name: Pod name.
            tail: Lines to return from end of log. Capped at MAX_TAIL_LINES.
            container: Explicit container name. Auto-detected if omitted.
            previous: If True, fetch logs from the previous (crashed) instance.

        Returns:
            Raw log output as a single string.

        Raises:
            PermissionError: If namespace is not allowed.
        """
        self._security.check_namespace(namespace)

        if tail > MAX_TAIL_LINES:
            log.warning("tail=%d exceeds MAX_TAIL_LINES=%d, capping", tail, MAX_TAIL_LINES)
            tail = MAX_TAIL_LINES

        if container is None:
            container = self._detect_crashing_container(namespace, pod_name)

        log.debug("get_pod_logs  namespace=%s  pod=%s  container=%s  previous=%s  tail=%d",
                  namespace, pod_name, container, previous, tail)

        output = self._client.core.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            tail_lines=tail,
            container=container,
            previous=previous,
        )
        log.info("get_pod_logs  namespace=%s  pod=%s  container=%s  previous=%s  bytes=%d",
                 namespace, pod_name, container, previous, len(output))
        return output

    def get_all_container_logs(
        self,
        namespace: str,
        pod_name: str,
        tail: int = 50,
    ) -> list[ContainerLogs]:
        """Fetch logs from every container in a pod, including init containers.

        For any container that has previously crashed, both current and
        previous logs are fetched automatically.

        Args:
            namespace: Kubernetes namespace.
            pod_name: Pod name.
            tail: Lines per container. Capped at MAX_TAIL_LINES.

        Returns:
            List of :class:`ContainerLogs`, one per container per run (current + previous if crashed).
        """
        self._security.check_namespace(namespace)
        tail = min(tail, MAX_TAIL_LINES)

        pod = self._client.core.read_namespaced_pod(pod_name, namespace)
        results: list[ContainerLogs] = []

        init_containers = pod.spec.init_containers or []
        app_containers = pod.spec.containers or []

        all_statuses = {
            cs.name: cs
            for cs in (pod.status.init_container_statuses or [])
                      + (pod.status.container_statuses or [])
        }

        for cname, is_init in (
            [(c.name, True) for c in init_containers]
            + [(c.name, False) for c in app_containers]
        ):
            for previous in self._previous_flags(all_statuses.get(cname)):
                try:
                    raw = self._client.core.read_namespaced_pod_log(
                        name=pod_name,
                        namespace=namespace,
                        container=cname,
                        tail_lines=tail,
                        previous=previous,
                    )
                    results.append(ContainerLogs(
                        pod_name=pod_name,
                        container=cname,
                        is_init=is_init,
                        previous=previous,
                        lines=raw.splitlines(),
                    ))
                except Exception as e:
                    log.debug("Could not fetch logs  container=%s  previous=%s  reason=%s", cname, previous, e)

        log.info("get_all_container_logs  namespace=%s  pod=%s  containers=%d",
                 namespace, pod_name, len(results))
        return results

    # ── internal ──────────────────────────────────────────────────────────────

    def _detect_crashing_container(self, namespace: str, pod_name: str) -> str:
        """Return the name of the container most likely to be crashing."""
        pod = self._client.core.read_namespaced_pod(pod_name, namespace)

        # Check init containers first — a failing init blocks everything
        for cs in (pod.status.init_container_statuses or []):
            if cs.state.waiting and cs.state.waiting.reason in (
                "CrashLoopBackOff", "Error", "OOMKilled"
            ):
                log.debug("Auto-detected crashing init container: %s", cs.name)
                return cs.name
            if cs.last_state.terminated and cs.last_state.terminated.exit_code != 0:
                log.debug("Auto-detected failed init container: %s", cs.name)
                return cs.name

        # Then app containers
        for cs in (pod.status.container_statuses or []):
            if cs.state.waiting and cs.state.waiting.reason in (
                "CrashLoopBackOff", "Error", "OOMKilled"
            ):
                log.debug("Auto-detected crashing app container: %s", cs.name)
                return cs.name

        # Fallback: first init container if still initializing, else first app container
        if pod.spec.init_containers:
            name = pod.spec.init_containers[0].name
            log.debug("Falling back to first init container: %s", name)
            return name

        name = pod.spec.containers[0].name
        log.debug("Falling back to first app container: %s", name)
        return name

    @staticmethod
    def _previous_flags(cs) -> list[bool]:
        """Return [False] normally, [False, True] if container has previously crashed."""
        if cs is None:
            return [False]
        has_previous = (
            cs.last_state.terminated is not None
            if cs.last_state else False
        )
        return [False, True] if has_previous else [False]
