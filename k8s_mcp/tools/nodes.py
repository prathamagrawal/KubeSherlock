"""
k8s_mcp.tools.nodes
~~~~~~~~~~~~~~~~~~~

Node health inspection: conditions, resource pressure, capacity,
and cordoned status.

Critical for diagnosing FailedScheduling events — a pod stuck in Pending
often means the node has memory/disk pressure or is cordoned.
"""

import logging
from dataclasses import dataclass

from ..client import K8sClient
from ..security import SecurityContext

log = logging.getLogger(__name__)


@dataclass
class NodeInfo:
    """Health snapshot of a Kubernetes node.

    Attributes:
        name: Node name.
        ready: Whether the node is in Ready condition.
        schedulable: False if the node is cordoned (unschedulable).
        conditions: List of condition dicts with ``type``, ``status``, ``reason``.
        capacity: Dict of allocatable resources (cpu, memory, pods, etc.).
        pressures: List of active pressure condition names (MemoryPressure, DiskPressure, etc.).
    """
    name: str
    ready: bool
    schedulable: bool
    conditions: list[dict]
    capacity: dict[str, str]
    pressures: list[str]


class NodesTool:
    """Inspects Kubernetes node health.

    Does not require a namespace — nodes are cluster-scoped.
    Namespace ACL check is skipped for node queries.

    Args:
        client: Shared :class:`~k8s_mcp.client.K8sClient` instance.
        security: Unused for namespace checks but kept for consistency.
    """

    def __init__(self, client: K8sClient, security: SecurityContext) -> None:
        self._client = client
        self._security = security

    def list_nodes(self) -> list[NodeInfo]:
        """Return health snapshots of all nodes in the cluster.

        Returns:
            List of :class:`NodeInfo` with conditions, pressures, and capacity.
        """
        log.debug("list_nodes")
        nodes = self._client.core.list_node()
        result = [self._to_info(n) for n in nodes.items]
        unhealthy = [n for n in result if not n.ready or n.pressures]
        log.info("list_nodes  count=%d  unhealthy=%d", len(result), len(unhealthy))
        return result

    def describe_node(self, node_name: str) -> NodeInfo:
        """Return a health snapshot for a specific node.

        Args:
            node_name: Name of the node.

        Returns:
            :class:`NodeInfo` for the requested node.
        """
        log.debug("describe_node  node=%s", node_name)
        node = self._client.core.read_node(node_name)
        info = self._to_info(node)
        log.info("describe_node  node=%s  ready=%s  schedulable=%s  pressures=%s",
                 node_name, info.ready, info.schedulable, info.pressures)
        return info

    # ── internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _to_info(node) -> NodeInfo:
        conditions = [
            {"type": c.type, "status": c.status, "reason": c.reason}
            for c in (node.status.conditions or [])
        ]
        ready = any(
            c["type"] == "Ready" and c["status"] == "True"
            for c in conditions
        )
        pressures = [
            c["type"] for c in conditions
            if c["type"] in ("MemoryPressure", "DiskPressure", "PIDPressure")
            and c["status"] == "True"
        ]
        capacity = {
            k: v for k, v in (node.status.allocatable or {}).items()
        }
        return NodeInfo(
            name=node.metadata.name,
            ready=ready,
            schedulable=not node.spec.unschedulable,
            conditions=conditions,
            capacity=capacity,
            pressures=pressures,
        )
