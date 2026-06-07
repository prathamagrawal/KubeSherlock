"""
k8s_mcp.tools.pods
~~~~~~~~~~~~~~~~~~

Kubernetes pod diagnostics: listing and describing pods.

Classes:
    PodSummary  — lightweight summary returned by list_pods.
    PodDetail   — full diagnostic snapshot returned by describe_pod.
    PodsTool    — stateless tool class; injected with a client and security context.
"""

import logging
from dataclasses import dataclass
from typing import Any

from ..client import K8sClient
from ..security import SecurityContext

log = logging.getLogger(__name__)


@dataclass
class PodSummary:
    """Lightweight pod record used by list_pods.

    Attributes:
        name: Pod name.
        namespace: Kubernetes namespace.
        status: Pod phase (Running, Pending, Failed, …).
        restart_count: Total restarts across all containers in the pod.
    """

    name: str
    namespace: str
    status: str
    restart_count: int


@dataclass
class PodDetail:
    """Full diagnostic snapshot of a single pod used by describe_pod.

    Attributes:
        name: Pod name.
        namespace: Kubernetes namespace.
        node: Node the pod is scheduled on.
        image: List of container image references.
        status: Pod phase (Running, Pending, Failed, …).
        restart_count: Total restarts across all containers.
        conditions: List of pod conditions, each with ``type``, ``status``,
            and ``reason`` keys.
    """

    name: str
    namespace: str
    node: str
    image: list[str]
    status: str
    restart_count: int
    conditions: list[dict[str, Any]]


class PodsTool:
    """Provides pod listing and description against a Kubernetes cluster.

    Args:
        client: Shared :class:`~k8s_mcp.client.K8sClient` instance.
        security: :class:`~k8s_mcp.security.SecurityContext` for the current
            session — enforces namespace ACLs before any API call.
    """

    def __init__(self, client: K8sClient, security: SecurityContext) -> None:
        self._client = client
        self._security = security

    def list_pods(self, namespace: str) -> list[PodSummary]:
        """Return a summary of every pod in *namespace*.

        Args:
            namespace: Kubernetes namespace to query.

        Returns:
            List of :class:`PodSummary` objects ordered by the API response.

        Raises:
            PermissionError: If *namespace* is not in the session's allowlist.
        """
        log.debug("list_pods  namespace=%s", namespace)
        self._security.check_namespace(namespace)
        pods = self._client.core.list_namespaced_pod(namespace)
        result = [
            PodSummary(
                name=p.metadata.name,
                namespace=namespace,
                status=p.status.phase or "Unknown",
                restart_count=sum(
                    cs.restart_count for cs in (p.status.container_statuses or [])
                ),
            )
            for p in pods.items
        ]
        log.info("list_pods  namespace=%s  count=%d", namespace, len(result))
        return result

    def describe_pod(self, namespace: str, pod_name: str) -> PodDetail:
        """Return a full diagnostic snapshot of a single pod.

        Args:
            namespace: Kubernetes namespace containing the pod.
            pod_name: Exact name of the pod.

        Returns:
            :class:`PodDetail` with image, node, conditions, and restart count.

        Raises:
            PermissionError: If *namespace* is not in the session's allowlist.
            kubernetes.client.exceptions.ApiException: If the pod does not exist
                (HTTP 404) or the request is otherwise rejected.
        """
        log.debug("describe_pod  namespace=%s  pod=%s", namespace, pod_name)
        self._security.check_namespace(namespace)
        p = self._client.core.read_namespaced_pod(pod_name, namespace)
        detail = PodDetail(
            name=p.metadata.name,
            namespace=namespace,
            node=p.spec.node_name or "Unknown",
            image=[c.image for c in p.spec.containers],
            status=p.status.phase or "Unknown",
            restart_count=sum(
                cs.restart_count for cs in (p.status.container_statuses or [])
            ),
            conditions=[
                {"type": c.type, "status": c.status, "reason": c.reason}
                for c in (p.status.conditions or [])
            ],
        )
        log.info(
            "describe_pod  namespace=%s  pod=%s  status=%s  restarts=%d",
            namespace, pod_name, detail.status, detail.restart_count,
        )
        return detail
