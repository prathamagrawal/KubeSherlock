"""
K8s MCP Server — exposes Kubernetes diagnostics and remediation as MCP tools.

Usage:
    python -m k8s_mcp.server --namespaces payments checkout

Destructive actions (restart, delete, scale, rollback, exec) are only
registered when DESTRUCTIVE_ACTIONS_ENABLED=true in the environment.
"""

import argparse
import logging
import os
import signal
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).resolve().parent.parent / "config.env")

from .client import K8sClient
from .logging_config import configure_logging
from .security import SecurityContext
from .tools import (
    ActionsTool, ConfigTool, EventsTool, ExecTool, LogsTool,
    MetricsTool, NetworkTool, NodesTool, PodsTool, QuotaTool,
    StorageTool, SummaryTool, WorkloadsTool,
)

configure_logging()
log = logging.getLogger("k8s_mcp.server")

mcp = FastMCP("k8s-sherlock")

# Singletons populated at startup
_pods: PodsTool
_logs: LogsTool
_events: EventsTool
_metrics: MetricsTool
_storage: StorageTool
_config: ConfigTool
_nodes: NodesTool
_workloads: WorkloadsTool
_network: NetworkTool
_quota: QuotaTool
_summary: SummaryTool
_actions: ActionsTool
_exec: ExecTool


def _init(allowed_namespaces: list[str], destructive: bool) -> None:
    global _pods, _logs, _events, _metrics, _storage, _config
    global _nodes, _workloads, _network, _quota, _summary, _actions, _exec
    log.info("Initialising k8s_mcp  allowed_namespaces=%s  destructive=%s",
             allowed_namespaces or "ALL", destructive)
    client = K8sClient()
    security = SecurityContext(allowed_namespaces=allowed_namespaces,
                               destructive_actions_enabled=destructive)
    _pods      = PodsTool(client, security)
    _logs      = LogsTool(client, security)
    _events    = EventsTool(client, security)
    _metrics   = MetricsTool(client, security)
    _storage   = StorageTool(client, security)
    _config    = ConfigTool(client, security)
    _nodes     = NodesTool(client, security)
    _workloads = WorkloadsTool(client, security)
    _network   = NetworkTool(client, security)
    _quota     = QuotaTool(client, security)
    _summary   = SummaryTool(client, security)
    _actions   = ActionsTool(client, security)
    _exec      = ExecTool(client, security)
    log.info("k8s_mcp ready  tools=13")


# ---------------------------------------------------------------------------
# Diagnostic tools (always registered)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_pods(namespace: str) -> str:
    """List pods in a namespace with status and restart counts."""
    import json
    return json.dumps([asdict(p) for p in _pods.list_pods(namespace)])

@mcp.tool()
def describe_pod(namespace: str, pod_name: str) -> dict:
    """Full diagnostic snapshot of a pod: image, node, conditions, restarts."""
    return asdict(_pods.describe_pod(namespace, pod_name))

@mcp.tool()
def get_pod_logs(namespace: str, pod_name: str, tail: int = 100,
                 container: str | None = None, previous: bool = False) -> str:
    """Fetch pod logs. Auto-detects crashing container. previous=True for last crash."""
    return _logs.get_pod_logs(namespace, pod_name, tail, container, previous)

@mcp.tool()
def get_all_container_logs(namespace: str, pod_name: str, tail: int = 50) -> list[dict]:
    """Fetch logs from every container (including init) and previous crashed instances."""
    return [asdict(c) for c in _logs.get_all_container_logs(namespace, pod_name, tail)]

@mcp.tool()
def get_events(namespace: str, warnings_only: bool = True) -> list[dict]:
    """Kubernetes events for a namespace. warnings_only=True by default."""
    return [asdict(e) for e in _events.get_events(namespace, warnings_only)]

@mcp.tool()
def get_pod_metrics(namespace: str) -> list[dict]:
    """Live CPU and memory usage for all pods. Requires metrics-server."""
    return [asdict(m) for m in _metrics.get_pod_metrics(namespace)]

@mcp.tool()
def get_node_metrics() -> list[dict]:
    """Live CPU and memory usage for all nodes. Requires metrics-server."""
    return [asdict(m) for m in _metrics.get_node_metrics()]

@mcp.tool()
def list_pvcs(namespace: str) -> list[dict]:
    """List PersistentVolumeClaims with binding status and capacity."""
    return [asdict(p) for p in _storage.list_pvcs(namespace)]

@mcp.tool()
def describe_pvc(namespace: str, pvc_name: str) -> dict:
    """Describe a single PVC: status, capacity, bound volume."""
    return asdict(_storage.describe_pvc(namespace, pvc_name))

@mcp.tool()
def list_configmaps(namespace: str) -> list[dict]:
    """List ConfigMaps with data (sensitive values redacted)."""
    return [asdict(c) for c in _config.list_configmaps(namespace)]

@mcp.tool()
def get_configmap(namespace: str, name: str) -> dict:
    """Fetch a single ConfigMap's data (sensitive values redacted)."""
    return asdict(_config.get_configmap(namespace, name))

@mcp.tool()
def list_nodes() -> list[dict]:
    """Node health: conditions, pressures, capacity, schedulable status."""
    return [asdict(n) for n in _nodes.list_nodes()]

@mcp.tool()
def describe_node(node_name: str) -> dict:
    """Full health snapshot of a single node."""
    return asdict(_nodes.describe_node(node_name))

@mcp.tool()
def list_deployments(namespace: str) -> list[dict]:
    """Deployment rollout status: desired/ready/available replicas."""
    return [asdict(d) for d in _workloads.list_deployments(namespace)]

@mcp.tool()
def list_statefulsets(namespace: str) -> list[dict]:
    """StatefulSet rollout status: desired/ready replicas, revision info."""
    return [asdict(s) for s in _workloads.list_statefulsets(namespace)]

@mcp.tool()
def list_services(namespace: str) -> list[dict]:
    """List Services with endpoint counts. Zero endpoints = unreachable."""
    return [asdict(s) for s in _network.list_services(namespace)]

@mcp.tool()
def describe_service(namespace: str, service_name: str) -> dict:
    """Full Service details including endpoint count and port mappings."""
    return asdict(_network.describe_service(namespace, service_name))


@mcp.tool()
def list_resource_quotas(namespace: str) -> list[dict]:
    """ResourceQuota usage vs hard limits. Highlights fields at ≥ 80% utilisation."""
    return [asdict(q) for q in _quota.list_resource_quotas(namespace)]

@mcp.tool()
def list_limit_ranges(namespace: str) -> list[dict]:
    """LimitRange defaults and min/max constraints per container type."""
    return [asdict(lr) for lr in _quota.list_limit_ranges(namespace)]

@mcp.tool()
def summarize_pod_health(namespace: str, pod_name: str) -> dict:
    """Full diagnostic report for a pod: logs, events, node, PVCs, quotas, probable causes.
    Call this first on any incident — replaces 6-8 sequential tool calls."""
    return asdict(_summary.summarize_pod_health(namespace, pod_name))


# ---------------------------------------------------------------------------
# Destructive / mutating tools
# ---------------------------------------------------------------------------

def _register_destructive_tools() -> None:

    @mcp.tool()
    def restart_pod(namespace: str, pod_name: str) -> dict:
        """Delete pod so its controller recreates it (instant restart)."""
        return asdict(_actions.restart_pod(namespace, pod_name))

    @mcp.tool()
    def delete_pod(namespace: str, pod_name: str, grace_period: int = 30) -> dict:
        """Permanently delete a pod. grace_period=0 for immediate removal."""
        return asdict(_actions.delete_pod(namespace, pod_name, grace_period))

    @mcp.tool()
    def restart_deployment(namespace: str, deployment_name: str) -> dict:
        """Rolling restart of all pods in a deployment."""
        return asdict(_actions.restart_deployment(namespace, deployment_name))

    @mcp.tool()
    def scale_deployment(namespace: str, deployment_name: str, replicas: int) -> dict:
        """Scale deployment to given replicas. 0 = stop workload."""
        return asdict(_actions.scale_deployment(namespace, deployment_name, replicas))

    @mcp.tool()
    def rollback_deployment(namespace: str, deployment_name: str) -> dict:
        """Roll back deployment to previous revision."""
        return asdict(_actions.rollback_deployment(namespace, deployment_name))

    @mcp.tool()
    def exec_in_pod(namespace: str, pod_name: str, command: list[str],
                    container: str | None = None) -> dict:
        """Run a command inside a container and return stdout/stderr."""
        return asdict(_exec.exec(namespace, pod_name, command, container))

    log.info("Destructive tools registered: restart_pod, delete_pod, restart_deployment, "
             "scale_deployment, rollback_deployment, exec_in_pod")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="KubeSherlock K8s MCP server")
    parser.add_argument("--namespaces", nargs="*", default=None,
                        help="Allowed namespaces (overrides ALLOWED_NAMESPACES env var)")
    args = parser.parse_args()

    if args.namespaces is not None:
        namespaces = args.namespaces
    else:
        raw = os.environ.get("ALLOWED_NAMESPACES", "")
        namespaces = [n.strip() for n in raw.split(",") if n.strip()]

    destructive = os.environ.get("DESTRUCTIVE_ACTIONS_ENABLED", "false").lower() == "true"

    if destructive:
        _register_destructive_tools()
    else:
        log.info("Destructive tools NOT registered (DESTRUCTIVE_ACTIONS_ENABLED=false)")

    _init(namespaces, destructive)

    def _shutdown(signum, frame):
        log.info("Received signal %s — shutting down", signum)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        mcp.run()
    except KeyboardInterrupt:
        log.info("Interrupted — shutting down")
        sys.exit(0)


if __name__ == "__main__":
    main()
