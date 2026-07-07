"""
tests.test_watcher_unit
~~~~~~~~~~~~~~~~~~~~~~~

Unit tests for agent/watcher.py — the continuous incident watcher.

All Kubernetes API calls, Investigator calls, and email notifications are mocked.
"""

import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from agent.watcher import Watcher, WatcherConfig, PodFailure, FAILURE_REASONS
from agent.investigator import InvestigationResult


# ─────────────────────────────────────────────────────────────────────────────
# WatcherConfig tests
# ─────────────────────────────────────────────────────────────────────────────

class TestWatcherConfig:

    def test_default_values(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = WatcherConfig()
            assert cfg.enabled is True
            assert cfg.poll_interval == 30
            assert cfg.provider == "anthropic"
            assert cfg.restart_threshold == 3
            assert cfg.cooldown == 300
            assert cfg.email_enabled is False
            assert cfg.namespaces == []

    def test_custom_values_from_env(self):
        env = {
            "WATCHER_ENABLED": "false",
            "WATCHER_POLL_INTERVAL": "60",
            "WATCHER_LLM_PROVIDER": "openai",
            "WATCHER_RESTART_THRESHOLD": "5",
            "WATCHER_COOLDOWN": "120",
            "WATCHER_EMAIL_ENABLED": "true",
            "WATCHER_NAMESPACES": "kube-system, monitoring",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = WatcherConfig()
            assert cfg.enabled is False
            assert cfg.poll_interval == 60
            assert cfg.provider == "openai"
            assert cfg.restart_threshold == 5
            assert cfg.cooldown == 120
            assert cfg.email_enabled is True
            assert cfg.namespaces == ["kube-system", "monitoring"]

    def test_fallback_namespaces_to_allowed_namespaces(self):
        env = {
            "ALLOWED_NAMESPACES": "default,prod",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = WatcherConfig()
            assert cfg.namespaces == ["default", "prod"]


# ─────────────────────────────────────────────────────────────────────────────
# Watcher._detect_failure() tests
# ─────────────────────────────────────────────────────────────────────────────

class TestWatcherDetectFailure:

    def _make_mock_pod(self, name="my-pod", status="Running", restart_count=0):
        pod = MagicMock()
        pod.name = name
        pod.status = status
        pod.restart_count = restart_count
        return pod

    @patch("agent.watcher.log")
    def test_detect_failure_healthy_pod(self, mock_log):
        cfg = WatcherConfig()
        watcher = Watcher(cfg)
        pod = self._make_mock_pod(status="Running", restart_count=1)

        # Mock check container states logic inside try block to return None
        with patch("k8s_mcp.client.K8sClient") as mock_client:
            mock_core = mock_client.return_value.core
            mock_core.read_namespaced_pod.return_value.status.container_statuses = None
            
            result = watcher._detect_failure("default", pod)
            assert result is None

    def test_detect_failure_pod_failed_phase(self):
        cfg = WatcherConfig()
        watcher = Watcher(cfg)
        pod = self._make_mock_pod(status="Failed", restart_count=0)

        result = watcher._detect_failure("default", pod)
        assert isinstance(result, PodFailure)
        assert result.reason == "PodFailed"
        assert result.restart_count == 0

    def test_detect_failure_high_restart_count(self):
        cfg = WatcherConfig()
        cfg.restart_threshold = 3
        watcher = Watcher(cfg)
        pod = self._make_mock_pod(status="Running", restart_count=3)

        result = watcher._detect_failure("default", pod)
        assert isinstance(result, PodFailure)
        assert result.reason == "HighRestarts(3)"
        assert result.restart_count == 3

    def test_detect_failure_container_waiting_state(self):
        cfg = WatcherConfig()
        watcher = Watcher(cfg)
        pod = self._make_mock_pod(status="Running", restart_count=0)

        # Mock full pod retrieval returning a container in CrashLoopBackOff
        with patch("k8s_mcp.client.K8sClient") as mock_client:
            mock_core = mock_client.return_value.core
            
            cs = MagicMock()
            cs.state.waiting.reason = "CrashLoopBackOff"
            cs.state.running = None
            cs.state.terminated = None
            
            full_pod = MagicMock()
            full_pod.status.container_statuses = [cs]
            mock_core.read_namespaced_pod.return_value = full_pod

            result = watcher._detect_failure("default", pod)
            assert isinstance(result, PodFailure)
            assert result.reason == "CrashLoopBackOff"
            assert result.restart_count == 0

    def test_detect_failure_graceful_on_exception(self):
        cfg = WatcherConfig()
        watcher = Watcher(cfg)
        pod = self._make_mock_pod(status="Running", restart_count=0)

        with patch("k8s_mcp.client.K8sClient") as mock_client:
            mock_client.side_effect = Exception("Kubernetes API error")
            # Should not raise, just return None
            result = watcher._detect_failure("default", pod)
            assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Watcher._maybe_investigate() & Cooldown tests
# ─────────────────────────────────────────────────────────────────────────────

class TestWatcherMaybeInvestigate:

    @pytest.mark.asyncio
    @patch("agent.watcher.Investigator")
    @patch("agent.severity.detect_severity")
    async def test_maybe_investigate_cooldown_skips(self, mock_detect_severity, mock_investigator):
        cfg = WatcherConfig()
        cfg.cooldown = 100
        watcher = Watcher(cfg)
        
        failure = PodFailure("default", "web", "CrashLoopBackOff", 2)
        watcher._last_investigated["default/web"] = time.monotonic() - 50 # 50s ago < 100s cooldown

        await watcher._maybe_investigate(failure, MagicMock())
        mock_investigator.assert_not_called()

    @pytest.mark.asyncio
    @patch("agent.watcher.Investigator")
    @patch("agent.severity.detect_severity")
    async def test_maybe_investigate_triggers_after_cooldown(self, mock_detect, mock_investigator):
        cfg = WatcherConfig()
        cfg.cooldown = 100
        watcher = Watcher(cfg)
        
        failure = PodFailure("default", "web", "CrashLoopBackOff", 2)
        watcher._last_investigated["default/web"] = time.monotonic() - 150 # 150s ago > 100s cooldown

        # Mock investigator run
        mock_inv_instance = mock_investigator.return_value
        mock_inv_instance.investigate = AsyncMock(return_value=InvestigationResult("q", "a", [], 1, "openai"))
        mock_detect.return_value = "MEDIUM"

        await watcher._maybe_investigate(failure, MagicMock())
        mock_inv_instance.investigate.assert_called_once()
        assert watcher._last_investigated["default/web"] == pytest.approx(time.monotonic(), abs=1.0)

    @pytest.mark.asyncio
    @patch("agent.watcher.Investigator")
    @patch("agent.severity.detect_severity")
    async def test_maybe_investigate_sends_alert_only_on_high_critical(self, mock_detect, mock_investigator):
        cfg = WatcherConfig()
        watcher = Watcher(cfg)
        watcher._notifier = MagicMock()

        # Mock investigator
        mock_inv_instance = mock_investigator.return_value
        mock_inv_instance.investigate = AsyncMock(return_value=InvestigationResult("q", "a", [], 1, "openai"))
        
        failure = PodFailure("default", "web", "CrashLoopBackOff", 2)

        # 1. Medium severity should NOT trigger alert
        mock_detect.return_value = "MEDIUM"
        await watcher._maybe_investigate(failure, MagicMock())
        watcher._notifier.send_alert.assert_not_called()

        # Reset cooldown to run again
        watcher._last_investigated.clear()

        # 2. Critical severity SHOULD trigger alert
        mock_detect.return_value = "CRITICAL"
        await watcher._maybe_investigate(failure, MagicMock())
        watcher._notifier.send_alert.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions tests
# ─────────────────────────────────────────────────────────────────────────────

class TestWatcherHelpers:

    def test_build_server_cmd_no_namespaces(self):
        cfg = WatcherConfig()
        cfg.namespaces = []
        watcher = Watcher(cfg)
        cmd = watcher._build_server_cmd()
        assert cmd == [sys.executable, "-m", "k8s_mcp.server"]

    def test_build_server_cmd_with_namespaces(self):
        cfg = WatcherConfig()
        cfg.namespaces = ["default", "kube-system"]
        watcher = Watcher(cfg)
        cmd = watcher._build_server_cmd()
        assert cmd == [sys.executable, "-m", "k8s_mcp.server", "--namespaces", "default", "kube-system"]

    def test_get_all_namespaces_success(self):
        cfg = WatcherConfig()
        watcher = Watcher(cfg)

        with patch("k8s_mcp.client.K8sClient") as mock_client:
            ns1 = MagicMock()
            ns1.metadata.name = "default"
            ns2 = MagicMock()
            ns2.metadata.name = "kube-public"
            
            mock_client.return_value.core.list_namespace.return_value.items = [ns1, ns2]
            
            namespaces = watcher._get_all_namespaces()
            assert namespaces == ["default", "kube-public"]

    def test_get_all_namespaces_failure_fallback(self):
        cfg = WatcherConfig()
        watcher = Watcher(cfg)

        with patch("k8s_mcp.client.K8sClient") as mock_client:
            mock_client.return_value.core.list_namespace.side_effect = Exception("Unauthorized")
            namespaces = watcher._get_all_namespaces()
            # Falls back to default
            assert namespaces == ["default"]
