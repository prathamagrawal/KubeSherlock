"""
k8s_mcp.tools.workloads
~~~~~~~~~~~~~~~~~~~~~~~

Deployment and StatefulSet controller status inspection.

Individual pod status is not enough — the controller tells you desired vs
ready replicas, rollout state, and update strategy.
"""

import logging
from dataclasses import dataclass

from ..client import K8sClient
from ..security import SecurityContext

log = logging.getLogger(__name__)


@dataclass
class DeploymentStatus:
    """Rollout status of a Deployment.

    Attributes:
        name: Deployment name.
        namespace: Kubernetes namespace.
        desired: Desired replica count.
        ready: Ready replica count.
        available: Available replica count.
        updated: Replicas updated to latest spec.
        strategy: Update strategy (RollingUpdate or Recreate).
        conditions: List of deployment condition dicts.
    """
    name: str
    namespace: str
    desired: int
    ready: int
    available: int
    updated: int
    strategy: str
    conditions: list[dict]


@dataclass
class StatefulSetStatus:
    """Rollout status of a StatefulSet.

    Attributes:
        name: StatefulSet name.
        namespace: Kubernetes namespace.
        desired: Desired replica count.
        ready: Ready replica count.
        current: Current replica count.
        update_revision: Current update revision.
        current_revision: Running revision.
        ordered: True if pod management policy is OrderedReady.
    """
    name: str
    namespace: str
    desired: int
    ready: int
    current: int
    update_revision: str | None
    current_revision: str | None
    ordered: bool


class WorkloadsTool:
    """Inspects Deployment and StatefulSet controller status.

    Args:
        client: Shared :class:`~k8s_mcp.client.K8sClient` instance.
        security: :class:`~k8s_mcp.security.SecurityContext` for the current session.
    """

    def __init__(self, client: K8sClient, security: SecurityContext) -> None:
        self._client = client
        self._security = security

    def list_deployments(self, namespace: str) -> list[DeploymentStatus]:
        """Return rollout status of all Deployments in *namespace*.

        Raises:
            PermissionError: If namespace is not allowed.
        """
        self._security.check_namespace(namespace)
        log.debug("list_deployments  namespace=%s", namespace)
        deploys = self._client.apps.list_namespaced_deployment(namespace)
        result = [self._deploy_to_status(d) for d in deploys.items]
        degraded = [d for d in result if d.ready < d.desired]
        log.info("list_deployments  namespace=%s  count=%d  degraded=%d",
                 namespace, len(result), len(degraded))
        return result

    def list_statefulsets(self, namespace: str) -> list[StatefulSetStatus]:
        """Return rollout status of all StatefulSets in *namespace*.

        Raises:
            PermissionError: If namespace is not allowed.
        """
        self._security.check_namespace(namespace)
        log.debug("list_statefulsets  namespace=%s", namespace)
        ssets = self._client.apps.list_namespaced_stateful_set(namespace)
        result = [self._sts_to_status(s) for s in ssets.items]
        degraded = [s for s in result if s.ready < s.desired]
        log.info("list_statefulsets  namespace=%s  count=%d  degraded=%d",
                 namespace, len(result), len(degraded))
        return result

    # ── internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _deploy_to_status(d) -> DeploymentStatus:
        s = d.status
        return DeploymentStatus(
            name=d.metadata.name,
            namespace=d.metadata.namespace,
            desired=d.spec.replicas or 0,
            ready=s.ready_replicas or 0,
            available=s.available_replicas or 0,
            updated=s.updated_replicas or 0,
            strategy=d.spec.strategy.type if d.spec.strategy else "Unknown",
            conditions=[
                {"type": c.type, "status": c.status, "reason": c.reason, "message": c.message}
                for c in (s.conditions or [])
            ],
        )

    @staticmethod
    def _sts_to_status(s) -> StatefulSetStatus:
        st = s.status
        return StatefulSetStatus(
            name=s.metadata.name,
            namespace=s.metadata.namespace,
            desired=s.spec.replicas or 0,
            ready=st.ready_replicas or 0,
            current=st.current_replicas or 0,
            update_revision=st.update_revision,
            current_revision=st.current_revision,
            ordered=s.spec.pod_management_policy != "Parallel",
        )
