"""
tests/test_k8s_tools_extended.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Extended unit tests for KubeSherlock Kubernetes MCP tools.
Covers: WorkloadsTool, NodesTool, NetworkTool, StorageTool, ConfigTool,
        QuotaTool, MetricsTool, ExecTool, SummaryTool.

The Kubernetes SDK is fully mocked — no cluster required.
"""

import pytest
from unittest.mock import MagicMock, patch

from k8s_mcp.security import SecurityContext
from k8s_mcp.tools.workloads import WorkloadsTool, DeploymentStatus, StatefulSetStatus
from k8s_mcp.tools.nodes import NodesTool, NodeInfo
from k8s_mcp.tools.network import NetworkTool, ServiceInfo
from k8s_mcp.tools.storage import StorageTool, PVCInfo
from k8s_mcp.tools.config import ConfigTool, ConfigMapInfo
from k8s_mcp.tools.quota import QuotaTool, ResourceQuotaInfo, LimitRangeInfo, _parse_quantity
from k8s_mcp.tools.metrics import MetricsTool, PodMetrics, NodeMetrics
from k8s_mcp.tools.exec import ExecTool, ExecResult, MAX_OUTPUT_BYTES
from k8s_mcp.tools.summary import SummaryTool, PodHealthReport


# ─────────────────────────────────────────────────────────────────────────────
# WorkloadsTool
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkloadsTool:

    def test_list_deployments_returns_correct_data(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])
        tool = WorkloadsTool(client, security)

        # Mock list_namespaced_deployment response
        d = MagicMock()
        d.metadata.name = "web"
        d.metadata.namespace = "default"
        d.spec.replicas = 3
        d.spec.strategy.type = "RollingUpdate"
        d.status.ready_replicas = 2
        d.status.available_replicas = 2
        d.status.updated_replicas = 2
        
        cond = MagicMock()
        cond.type = "Available"
        cond.status = "True"
        cond.reason = "MinimumReplicasAvailable"
        cond.message = "Deployment has minimum availability."
        d.status.conditions = [cond]

        client.apps.list_namespaced_deployment.return_value.items = [d]

        result = tool.list_deployments("default")
        assert len(result) == 1
        assert isinstance(result[0], DeploymentStatus)
        assert result[0].name == "web"
        assert result[0].desired == 3
        assert result[0].ready == 2
        assert result[0].strategy == "RollingUpdate"
        assert len(result[0].conditions) == 1

    def test_list_deployments_blocked_namespace_raises(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])
        tool = WorkloadsTool(client, security)

        with pytest.raises(PermissionError):
            tool.list_deployments("kube-system")

    def test_list_statefulsets_returns_correct_data(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])
        tool = WorkloadsTool(client, security)

        s = MagicMock()
        s.metadata.name = "db"
        s.metadata.namespace = "default"
        s.spec.replicas = 3
        s.spec.pod_management_policy = "OrderedReady"
        s.status.ready_replicas = 3
        s.status.current_replicas = 3
        s.status.update_revision = "db-1"
        s.status.current_revision = "db-1"

        client.apps.list_namespaced_stateful_set.return_value.items = [s]

        result = tool.list_statefulsets("default")
        assert len(result) == 1
        assert isinstance(result[0], StatefulSetStatus)
        assert result[0].name == "db"
        assert result[0].desired == 3
        assert result[0].ready == 3
        assert result[0].ordered is True

    def test_list_statefulsets_blocked_namespace_raises(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])
        tool = WorkloadsTool(client, security)

        with pytest.raises(PermissionError):
            tool.list_statefulsets("kube-system")


# ─────────────────────────────────────────────────────────────────────────────
# NodesTool
# ─────────────────────────────────────────────────────────────────────────────

class TestNodesTool:

    def test_list_nodes_returns_correct_data(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["*"])
        tool = NodesTool(client, security)

        n = MagicMock()
        n.metadata.name = "node-1"
        n.spec.unschedulable = False
        
        c1 = MagicMock()
        c1.type = "Ready"
        c1.status = "True"
        c1.reason = "KubeletReady"
        
        c2 = MagicMock()
        c2.type = "MemoryPressure"
        c2.status = "False"
        c2.reason = "KubeletHasSufficientMemory"

        n.status.conditions = [c1, c2]
        n.status.allocatable = {"cpu": "4", "memory": "16Gi"}
        client.core.list_node.return_value.items = [n]

        result = tool.list_nodes()
        assert len(result) == 1
        assert isinstance(result[0], NodeInfo)
        assert result[0].name == "node-1"
        assert result[0].ready is True
        assert result[0].schedulable is True
        assert result[0].pressures == []
        assert result[0].capacity == {"cpu": "4", "memory": "16Gi"}

    def test_describe_node_returns_snapshot(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["*"])
        tool = NodesTool(client, security)

        n = MagicMock()
        n.metadata.name = "node-2"
        n.spec.unschedulable = True
        
        c1 = MagicMock()
        c1.type = "Ready"
        c1.status = "False"
        c1.reason = "KubeletNotReady"

        n.status.conditions = [c1]
        n.status.allocatable = {"cpu": "2"}
        client.core.read_node.return_value = n

        result = tool.describe_node("node-2")
        assert result.name == "node-2"
        assert result.ready is False
        assert result.schedulable is False


# ─────────────────────────────────────────────────────────────────────────────
# NetworkTool
# ─────────────────────────────────────────────────────────────────────────────

class TestNetworkTool:

    def test_list_services_returns_endpoint_counts(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])
        tool = NetworkTool(client, security)

        svc = MagicMock()
        svc.metadata.name = "my-service"
        svc.metadata.namespace = "default"
        svc.spec.type = "ClusterIP"
        svc.spec.cluster_ip = "10.96.0.1"
        
        port = MagicMock()
        port.port = 80
        port.target_port = 8080
        port.protocol = "TCP"
        svc.spec.ports = [port]
        svc.spec.selector = {"app": "web"}

        client.core.list_namespaced_service.return_value.items = [svc]

        # Mock list_namespaced_endpoints response
        ep = MagicMock()
        ep.metadata.name = "my-service"
        addr = MagicMock()
        subset = MagicMock()
        subset.addresses = [addr, addr] # 2 endpoints
        ep.subsets = [subset]
        client.core.list_namespaced_endpoints.return_value.items = [ep]

        result = tool.list_services("default")
        assert len(result) == 1
        assert isinstance(result[0], ServiceInfo)
        assert result[0].name == "my-service"
        assert result[0].endpoint_count == 2

    def test_describe_service_blocked_namespace_raises(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])
        tool = NetworkTool(client, security)

        with pytest.raises(PermissionError):
            tool.describe_service("kube-system", "my-service")


# ─────────────────────────────────────────────────────────────────────────────
# StorageTool
# ─────────────────────────────────────────────────────────────────────────────

class TestStorageTool:

    def test_list_pvcs_returns_bound_and_unbound(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])
        tool = StorageTool(client, security)

        pvc_bound = MagicMock()
        pvc_bound.metadata.name = "data-bound"
        pvc_bound.metadata.namespace = "default"
        pvc_bound.status.phase = "Bound"
        pvc_bound.spec.storage_class_name = "standard"
        pvc_bound.status.capacity = {"storage": "1Gi"}
        pvc_bound.status.access_modes = ["ReadWriteOnce"]
        pvc_bound.spec.volume_name = "pv-001"

        pvc_unbound = MagicMock()
        pvc_unbound.metadata.name = "data-unbound"
        pvc_unbound.metadata.namespace = "default"
        pvc_unbound.status.phase = "Pending"
        pvc_unbound.spec.storage_class_name = "standard"
        pvc_unbound.status.capacity = None
        pvc_unbound.status.access_modes = None
        pvc_unbound.spec.volume_name = None

        client.core.list_namespaced_persistent_volume_claim.return_value.items = [pvc_bound, pvc_unbound]

        result = tool.list_pvcs("default")
        assert len(result) == 2
        
        # Bound assertions
        assert result[0].name == "data-bound"
        assert result[0].status == "Bound"
        assert result[0].capacity == "1Gi"
        assert result[0].volume_name == "pv-001"

        # Unbound assertions
        assert result[1].name == "data-unbound"
        assert result[1].status == "Pending"
        assert result[1].capacity is None
        assert result[1].volume_name is None

    def test_describe_pvc_blocked_namespace_raises(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])
        tool = StorageTool(client, security)

        with pytest.raises(PermissionError):
            tool.describe_pvc("kube-system", "claim")


# ─────────────────────────────────────────────────────────────────────────────
# ConfigTool
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigTool:

    def test_get_configmap_redacts_sensitive_values(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])
        tool = ConfigTool(client, security)

        cm = MagicMock()
        cm.metadata.name = "my-config"
        cm.metadata.namespace = "default"
        cm.data = {
            "DB_HOST": "postgres",
            "DB_PASSWORD": "supersecretpassword",
            "API_KEY": "secretkeyvalue",
        }
        client.core.read_namespaced_config_map.return_value = cm

        result = tool.get_configmap("default", "my-config")
        assert isinstance(result, ConfigMapInfo)
        assert result.name == "my-config"
        assert result.data["DB_HOST"] == "postgres"
        assert result.data["DB_PASSWORD"] == "***REDACTED***"
        assert result.data["API_KEY"] == "***REDACTED***"

    def test_list_configmaps_blocked_namespace_raises(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])
        tool = ConfigTool(client, security)

        with pytest.raises(PermissionError):
            tool.list_configmaps("kube-system")


# ─────────────────────────────────────────────────────────────────────────────
# QuotaTool
# ─────────────────────────────────────────────────────────────────────────────

class TestQuotaTool:

    def test_list_resource_quotas_identifies_near_limit(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])
        tool = QuotaTool(client, security)

        q = MagicMock()
        q.metadata.name = "my-quota"
        q.metadata.namespace = "default"
        q.status.hard = {"pods": "10", "cpu": "4", "memory": "8Gi"}
        # cpu (3.5/4 >= 0.8) should be in near_limit; memory (4Gi/8Gi < 0.8) should not
        q.status.used = {"pods": "2", "cpu": "3.5", "memory": "4Gi"}

        client.core.list_namespaced_resource_quota.return_value.items = [q]

        result = tool.list_resource_quotas("default")
        assert len(result) == 1
        assert isinstance(result[0], ResourceQuotaInfo)
        assert "cpu (3.5/4)" in result[0].near_limit[0]
        assert len(result[0].near_limit) == 1

    def test_list_limit_ranges_returns_spec_ranges(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])
        tool = QuotaTool(client, security)

        lr = MagicMock()
        lr.metadata.name = "my-limits"
        lr.metadata.namespace = "default"
        
        limit_item = MagicMock()
        limit_item.type = "Container"
        limit_item.default = {"memory": "512Mi"}
        limit_item.default_request = {"memory": "256Mi"}
        limit_item.min = {"memory": "64Mi"}
        limit_item.max = {"memory": "1Gi"}
        
        lr.spec.limits = [limit_item]
        client.core.list_namespaced_limit_range.return_value.items = [lr]

        result = tool.list_limit_ranges("default")
        assert len(result) == 1
        assert isinstance(result[0], LimitRangeInfo)
        assert result[0].limits[0]["type"] == "Container"
        assert result[0].limits[0]["default"] == {"memory": "512Mi"}

    def test_parse_quantity_helper(self):
        assert _parse_quantity("10") == 10.0
        assert _parse_quantity("1Ki") == 1024.0
        assert _parse_quantity("2Mi") == 2097152.0
        assert _parse_quantity("3Gi") == 3221225472.0
        assert _parse_quantity("500m") == 0.5
        assert _parse_quantity("2.5") == 2.5


# ─────────────────────────────────────────────────────────────────────────────
# MetricsTool
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricsTool:

    def test_get_pod_metrics_returns_list(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])

        # Mock custom api response structure
        # CustomObjectsApi is instantiated dynamically inside MetricsTool
        with patch("k8s_mcp.tools.metrics.CustomObjectsApi") as mock_custom_cls:
            mock_custom = mock_custom_cls.return_value
            mock_custom.list_namespaced_custom_object.return_value = {
                "items": [
                    {
                        "metadata": {"name": "web-pod"},
                        "containers": [
                            {
                                "name": "nginx",
                                "usage": {"cpu": "120m", "memory": "256Mi"}
                            }
                        ]
                    }
                ]
            }

            tool = MetricsTool(client, security)
            result = tool.get_pod_metrics("default")
            assert len(result) == 1
            assert isinstance(result[0], PodMetrics)
            assert result[0].name == "web-pod"
            assert result[0].containers[0]["name"] == "nginx"

    def test_get_pod_metrics_unavailable_swallows_exception(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])

        with patch("k8s_mcp.tools.metrics.CustomObjectsApi") as mock_custom_cls:
            mock_custom = mock_custom_cls.return_value
            mock_custom.list_namespaced_custom_object.side_effect = Exception("API Not Found")
            
            tool = MetricsTool(client, security)
            # Should not raise exception
            result = tool.get_pod_metrics("default")
            assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# ExecTool
# ─────────────────────────────────────────────────────────────────────────────

class TestExecTool:

    def test_exec_blocked_when_destructive_disabled(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"], destructive_actions_enabled=False)
        tool = ExecTool(client, security)

        with pytest.raises(PermissionError, match="not allowed"):
            tool.exec("default", "my-pod", ["ls"])

    def test_exec_string_command_raises_value_error(self):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"], destructive_actions_enabled=True)
        tool = ExecTool(client, security)

        with pytest.raises(ValueError, match="command must be a non-empty list"):
            tool.exec("default", "my-pod", "ls -la")

    @patch("k8s_mcp.tools.exec.stream")
    def test_exec_truncates_large_output(self, mock_stream):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"], destructive_actions_enabled=True)
        tool = ExecTool(client, security)

        large_output = "a" * (MAX_OUTPUT_BYTES + 10)
        mock_stream.return_value = large_output

        result = tool.exec("default", "my-pod", ["cat", "largefile"])
        assert result.truncated is True
        assert len(result.stdout) == MAX_OUTPUT_BYTES


# ─────────────────────────────────────────────────────────────────────────────
# SummaryTool
# ─────────────────────────────────────────────────────────────────────────────

class TestSummaryTool:

    @patch("k8s_mcp.tools.summary.PodsTool")
    @patch("k8s_mcp.tools.summary.LogsTool")
    @patch("k8s_mcp.tools.summary.EventsTool")
    @patch("k8s_mcp.tools.summary.MetricsTool")
    @patch("k8s_mcp.tools.summary.StorageTool")
    @patch("k8s_mcp.tools.summary.QuotaTool")
    @patch("k8s_mcp.tools.summary.NodesTool")
    @patch("k8s_mcp.tools.summary.WorkloadsTool")
    def test_summarize_pod_health_aggregates_properly(
        self, mock_workloads, mock_nodes, mock_quota, mock_storage,
        mock_metrics, mock_events, mock_logs, mock_pods
    ):
        client = MagicMock()
        security = SecurityContext(allowed_namespaces=["default"])
        tool = SummaryTool(client, security)

        # Mock PodsTool describe_pod output
        mock_pods.return_value.describe_pod.return_value = MagicMock(
            status="Running", restart_count=1, node="node-1", image=["nginx"]
        )

        # Mock K8s API read_namespaced_pod output
        raw_pod = MagicMock()
        cs = MagicMock()
        cs.name = "nginx"
        cs.state.running = MagicMock()
        cs.restart_count = 1
        cs.ready = True
        raw_pod.status.container_statuses = [cs]
        raw_pod.status.init_container_statuses = None
        raw_pod.metadata.owner_references = None
        client.core.read_namespaced_pod.return_value = raw_pod

        # Mock remaining tools
        mock_logs.return_value.get_all_container_logs.return_value = (["logline"], [])
        mock_events.return_value.get_events.return_value = []
        mock_nodes.return_value.describe_node.return_value = MagicMock(
            ready=True, pressures=[]
        )
        mock_storage.return_value.list_pvcs.return_value = []
        mock_quota.return_value.list_resource_quotas.return_value = []
        mock_metrics.return_value.get_pod_metrics.return_value = []

        result = tool.summarize_pod_health("default", "my-pod")
        assert isinstance(result, PodHealthReport)
        assert result.pod_name == "my-pod"
        assert result.status == "Running"
        assert result.node_ready is True
        assert result.workload_type == "standalone"
