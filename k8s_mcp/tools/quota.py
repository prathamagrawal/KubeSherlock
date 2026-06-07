"""
k8s_mcp.tools.quota
~~~~~~~~~~~~~~~~~~~

ResourceQuota and LimitRange inspection.

ResourceQuota caps total resource consumption per namespace.
LimitRange sets default/min/max per individual pod or container.

Both are common reasons for pods failing to schedule or getting OOMKilled
despite appearing to have headroom.
"""

import logging
from dataclasses import dataclass, field

from ..client import K8sClient
from ..security import SecurityContext

log = logging.getLogger(__name__)


@dataclass
class ResourceQuotaInfo:
    """Usage vs limits for a namespace ResourceQuota.

    Attributes:
        name: ResourceQuota object name.
        namespace: Kubernetes namespace.
        hard: Dict of resource → hard limit (e.g. ``{"pods": "10", "cpu": "4"}``)
        used: Dict of resource → current usage.
        near_limit: Resources at ≥ 80% of their hard limit.
    """
    name: str
    namespace: str
    hard: dict[str, str]
    used: dict[str, str]
    near_limit: list[str]


@dataclass
class LimitRangeInfo:
    """Default and min/max constraints from a LimitRange.

    Attributes:
        name: LimitRange object name.
        namespace: Kubernetes namespace.
        limits: List of limit dicts with ``type``, ``default``, ``defaultRequest``,
            ``min``, ``max`` keys.
    """
    name: str
    namespace: str
    limits: list[dict]


class QuotaTool:
    """Inspects ResourceQuotas and LimitRanges in a namespace.

    Args:
        client: Shared :class:`~k8s_mcp.client.K8sClient` instance.
        security: :class:`~k8s_mcp.security.SecurityContext` for the current session.
    """

    def __init__(self, client: K8sClient, security: SecurityContext) -> None:
        self._client = client
        self._security = security

    def list_resource_quotas(self, namespace: str) -> list[ResourceQuotaInfo]:
        """Return all ResourceQuotas in *namespace* with usage vs hard limits.

        Args:
            namespace: Kubernetes namespace.

        Returns:
            List of :class:`ResourceQuotaInfo`. Includes ``near_limit`` list
            for resources at ≥ 80% utilisation.

        Raises:
            PermissionError: If namespace is not allowed.
        """
        self._security.check_namespace(namespace)
        log.debug("list_resource_quotas  namespace=%s", namespace)
        quotas = self._client.core.list_namespaced_resource_quota(namespace)
        result = [self._to_quota_info(q) for q in quotas.items]
        near = [r for q in result for r in q.near_limit]
        log.info("list_resource_quotas  namespace=%s  count=%d  near_limit=%s",
                 namespace, len(result), near)
        return result

    def list_limit_ranges(self, namespace: str) -> list[LimitRangeInfo]:
        """Return all LimitRanges in *namespace*.

        Args:
            namespace: Kubernetes namespace.

        Returns:
            List of :class:`LimitRangeInfo`.

        Raises:
            PermissionError: If namespace is not allowed.
        """
        self._security.check_namespace(namespace)
        log.debug("list_limit_ranges  namespace=%s", namespace)
        lrs = self._client.core.list_namespaced_limit_range(namespace)
        result = [self._to_lr_info(lr) for lr in lrs.items]
        log.info("list_limit_ranges  namespace=%s  count=%d", namespace, len(result))
        return result

    # ── internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _to_quota_info(q) -> ResourceQuotaInfo:
        hard = {k: str(v) for k, v in (q.status.hard or {}).items()}
        used = {k: str(v) for k, v in (q.status.used or {}).items()}
        near_limit = []
        for resource, hard_val in hard.items():
            used_val = used.get(resource, "0")
            try:
                ratio = _parse_quantity(used_val) / _parse_quantity(hard_val)
                if ratio >= 0.8:
                    near_limit.append(f"{resource} ({used_val}/{hard_val})")
            except (ValueError, ZeroDivisionError):
                pass
        return ResourceQuotaInfo(
            name=q.metadata.name,
            namespace=q.metadata.namespace,
            hard=hard,
            used=used,
            near_limit=near_limit,
        )

    @staticmethod
    def _to_lr_info(lr) -> LimitRangeInfo:
        limits = []
        for item in (lr.spec.limits or []):
            limits.append({
                "type": item.type,
                "default": {k: str(v) for k, v in (item.default or {}).items()},
                "defaultRequest": {k: str(v) for k, v in (item.default_request or {}).items()},
                "min": {k: str(v) for k, v in (item.min or {}).items()},
                "max": {k: str(v) for k, v in (item.max or {}).items()},
            })
        return LimitRangeInfo(
            name=lr.metadata.name,
            namespace=lr.metadata.namespace,
            limits=limits,
        )


def _parse_quantity(value: str) -> float:
    """Parse a Kubernetes quantity string to a float for ratio comparison."""
    suffixes = {
        "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40,
        "k": 1e3, "M": 1e6, "G": 1e9,
        "m": 1e-3,  # millicores
    }
    value = value.strip()
    for suffix, multiplier in suffixes.items():
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * multiplier
    return float(value)
