"""
k8s_mcp.tools.storage
~~~~~~~~~~~~~~~~~~~~~

PersistentVolumeClaim and PersistentVolume inspection.

Useful for diagnosing pods stuck in Pending due to unbound PVCs,
or init containers failing because of missing/corrupt data directories.
"""

import logging
from dataclasses import dataclass

from ..client import K8sClient
from ..security import SecurityContext

log = logging.getLogger(__name__)


@dataclass
class PVCInfo:
    """Status of a PersistentVolumeClaim.

    Attributes:
        name: PVC name.
        namespace: Kubernetes namespace.
        status: Binding phase (Bound, Pending, Lost).
        storage_class: StorageClass name.
        capacity: Allocated storage (e.g. ``1Gi``). None if unbound.
        access_modes: List of access modes (ReadWriteOnce, etc.).
        volume_name: Bound PV name. None if unbound.
    """
    name: str
    namespace: str
    status: str
    storage_class: str | None
    capacity: str | None
    access_modes: list[str]
    volume_name: str | None


class StorageTool:
    """Inspects PersistentVolumeClaims and PersistentVolumes.

    Args:
        client: Shared :class:`~k8s_mcp.client.K8sClient` instance.
        security: :class:`~k8s_mcp.security.SecurityContext` for the current session.
    """

    def __init__(self, client: K8sClient, security: SecurityContext) -> None:
        self._client = client
        self._security = security

    def list_pvcs(self, namespace: str) -> list[PVCInfo]:
        """Return all PVCs in *namespace* with binding status.

        Args:
            namespace: Kubernetes namespace.

        Returns:
            List of :class:`PVCInfo`. Unbound PVCs have None for capacity and volume_name.

        Raises:
            PermissionError: If namespace is not allowed.
        """
        self._security.check_namespace(namespace)
        log.debug("list_pvcs  namespace=%s", namespace)
        pvcs = self._client.core.list_namespaced_persistent_volume_claim(namespace)
        result = [self._to_info(p) for p in pvcs.items]
        log.info("list_pvcs  namespace=%s  count=%d  unbound=%d",
                 namespace, len(result), sum(1 for p in result if p.status != "Bound"))
        return result

    def describe_pvc(self, namespace: str, pvc_name: str) -> PVCInfo:
        """Return details for a single PVC.

        Args:
            namespace: Kubernetes namespace.
            pvc_name: PVC name.

        Returns:
            :class:`PVCInfo` for the requested PVC.

        Raises:
            PermissionError: If namespace is not allowed.
        """
        self._security.check_namespace(namespace)
        log.debug("describe_pvc  namespace=%s  pvc=%s", namespace, pvc_name)
        pvc = self._client.core.read_namespaced_persistent_volume_claim(pvc_name, namespace)
        info = self._to_info(pvc)
        log.info("describe_pvc  namespace=%s  pvc=%s  status=%s  volume=%s",
                 namespace, pvc_name, info.status, info.volume_name)
        return info

    # ── internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _to_info(pvc) -> PVCInfo:
        capacity = None
        if pvc.status.capacity:
            capacity = pvc.status.capacity.get("storage")
        return PVCInfo(
            name=pvc.metadata.name,
            namespace=pvc.metadata.namespace,
            status=pvc.status.phase or "Unknown",
            storage_class=pvc.spec.storage_class_name,
            capacity=capacity,
            access_modes=pvc.status.access_modes or [],
            volume_name=pvc.spec.volume_name or None,
        )
