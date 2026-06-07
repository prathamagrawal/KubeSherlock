"""
k8s_mcp.tools.metrics
~~~~~~~~~~~~~~~~~~~~~

Pod and node CPU/memory usage via the Kubernetes Metrics Server API.

Requires metrics-server to be installed in the cluster.
Install on minikube: minikube addons enable metrics-server
"""

import logging
from dataclasses import dataclass

from kubernetes.client import CustomObjectsApi

from ..client import K8sClient
from ..security import SecurityContext

log = logging.getLogger(__name__)

_METRICS_GROUP = "metrics.k8s.io"
_METRICS_VERSION = "v1beta1"


@dataclass
class PodMetrics:
    """CPU and memory usage for a pod.

    Attributes:
        name: Pod name.
        namespace: Kubernetes namespace.
        containers: Per-container usage dicts with keys ``name``, ``cpu``, ``memory``.
    """
    name: str
    namespace: str
    containers: list[dict]


@dataclass
class NodeMetrics:
    """CPU and memory usage for a node.

    Attributes:
        name: Node name.
        cpu: Raw CPU usage string (e.g. ``245m``).
        memory: Raw memory usage string (e.g. ``512Mi``).
    """
    name: str
    cpu: str
    memory: str


class MetricsTool:
    """Fetches live resource usage from the Metrics Server.

    Args:
        client: Shared :class:`~k8s_mcp.client.K8sClient` instance.
        security: :class:`~k8s_mcp.security.SecurityContext` for the current session.
    """

    def __init__(self, client: K8sClient, security: SecurityContext) -> None:
        self._security = security
        self._custom: CustomObjectsApi = CustomObjectsApi(client.core.api_client)

    def get_pod_metrics(self, namespace: str) -> list[PodMetrics]:
        """Return CPU and memory usage for all pods in *namespace*.

        Args:
            namespace: Kubernetes namespace.

        Returns:
            List of :class:`PodMetrics`. Empty if metrics-server is unavailable.

        Raises:
            PermissionError: If namespace is not allowed.
        """
        self._security.check_namespace(namespace)
        log.debug("get_pod_metrics  namespace=%s", namespace)
        try:
            data = self._custom.list_namespaced_custom_object(
                group=_METRICS_GROUP,
                version=_METRICS_VERSION,
                namespace=namespace,
                plural="pods",
            )
            result = [
                PodMetrics(
                    name=item["metadata"]["name"],
                    namespace=namespace,
                    containers=[
                        {
                            "name": c["name"],
                            "cpu": c["usage"]["cpu"],
                            "memory": c["usage"]["memory"],
                        }
                        for c in item.get("containers", [])
                    ],
                )
                for item in data.get("items", [])
            ]
            log.info("get_pod_metrics  namespace=%s  count=%d", namespace, len(result))
            return result
        except Exception as e:
            log.warning("Metrics Server unavailable: %s", e)
            return []

    def get_node_metrics(self) -> list[NodeMetrics]:
        """Return CPU and memory usage for all nodes.

        Returns:
            List of :class:`NodeMetrics`. Empty if metrics-server is unavailable.
        """
        log.debug("get_node_metrics")
        try:
            data = self._custom.list_cluster_custom_object(
                group=_METRICS_GROUP,
                version=_METRICS_VERSION,
                plural="nodes",
            )
            result = [
                NodeMetrics(
                    name=item["metadata"]["name"],
                    cpu=item["usage"]["cpu"],
                    memory=item["usage"]["memory"],
                )
                for item in data.get("items", [])
            ]
            log.info("get_node_metrics  count=%d", len(result))
            return result
        except Exception as e:
            log.warning("Metrics Server unavailable: %s", e)
            return []
