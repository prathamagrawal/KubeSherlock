"""
k8s_mcp.tools.actions
~~~~~~~~~~~~~~~~~~~~~

Destructive remediation actions for incident recovery.

Every method calls ``security.check_destructive()`` first — if
``DESTRUCTIVE_ACTIONS_ENABLED`` is not ``true`` all calls raise
``PermissionError`` before touching the cluster.

Available actions
-----------------
- restart_pod        — delete a pod so its controller recreates it
- delete_pod         — permanently delete a pod (no controller recreate)
- restart_deployment — rolling restart of all pods in a deployment
- scale_deployment   — set replica count on a deployment
- rollback_deployment — roll back a deployment to its previous revision
"""

import logging
from dataclasses import dataclass

from kubernetes.client import V1DeleteOptions

from ..client import K8sClient
from ..security import SecurityContext

log = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """Outcome of a remediation action.

    Attributes:
        action: Name of the action performed.
        namespace: Kubernetes namespace.
        resource: Resource name the action was applied to.
        success: Whether the API call succeeded.
        message: Human-readable summary.
    """

    action: str
    namespace: str
    resource: str
    success: bool
    message: str


class ActionsTool:
    """Performs destructive remediation actions on a Kubernetes cluster.

    All methods are gated by :meth:`~k8s_mcp.security.SecurityContext.check_destructive`.
    Namespace ACL is also enforced via :meth:`~k8s_mcp.security.SecurityContext.check_namespace`.

    Args:
        client: Shared :class:`~k8s_mcp.client.K8sClient` instance.
        security: :class:`~k8s_mcp.security.SecurityContext` for the current
            session.
    """

    def __init__(self, client: K8sClient, security: SecurityContext) -> None:
        self._client = client
        self._security = security

    # ── internal helpers ────────────────────────────────────────────────────

    def _guard(self, action: str, namespace: str) -> None:
        """Run both security checks before any mutating call."""
        self._security.check_destructive(action)
        self._security.check_namespace(namespace)

    # ── pod actions ─────────────────────────────────────────────────────────

    def restart_pod(self, namespace: str, pod_name: str) -> ActionResult:
        """Delete a pod so its owning controller (Deployment/StatefulSet) recreates it.

        This is the standard way to 'restart' a pod — the pod is deleted and
        the controller immediately schedules a replacement.

        Args:
            namespace: Kubernetes namespace.
            pod_name: Name of the pod to restart.

        Returns:
            :class:`ActionResult` indicating success or failure.

        Raises:
            PermissionError: If destructive actions are disabled or namespace
                is not allowed.
        """
        self._guard("restart_pod", namespace)
        log.warning("restart_pod  namespace=%s  pod=%s", namespace, pod_name)
        try:
            self._client.core.delete_namespaced_pod(
                name=pod_name,
                namespace=namespace,
                body=V1DeleteOptions(grace_period_seconds=0),
            )
            msg = f"Pod {pod_name} deleted; controller will recreate it."
            log.info("restart_pod succeeded  namespace=%s  pod=%s", namespace, pod_name)
            return ActionResult("restart_pod", namespace, pod_name, True, msg)
        except Exception as e:
            log.error("restart_pod failed  namespace=%s  pod=%s  error=%s", namespace, pod_name, e)
            return ActionResult("restart_pod", namespace, pod_name, False, str(e))

    def delete_pod(self, namespace: str, pod_name: str, grace_period: int = 30) -> ActionResult:
        """Permanently delete a pod.

        Unlike ``restart_pod``, this uses the standard grace period and is
        appropriate when the pod must be removed without expecting recreation
        (e.g. orphaned pods, pods stuck in Terminating).

        Args:
            namespace: Kubernetes namespace.
            pod_name: Name of the pod to delete.
            grace_period: Seconds to wait before forceful termination.
                Pass ``0`` to force-delete immediately.

        Returns:
            :class:`ActionResult` indicating success or failure.

        Raises:
            PermissionError: If destructive actions are disabled or namespace
                is not allowed.
        """
        self._guard("delete_pod", namespace)
        log.warning("delete_pod  namespace=%s  pod=%s  grace_period=%d", namespace, pod_name, grace_period)
        try:
            self._client.core.delete_namespaced_pod(
                name=pod_name,
                namespace=namespace,
                body=V1DeleteOptions(grace_period_seconds=grace_period),
            )
            msg = f"Pod {pod_name} deleted (grace_period={grace_period}s)."
            log.info("delete_pod succeeded  namespace=%s  pod=%s", namespace, pod_name)
            return ActionResult("delete_pod", namespace, pod_name, True, msg)
        except Exception as e:
            log.error("delete_pod failed  namespace=%s  pod=%s  error=%s", namespace, pod_name, e)
            return ActionResult("delete_pod", namespace, pod_name, False, str(e))

    # ── deployment actions ───────────────────────────────────────────────────

    def restart_deployment(self, namespace: str, deployment_name: str) -> ActionResult:
        """Trigger a rolling restart of all pods in a deployment.

        Patches the deployment's pod template with the current timestamp
        annotation, which forces a rolling restart without changing any
        application config.

        Args:
            namespace: Kubernetes namespace.
            deployment_name: Name of the deployment.

        Returns:
            :class:`ActionResult` indicating success or failure.

        Raises:
            PermissionError: If destructive actions are disabled or namespace
                is not allowed.
        """
        self._guard("restart_deployment", namespace)
        log.warning("restart_deployment  namespace=%s  deployment=%s", namespace, deployment_name)
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            patch = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {"kubectl.kubernetes.io/restartedAt": now}
                        }
                    }
                }
            }
            self._client.apps.patch_namespaced_deployment(
                name=deployment_name, namespace=namespace, body=patch
            )
            msg = f"Deployment {deployment_name} rolling restart triggered."
            log.info("restart_deployment succeeded  namespace=%s  deployment=%s", namespace, deployment_name)
            return ActionResult("restart_deployment", namespace, deployment_name, True, msg)
        except Exception as e:
            log.error("restart_deployment failed  namespace=%s  deployment=%s  error=%s", namespace, deployment_name, e)
            return ActionResult("restart_deployment", namespace, deployment_name, False, str(e))

    def scale_deployment(self, namespace: str, deployment_name: str, replicas: int) -> ActionResult:
        """Set the replica count of a deployment.

        Can be used to scale up (add capacity), scale down (reduce load),
        or scale to zero (effectively stop the workload).

        Args:
            namespace: Kubernetes namespace.
            deployment_name: Name of the deployment.
            replicas: Desired number of replicas (>= 0).

        Returns:
            :class:`ActionResult` indicating success or failure.

        Raises:
            PermissionError: If destructive actions are disabled or namespace
                is not allowed.
            ValueError: If ``replicas`` is negative.
        """
        if replicas < 0:
            raise ValueError(f"replicas must be >= 0, got {replicas}")
        self._guard("scale_deployment", namespace)
        log.warning(
            "scale_deployment  namespace=%s  deployment=%s  replicas=%d",
            namespace, deployment_name, replicas,
        )
        try:
            self._client.apps.patch_namespaced_deployment_scale(
                name=deployment_name,
                namespace=namespace,
                body={"spec": {"replicas": replicas}},
            )
            msg = f"Deployment {deployment_name} scaled to {replicas} replica(s)."
            log.info("scale_deployment succeeded  namespace=%s  deployment=%s  replicas=%d", namespace, deployment_name, replicas)
            return ActionResult("scale_deployment", namespace, deployment_name, True, msg)
        except Exception as e:
            log.error("scale_deployment failed  namespace=%s  deployment=%s  error=%s", namespace, deployment_name, e)
            return ActionResult("scale_deployment", namespace, deployment_name, False, str(e))

    def rollback_deployment(self, namespace: str, deployment_name: str) -> ActionResult:
        """Roll back a deployment to its previous revision.

        Annotates the deployment with ``deployment.kubernetes.io/revision``
        rollback trigger, equivalent to ``kubectl rollout undo``.

        Args:
            namespace: Kubernetes namespace.
            deployment_name: Name of the deployment.

        Returns:
            :class:`ActionResult` indicating success or failure.

        Raises:
            PermissionError: If destructive actions are disabled or namespace
                is not allowed.
        """
        self._guard("rollback_deployment", namespace)
        log.warning("rollback_deployment  namespace=%s  deployment=%s", namespace, deployment_name)
        try:
            # Read current revision
            deploy = self._client.apps.read_namespaced_deployment(
                name=deployment_name, namespace=namespace
            )
            current_rev = int(
                deploy.metadata.annotations.get("deployment.kubernetes.io/revision", "1")
            )
            target_rev = max(1, current_rev - 1)
            patch = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "deployment.kubernetes.io/revision": str(target_rev)
                            }
                        }
                    }
                }
            }
            self._client.apps.patch_namespaced_deployment(
                name=deployment_name, namespace=namespace, body=patch
            )
            msg = f"Deployment {deployment_name} rollback initiated (rev {current_rev} → {target_rev})."
            log.info("rollback_deployment succeeded  namespace=%s  deployment=%s  rev=%d→%d", namespace, deployment_name, current_rev, target_rev)
            return ActionResult("rollback_deployment", namespace, deployment_name, True, msg)
        except Exception as e:
            log.error("rollback_deployment failed  namespace=%s  deployment=%s  error=%s", namespace, deployment_name, e)
            return ActionResult("rollback_deployment", namespace, deployment_name, False, str(e))
