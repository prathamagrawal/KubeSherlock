"""
tests/test_k8s_mcp.py
~~~~~~~~~~~~~~~~~~~~~

Unit tests for the k8s_mcp layer.

The Kubernetes SDK is fully mocked — no cluster required.
Run with:
    pytest tests/test_k8s_mcp.py -v
"""

from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

from k8s_mcp.security import SecurityContext
from k8s_mcp.tools.events import Event, EventsTool
from k8s_mcp.tools.logs import LogsTool, MAX_TAIL_LINES
from k8s_mcp.tools.pods import PodDetail, PodSummary, PodsTool


# ---------------------------------------------------------------------------
# Helpers — build minimal fake SDK objects
# ---------------------------------------------------------------------------


def _make_pod(name: str, phase: str, restarts: int, node: str = "node-1"):
    cs = MagicMock()
    cs.restart_count = restarts

    cond = MagicMock()
    cond.type = "Ready"
    cond.status = "True"
    cond.reason = None

    container = MagicMock()
    container.image = "nginx:latest"

    pod = MagicMock()
    pod.metadata.name = name
    pod.status.phase = phase
    pod.status.container_statuses = [cs]
    pod.status.conditions = [cond]
    pod.spec.node_name = node
    pod.spec.containers = [container]
    return pod


def _make_event(name: str, reason: str, msg: str, kind: str, obj: str, count: int, etype: str = "Warning"):
    ev = MagicMock()
    ev.metadata.name = name
    ev.reason = reason
    ev.message = msg
    ev.type = etype
    ev.involved_object.kind = kind
    ev.involved_object.name = obj
    ev.count = count
    return ev


# ---------------------------------------------------------------------------
# SecurityContext
# ---------------------------------------------------------------------------


class TestSecurityContext:
    def test_allowed_namespace_passes(self):
        ctx = SecurityContext(allowed_namespaces=["payments"])
        ctx.check_namespace("payments")  # must not raise

    def test_blocked_namespace_raises(self):
        ctx = SecurityContext(allowed_namespaces=["payments"])
        with pytest.raises(PermissionError, match="checkout"):
            ctx.check_namespace("checkout")

    def test_empty_allowlist_permits_any(self):
        ctx = SecurityContext()
        ctx.check_namespace("kube-system")  # must not raise

    def test_redact_dict_key(self):
        ctx = SecurityContext()
        result = ctx.redact({"API_KEY": "secret123", "host": "localhost"})
        assert result["API_KEY"] == "***REDACTED***"
        assert result["host"] == "localhost"

    def test_redact_nested(self):
        ctx = SecurityContext()
        result = ctx.redact({"env": [{"DB_PASSWORD": "pass", "name": "app"}]})
        assert result["env"][0]["DB_PASSWORD"] == "***REDACTED***"
        assert result["env"][0]["name"] == "app"

    def test_redact_scalar_passthrough(self):
        ctx = SecurityContext()
        assert ctx.redact("hello") == "hello"
        assert ctx.redact(42) == 42


# ---------------------------------------------------------------------------
# PodsTool
# ---------------------------------------------------------------------------


class TestPodsTool:
    def setup_method(self):
        self.security = SecurityContext(allowed_namespaces=["default"])
        self.mock_client = MagicMock()

    def _tool(self):
        return PodsTool(self.mock_client, self.security)

    def test_list_pods_returns_summaries(self):
        self.mock_client.core.list_namespaced_pod.return_value.items = [
            _make_pod("pod-a", "Running", 0),
            _make_pod("pod-b", "Failed", 3),
        ]
        result = self._tool().list_pods("default")
        assert len(result) == 2
        assert all(isinstance(p, PodSummary) for p in result)
        assert result[1].restart_count == 3
        assert result[1].status == "Failed"

    def test_list_pods_blocked_namespace(self):
        with pytest.raises(PermissionError):
            self._tool().list_pods("kube-system")

    def test_describe_pod_returns_detail(self):
        self.mock_client.core.read_namespaced_pod.return_value = _make_pod(
            "pod-a", "Running", 2
        )
        result = self._tool().describe_pod("default", "pod-a")
        assert isinstance(result, PodDetail)
        assert result.name == "pod-a"
        assert result.restart_count == 2
        assert result.image == ["nginx:latest"]
        assert result.node == "node-1"

    def test_describe_pod_blocked_namespace(self):
        with pytest.raises(PermissionError):
            self._tool().describe_pod("prod", "pod-a")

    def test_list_pods_empty_namespace(self):
        self.mock_client.core.list_namespaced_pod.return_value.items = []
        result = self._tool().list_pods("default")
        assert result == []


# ---------------------------------------------------------------------------
# LogsTool
# ---------------------------------------------------------------------------


class TestLogsTool:
    def setup_method(self):
        self.security = SecurityContext(allowed_namespaces=["default"])
        self.mock_client = MagicMock()
        self.mock_client.core.read_namespaced_pod_log.return_value = "log line 1\nlog line 2"

    def _tool(self):
        return LogsTool(self.mock_client, self.security)

    def test_returns_log_string(self):
        result = self._tool().get_pod_logs("default", "pod-a", tail=50)
        assert "log line 1" in result
        # Container is auto-detected (first init container) when not specified
        call_args = self.mock_client.core.read_namespaced_pod_log.call_args
        assert call_args[1]["name"] == "pod-a"
        assert call_args[1]["namespace"] == "default"
        assert call_args[1]["tail_lines"] == 50

    def test_tail_capped_at_max(self):
        self._tool().get_pod_logs("default", "pod-a", tail=9999)
        call_kwargs = self.mock_client.core.read_namespaced_pod_log.call_args.kwargs
        assert call_kwargs["tail_lines"] == MAX_TAIL_LINES

    def test_container_arg_forwarded(self):
        self._tool().get_pod_logs("default", "pod-a", tail=10, container="sidecar")
        call_kwargs = self.mock_client.core.read_namespaced_pod_log.call_args.kwargs
        assert call_kwargs["container"] == "sidecar"

    def test_blocked_namespace_raises(self):
        with pytest.raises(PermissionError):
            self._tool().get_pod_logs("prod", "pod-a")


# ---------------------------------------------------------------------------
# EventsTool
# ---------------------------------------------------------------------------


class TestEventsTool:
    def setup_method(self):
        self.security = SecurityContext(allowed_namespaces=["default"])
        self.mock_client = MagicMock()

    def _tool(self):
        return EventsTool(self.mock_client, self.security)

    def _setup_events(self):
        self.mock_client.core.list_namespaced_event.return_value.items = [
            _make_event("ev-1", "OOMKilling", "OOM detected", "Pod", "pod-a", 3, "Warning"),
            _make_event("ev-2", "Pulled", "Image pulled", "Pod", "pod-b", 1, "Normal"),
        ]

    def test_warnings_only_by_default(self):
        self._setup_events()
        result = self._tool().get_events("default")
        assert len(result) == 1
        assert result[0].reason == "OOMKilling"

    def test_all_events_when_flag_false(self):
        self._setup_events()
        result = self._tool().get_events("default", warnings_only=False)
        assert len(result) == 2

    def test_event_fields(self):
        self._setup_events()
        ev = self._tool().get_events("default")[0]
        assert isinstance(ev, Event)
        assert ev.involved_object == "Pod/pod-a"
        assert ev.count == 3

    def test_blocked_namespace_raises(self):
        with pytest.raises(PermissionError):
            self._tool().get_events("prod")

    def test_empty_events(self):
        self.mock_client.core.list_namespaced_event.return_value.items = []
        assert self._tool().get_events("default") == []


# ---------------------------------------------------------------------------
# ActionsTool
# ---------------------------------------------------------------------------

from k8s_mcp.tools.actions import ActionsTool, ActionResult


class TestCheckDestructive:
    def test_disabled_by_default(self):
        ctx = SecurityContext()
        assert ctx.destructive_actions_enabled is False
        with pytest.raises(PermissionError, match="DESTRUCTIVE_ACTIONS_ENABLED"):
            ctx.check_destructive("restart_pod")

    def test_enabled(self):
        ctx = SecurityContext(destructive_actions_enabled=True)
        ctx.check_destructive("restart_pod")  # must not raise


class TestActionsTool:
    def setup_method(self):
        self.mock_client = MagicMock()
        # security with destructive ON and namespace allowed
        self.security = SecurityContext(
            allowed_namespaces=["default"],
            destructive_actions_enabled=True,
        )
        self.tool = ActionsTool(self.mock_client, self.security)

    def _blocked_tool(self):
        """ActionsTool with destructive actions disabled."""
        return ActionsTool(
            self.mock_client,
            SecurityContext(allowed_namespaces=["default"], destructive_actions_enabled=False),
        )

    # guard tests

    def test_restart_pod_blocked_when_disabled(self):
        with pytest.raises(PermissionError):
            self._blocked_tool().restart_pod("default", "pod-a")

    def test_delete_pod_blocked_when_disabled(self):
        with pytest.raises(PermissionError):
            self._blocked_tool().delete_pod("default", "pod-a")

    def test_restart_deployment_blocked_when_disabled(self):
        with pytest.raises(PermissionError):
            self._blocked_tool().restart_deployment("default", "deploy-a")

    def test_scale_deployment_blocked_when_disabled(self):
        with pytest.raises(PermissionError):
            self._blocked_tool().scale_deployment("default", "deploy-a", 3)

    def test_rollback_deployment_blocked_when_disabled(self):
        with pytest.raises(PermissionError):
            self._blocked_tool().rollback_deployment("default", "deploy-a")

    def test_namespace_block_still_enforced(self):
        with pytest.raises(PermissionError):
            self.tool.restart_pod("prod", "pod-a")

    # restart_pod

    def test_restart_pod_success(self):
        result = self.tool.restart_pod("default", "pod-a")
        assert isinstance(result, ActionResult)
        assert result.success is True
        assert result.action == "restart_pod"
        self.mock_client.core.delete_namespaced_pod.assert_called_once()

    def test_restart_pod_api_failure_returns_result(self):
        self.mock_client.core.delete_namespaced_pod.side_effect = Exception("not found")
        result = self.tool.restart_pod("default", "pod-a")
        assert result.success is False
        assert "not found" in result.message

    # delete_pod

    def test_delete_pod_success(self):
        result = self.tool.delete_pod("default", "pod-a", grace_period=0)
        assert result.success is True
        call_kwargs = self.mock_client.core.delete_namespaced_pod.call_args.kwargs
        assert call_kwargs["body"].grace_period_seconds == 0

    # restart_deployment

    def test_restart_deployment_success(self):
        result = self.tool.restart_deployment("default", "deploy-a")
        assert result.success is True
        self.mock_client.apps.patch_namespaced_deployment.assert_called_once()
        patch_body = self.mock_client.apps.patch_namespaced_deployment.call_args.kwargs["body"]
        assert "kubectl.kubernetes.io/restartedAt" in patch_body["spec"]["template"]["metadata"]["annotations"]

    # scale_deployment

    def test_scale_deployment_success(self):
        result = self.tool.scale_deployment("default", "deploy-a", 3)
        assert result.success is True
        body = self.mock_client.apps.patch_namespaced_deployment_scale.call_args.kwargs["body"]
        assert body["spec"]["replicas"] == 3

    def test_scale_deployment_negative_raises(self):
        with pytest.raises(ValueError):
            self.tool.scale_deployment("default", "deploy-a", -1)

    def test_scale_to_zero(self):
        result = self.tool.scale_deployment("default", "deploy-a", 0)
        assert result.success is True

    # rollback_deployment

    def test_rollback_deployment_success(self):
        deploy = MagicMock()
        deploy.metadata.annotations = {"deployment.kubernetes.io/revision": "3"}
        self.mock_client.apps.read_namespaced_deployment.return_value = deploy

        result = self.tool.rollback_deployment("default", "deploy-a")
        assert result.success is True
        assert "3 → 2" in result.message
