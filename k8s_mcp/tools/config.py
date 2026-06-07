"""
k8s_mcp.tools.config
~~~~~~~~~~~~~~~~~~~~

ConfigMap inspection with automatic secret redaction.

Secret values are never returned. ConfigMaps can reference sensitive data
via env var names — any key matching *KEY, *TOKEN, *PASSWORD, *SECRET,
or *CREDENTIAL is redacted before the data leaves this tool.
"""

import logging
from dataclasses import dataclass

from ..client import K8sClient
from ..security import SecurityContext

log = logging.getLogger(__name__)


@dataclass
class ConfigMapInfo:
    """Contents of a ConfigMap.

    Attributes:
        name: ConfigMap name.
        namespace: Kubernetes namespace.
        data: Key-value pairs (sensitive values redacted).
    """
    name: str
    namespace: str
    data: dict[str, str]


class ConfigTool:
    """Reads ConfigMaps and redacts sensitive values.

    Args:
        client: Shared :class:`~k8s_mcp.client.K8sClient` instance.
        security: :class:`~k8s_mcp.security.SecurityContext` for the current session.
    """

    def __init__(self, client: K8sClient, security: SecurityContext) -> None:
        self._client = client
        self._security = security

    def list_configmaps(self, namespace: str) -> list[ConfigMapInfo]:
        """Return all ConfigMaps in *namespace* with redacted data.

        Args:
            namespace: Kubernetes namespace.

        Returns:
            List of :class:`ConfigMapInfo`.

        Raises:
            PermissionError: If namespace is not allowed.
        """
        self._security.check_namespace(namespace)
        log.debug("list_configmaps  namespace=%s", namespace)
        cms = self._client.core.list_namespaced_config_map(namespace)
        result = [self._to_info(cm) for cm in cms.items]
        log.info("list_configmaps  namespace=%s  count=%d", namespace, len(result))
        return result

    def get_configmap(self, namespace: str, name: str) -> ConfigMapInfo:
        """Return a single ConfigMap with redacted data.

        Args:
            namespace: Kubernetes namespace.
            name: ConfigMap name.

        Returns:
            :class:`ConfigMapInfo` with sensitive values masked.

        Raises:
            PermissionError: If namespace is not allowed.
        """
        self._security.check_namespace(namespace)
        log.debug("get_configmap  namespace=%s  name=%s", namespace, name)
        cm = self._client.core.read_namespaced_config_map(name, namespace)
        info = self._to_info(cm)
        log.info("get_configmap  namespace=%s  name=%s  keys=%d", namespace, name, len(info.data))
        return info

    # ── internal ──────────────────────────────────────────────────────────────

    def _to_info(self, cm) -> ConfigMapInfo:
        raw = cm.data or {}
        return ConfigMapInfo(
            name=cm.metadata.name,
            namespace=cm.metadata.namespace,
            data=self._security.redact(raw),
        )
