"""
k8s_mcp.tools.network
~~~~~~~~~~~~~~~~~~~~~

Service and Endpoints inspection.

A pod can be Running but unreachable if it is not in the endpoints list
(failed readiness probe, missing label selector match, etc.).
"""

import logging
from dataclasses import dataclass

from ..client import K8sClient
from ..security import SecurityContext

log = logging.getLogger(__name__)


@dataclass
class ServiceInfo:
    """Summary of a Kubernetes Service.

    Attributes:
        name: Service name.
        namespace: Kubernetes namespace.
        type: Service type (ClusterIP, NodePort, LoadBalancer, ExternalName).
        cluster_ip: Cluster-internal IP.
        ports: List of port dicts with ``port``, ``target_port``, ``protocol``.
        selector: Label selector dict used to find backing pods.
        endpoint_count: Number of ready endpoints (pod IPs) behind this service.
    """
    name: str
    namespace: str
    type: str
    cluster_ip: str
    ports: list[dict]
    selector: dict[str, str]
    endpoint_count: int


class NetworkTool:
    """Inspects Services and their backing Endpoints.

    Args:
        client: Shared :class:`~k8s_mcp.client.K8sClient` instance.
        security: :class:`~k8s_mcp.security.SecurityContext` for the current session.
    """

    def __init__(self, client: K8sClient, security: SecurityContext) -> None:
        self._client = client
        self._security = security

    def list_services(self, namespace: str) -> list[ServiceInfo]:
        """Return all Services in *namespace* with endpoint counts.

        Raises:
            PermissionError: If namespace is not allowed.
        """
        self._security.check_namespace(namespace)
        log.debug("list_services  namespace=%s", namespace)

        services = self._client.core.list_namespaced_service(namespace)
        endpoints_map = self._build_endpoints_map(namespace)

        result = [
            self._to_info(svc, endpoints_map.get(svc.metadata.name, 0))
            for svc in services.items
        ]
        no_endpoints = [s for s in result if s.endpoint_count == 0 and s.selector]
        log.info("list_services  namespace=%s  count=%d  no_endpoints=%d",
                 namespace, len(result), len(no_endpoints))
        return result

    def describe_service(self, namespace: str, service_name: str) -> ServiceInfo:
        """Return details for a single Service including endpoint count.

        Raises:
            PermissionError: If namespace is not allowed.
        """
        self._security.check_namespace(namespace)
        log.debug("describe_service  namespace=%s  service=%s", namespace, service_name)
        svc = self._client.core.read_namespaced_service(service_name, namespace)
        endpoint_count = self._count_endpoints(namespace, service_name)
        info = self._to_info(svc, endpoint_count)
        log.info("describe_service  namespace=%s  service=%s  endpoints=%d",
                 namespace, service_name, info.endpoint_count)
        return info

    # ── internal ──────────────────────────────────────────────────────────────

    def _build_endpoints_map(self, namespace: str) -> dict[str, int]:
        """Return {service_name: ready_endpoint_count} for all services."""
        eps = self._client.core.list_namespaced_endpoints(namespace)
        result = {}
        for ep in eps.items:
            count = sum(
                len(subset.addresses or [])
                for subset in (ep.subsets or [])
            )
            result[ep.metadata.name] = count
        return result

    def _count_endpoints(self, namespace: str, service_name: str) -> int:
        try:
            ep = self._client.core.read_namespaced_endpoints(service_name, namespace)
            return sum(len(s.addresses or []) for s in (ep.subsets or []))
        except Exception:
            return 0

    @staticmethod
    def _to_info(svc, endpoint_count: int) -> ServiceInfo:
        return ServiceInfo(
            name=svc.metadata.name,
            namespace=svc.metadata.namespace,
            type=svc.spec.type or "ClusterIP",
            cluster_ip=svc.spec.cluster_ip or "",
            ports=[
                {
                    "port": p.port,
                    "target_port": str(p.target_port),
                    "protocol": p.protocol,
                }
                for p in (svc.spec.ports or [])
            ],
            selector=svc.spec.selector or {},
            endpoint_count=endpoint_count,
        )
