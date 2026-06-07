"""
k8s_mcp.tools.summary
~~~~~~~~~~~~~~~~~~~~~

Composite diagnostic tool that aggregates all relevant signals for a pod
into a single structured report.

The AI agent calls this first on every incident to get a complete picture
in one tool call instead of 6–8 sequential calls.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from .events import EventsTool
from .logs import LogsTool
from .metrics import MetricsTool
from .nodes import NodesTool
from .pods import PodsTool
from .quota import QuotaTool
from .storage import StorageTool
from .workloads import WorkloadsTool
from ..client import K8sClient
from ..security import SecurityContext

log = logging.getLogger(__name__)


@dataclass
class PodHealthReport:
    """Complete diagnostic snapshot for a single pod.

    Designed to give an AI agent everything it needs to reason about
    an incident in a single structured object.

    Attributes:
        namespace: Kubernetes namespace.
        pod_name: Pod name.
        status: Pod phase.
        restart_count: Total restarts across all containers.
        node: Node the pod is scheduled on.
        images: Container images.

        crashing_container: Name of the container currently crashing, if any.
        container_states: Per-container state summary list.

        recent_logs: Last 30 lines from the crashing/primary container.
        previous_logs: Last 30 lines from the previous crashed instance, if available.

        warning_events: Warning events involving this pod.

        node_ready: Whether the pod's node is healthy.
        node_pressures: Active node pressure conditions (MemoryPressure, etc.).

        pvc_issues: PVCs bound to this pod's namespace that are not Bound.
        quota_near_limit: Resource quota fields at ≥ 80% in this namespace.

        workload_type: "Deployment", "StatefulSet", or "standalone".
        workload_ready: Ready replicas / desired replicas string, e.g. "2/3".

        pod_metrics: Per-container CPU and memory usage (empty if no metrics-server).

        probable_causes: List of inferred likely root causes based on signals.
    """
    namespace: str
    pod_name: str
    status: str
    restart_count: int
    node: str
    images: list[str]

    crashing_container: str | None
    container_states: list[dict]

    recent_logs: list[str]
    previous_logs: list[str]

    warning_events: list[dict]

    node_ready: bool
    node_pressures: list[str]

    pvc_issues: list[dict]
    quota_near_limit: list[str]

    workload_type: str
    workload_ready: str

    pod_metrics: list[dict]

    probable_causes: list[str]


class SummaryTool:
    """Produces a complete :class:`PodHealthReport` in a single call.

    Aggregates: pod detail, logs (current + previous), events, node health,
    PVC status, resource quotas, workload controller status, and metrics.

    Args:
        client: Shared :class:`~k8s_mcp.client.K8sClient` instance.
        security: :class:`~k8s_mcp.security.SecurityContext` for the current session.
    """

    def __init__(self, client: K8sClient, security: SecurityContext) -> None:
        self._pods      = PodsTool(client, security)
        self._logs      = LogsTool(client, security)
        self._events    = EventsTool(client, security)
        self._metrics   = MetricsTool(client, security)
        self._storage   = StorageTool(client, security)
        self._quota     = QuotaTool(client, security)
        self._nodes     = NodesTool(client, security)
        self._workloads = WorkloadsTool(client, security)
        self._client    = client
        self._security  = security

    def summarize_pod_health(self, namespace: str, pod_name: str) -> PodHealthReport:
        """Gather all diagnostic signals for *pod_name* and return a structured report.

        Args:
            namespace: Kubernetes namespace.
            pod_name: Pod to investigate.

        Returns:
            :class:`PodHealthReport` with all signals populated. Individual
            failures (e.g. metrics-server unavailable) are handled gracefully
            and result in empty fields rather than exceptions.

        Raises:
            PermissionError: If namespace is not allowed.
        """
        self._security.check_namespace(namespace)
        log.info("summarize_pod_health  namespace=%s  pod=%s", namespace, pod_name)

        # ── pod detail ────────────────────────────────────────────────────────
        detail = self._pods.describe_pod(namespace, pod_name)

        # ── container states ──────────────────────────────────────────────────
        raw_pod = self._client.core.read_namespaced_pod(pod_name, namespace)
        container_states, crashing_container = _extract_container_states(raw_pod)

        # ── logs ──────────────────────────────────────────────────────────────
        recent_logs: list[str] = []
        previous_logs: list[str] = []
        if crashing_container:
            try:
                recent_logs = self._logs.get_pod_logs(
                    namespace, pod_name, tail=30, container=crashing_container
                ).splitlines()
            except Exception as e:
                log.debug("Could not fetch recent logs: %s", e)
            try:
                previous_logs = self._logs.get_pod_logs(
                    namespace, pod_name, tail=30, container=crashing_container, previous=True
                ).splitlines()
            except Exception:
                pass

        # ── events filtered to this pod ───────────────────────────────────────
        all_events = self._events.get_events(namespace, warnings_only=True)
        pod_events = [
            {"reason": e.reason, "message": e.message, "count": e.count}
            for e in all_events
            if pod_name in e.involved_object
        ]

        # ── node health ───────────────────────────────────────────────────────
        node_ready, node_pressures = True, []
        if detail.node and detail.node != "Unknown":
            try:
                node_info = self._nodes.describe_node(detail.node)
                node_ready = node_info.ready
                node_pressures = node_info.pressures
            except Exception as e:
                log.debug("Could not fetch node info: %s", e)

        # ── PVC issues ────────────────────────────────────────────────────────
        pvc_issues: list[dict] = []
        try:
            pvcs = self._storage.list_pvcs(namespace)
            pvc_issues = [
                {"name": p.name, "status": p.status, "capacity": p.capacity}
                for p in pvcs if p.status != "Bound"
            ]
        except Exception as e:
            log.debug("Could not fetch PVCs: %s", e)

        # ── quota near limit ──────────────────────────────────────────────────
        quota_near_limit: list[str] = []
        try:
            for q in self._quota.list_resource_quotas(namespace):
                quota_near_limit.extend(q.near_limit)
        except Exception as e:
            log.debug("Could not fetch quotas: %s", e)

        # ── workload controller ───────────────────────────────────────────────
        workload_type, workload_ready = _find_workload(raw_pod, self._workloads, namespace)

        # ── metrics ───────────────────────────────────────────────────────────
        pod_metrics: list[dict] = []
        try:
            all_metrics = self._metrics.get_pod_metrics(namespace)
            for m in all_metrics:
                if m.name == pod_name:
                    pod_metrics = m.containers
                    break
        except Exception:
            pass

        # ── infer probable causes ─────────────────────────────────────────────
        probable_causes = _infer_causes(
            detail, container_states, pod_events, node_pressures,
            pvc_issues, quota_near_limit, pod_metrics, previous_logs,
        )

        log.info("summarize_pod_health complete  namespace=%s  pod=%s  causes=%s",
                 namespace, pod_name, probable_causes)

        return PodHealthReport(
            namespace=namespace,
            pod_name=pod_name,
            status=detail.status,
            restart_count=detail.restart_count,
            node=detail.node,
            images=detail.image,
            crashing_container=crashing_container,
            container_states=container_states,
            recent_logs=recent_logs,
            previous_logs=previous_logs,
            warning_events=pod_events,
            node_ready=node_ready,
            node_pressures=node_pressures,
            pvc_issues=pvc_issues,
            quota_near_limit=quota_near_limit,
            workload_type=workload_type,
            workload_ready=workload_ready,
            pod_metrics=pod_metrics,
            probable_causes=probable_causes,
        )


# ── helpers ───────────────────────────────────────────────────────────────────

def _extract_container_states(raw_pod) -> tuple[list[dict], str | None]:
    """Return (container_states, crashing_container_name)."""
    states = []
    crashing = None

    all_statuses = (
        [(cs, True)  for cs in (raw_pod.status.init_container_statuses or [])]
        + [(cs, False) for cs in (raw_pod.status.container_statuses or [])]
    )

    for cs, is_init in all_statuses:
        state_name, reason, exit_code = "unknown", None, None

        if cs.state.running:
            state_name = "running"
        elif cs.state.waiting:
            state_name = "waiting"
            reason = cs.state.waiting.reason
        elif cs.state.terminated:
            state_name = "terminated"
            reason = cs.state.terminated.reason
            exit_code = cs.state.terminated.exit_code

        if reason in ("CrashLoopBackOff", "Error", "OOMKilled") and crashing is None:
            crashing = cs.name
        if state_name == "terminated" and exit_code and exit_code != 0 and crashing is None:
            crashing = cs.name

        states.append({
            "name": cs.name,
            "is_init": is_init,
            "state": state_name,
            "reason": reason,
            "exit_code": exit_code,
            "restart_count": cs.restart_count,
            "ready": cs.ready,
        })

    # Fallback: first init container if pod is stuck initializing
    if crashing is None and raw_pod.spec.init_containers:
        init_done = any(
            s["is_init"] and s["state"] == "running"
            for s in states
        )
        if not init_done and states:
            crashing = states[0]["name"]

    return states, crashing


def _find_workload(raw_pod, workloads: WorkloadsTool, namespace: str) -> tuple[str, str]:
    """Return (workload_type, 'ready/desired') for the pod's owner."""
    for ref in (raw_pod.metadata.owner_references or []):
        try:
            if ref.kind == "ReplicaSet":
                # owned by a Deployment — find matching deployment
                for d in workloads.list_deployments(namespace):
                    if d.name in ref.name:
                        return "Deployment", f"{d.ready}/{d.desired}"
            elif ref.kind == "StatefulSet":
                for s in workloads.list_statefulsets(namespace):
                    if s.name == ref.name:
                        return "StatefulSet", f"{s.ready}/{s.desired}"
        except Exception:
            pass
    return "standalone", "1/1"


def _infer_causes(
    detail, container_states, events, node_pressures,
    pvc_issues, quota_near_limit, metrics, previous_logs,
) -> list[str]:
    """Return a list of probable root cause strings based on collected signals."""
    causes = []

    # OOMKilled
    for cs in container_states:
        if cs.get("reason") == "OOMKilled":
            causes.append(f"OOMKilled: container '{cs['name']}' exceeded memory limit")

    # CrashLoopBackOff
    crash_containers = [cs["name"] for cs in container_states if cs.get("reason") == "CrashLoopBackOff"]
    if crash_containers:
        causes.append(f"CrashLoopBackOff: {', '.join(crash_containers)} — check logs for exit reason")

    # Non-zero exit code in previous logs
    if previous_logs:
        for line in previous_logs[-5:]:
            if "error" in line.lower() or "fatal" in line.lower() or "exception" in line.lower():
                causes.append(f"Application error in previous run: {line.strip()[:120]}")
                break

    # Node pressure
    if node_pressures:
        causes.append(f"Node pressure: {', '.join(node_pressures)} on node '{detail.node}'")

    # Node not ready
    if not detail.node or detail.node == "Unknown":
        causes.append("Pod not yet scheduled (no node assigned)")

    # PVC unbound
    for pvc in pvc_issues:
        causes.append(f"PVC '{pvc['name']}' is {pvc['status']} — pod may be stuck waiting for storage")

    # Quota
    if quota_near_limit:
        causes.append(f"Resource quota near limit: {'; '.join(quota_near_limit)}")

    # High restarts with no other signal
    if detail.restart_count >= 5 and not causes:
        causes.append(f"High restart count ({detail.restart_count}) — likely repeated application crash")

    # Scheduling events
    for ev in events:
        if ev.get("reason") == "FailedScheduling":
            causes.append(f"Scheduling failure: {ev.get('message', '')[:120]}")
            break

    # BackOff event
    for ev in events:
        if ev.get("reason") == "BackOff":
            causes.append("Kubernetes BackOff: container start being throttled due to repeated failures")
            break

    if not causes:
        causes.append("No obvious cause detected — pod appears healthy or issue is transient")

    return causes
