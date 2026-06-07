"""
k8s_mcp.client
~~~~~~~~~~~~~~

Thin singleton wrapper around the Kubernetes Python SDK.

Responsibilities:
- Load kubeconfig once (in-cluster first, then local file fallback).
- Respect KUBECONFIG and KUBE_CONTEXT environment variables.
- Expose typed API handles so tool classes never import the SDK directly.
"""

import logging
import os

from kubernetes import client, config
from kubernetes.client import AppsV1Api, CoreV1Api

log = logging.getLogger(__name__)


class K8sClient:
    """Singleton that initialises the Kubernetes SDK and vends API handles.

    Config resolution order:
    1. In-cluster config (when running inside a pod).
    2. ``KUBECONFIG`` env var path (defaults to ``~/.kube/config``).
    3. Context selected by ``KUBE_CONTEXT`` env var (defaults to
       current-context in the kubeconfig file).

    Example::

        client = K8sClient()
        pods = client.core.list_namespaced_pod("default")
    """

    _instance: "K8sClient | None" = None

    def __new__(cls) -> "K8sClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        """Load kubeconfig and initialise API handles."""
        try:
            config.load_incluster_config()
            log.info("Loaded in-cluster kubeconfig")
        except config.ConfigException:
            kubeconfig = os.environ.get("KUBECONFIG") or None
            context = os.environ.get("KUBE_CONTEXT") or None
            config.load_kube_config(config_file=kubeconfig, context=context)
            log.info(
                "Loaded local kubeconfig  file=%s  context=%s",
                kubeconfig or "~/.kube/config",
                context or "(current-context)",
            )

        self._core: CoreV1Api = client.CoreV1Api()
        self._apps: AppsV1Api = client.AppsV1Api()
        log.debug("K8sClient initialised")

    @property
    def core(self) -> CoreV1Api:
        """CoreV1Api handle — pods, logs, events, configmaps, secrets."""
        return self._core

    @property
    def apps(self) -> AppsV1Api:
        """AppsV1Api handle — deployments, replicasets, statefulsets."""
        return self._apps
