"""
agent.watcher
~~~~~~~~~~~~~

Continuous cluster watcher.

Polls configured namespaces on a fixed interval, detects pod failures,
and automatically triggers an AI investigation for each new failure.

Detects:
- CrashLoopBackOff / OOMKilled / Error (waiting state)
- Pods in Failed phase
- Pods exceeding restart threshold

Config (all via environment / config.env):
    WATCHER_ENABLED           true/false (default: true)
    WATCHER_POLL_INTERVAL     seconds between polls (default: 30)
    WATCHER_NAMESPACES        comma-separated, falls back to ALLOWED_NAMESPACES
    WATCHER_LLM_PROVIDER      anthropic or openai (default: anthropic)
    WATCHER_RESTART_THRESHOLD restart count to trigger investigation (default: 3)
    WATCHER_COOLDOWN          seconds before re-investigating same pod (default: 300)

Usage:
    python -m agent.watcher
"""

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import anyio
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / "config.env")

from .investigator import Investigator
from .mcp_client import run_with_mcp

log = logging.getLogger(__name__)

# ── failure states that trigger investigation ──────────────────────────────
FAILURE_REASONS = {"CrashLoopBackOff", "OOMKilled", "Error", "CreateContainerError",
                   "ImagePullBackOff", "ErrImagePull"}


@dataclass
class PodFailure:
    """A detected pod failure event."""
    namespace: str
    pod_name: str
    reason: str
    restart_count: int
    detected_at: datetime = field(default_factory=datetime.now)

    def __str__(self) -> str:
        return (f"{self.namespace}/{self.pod_name} "
                f"reason={self.reason} restarts={self.restart_count}")


class WatcherConfig:
    """Loads watcher configuration from environment variables."""

    def __init__(self) -> None:
        self.enabled = os.environ.get("WATCHER_ENABLED", "true").lower() == "true"
        self.poll_interval = int(os.environ.get("WATCHER_POLL_INTERVAL", "30"))
        self.provider = os.environ.get("WATCHER_LLM_PROVIDER", "anthropic")
        self.restart_threshold = int(os.environ.get("WATCHER_RESTART_THRESHOLD", "3"))
        self.cooldown = int(os.environ.get("WATCHER_COOLDOWN", "300"))
        self.email_enabled = os.environ.get("WATCHER_EMAIL_ENABLED", "false").lower() == "true"

        raw_ns = (
            os.environ.get("WATCHER_NAMESPACES")
            or os.environ.get("ALLOWED_NAMESPACES", "")
        )
        self.namespaces = [n.strip() for n in raw_ns.split(",") if n.strip()]


class Watcher:
    """Continuously polls Kubernetes namespaces and triggers investigations on failures.

    Args:
        config: :class:`WatcherConfig` instance.
    """

    def __init__(self, config: WatcherConfig) -> None:
        self._config = config
        # pod_key → timestamp of last investigation
        self._last_investigated: dict[str, float] = {}
        
        log.info("🚀 Initializing KubeSherlock Watcher")
        log.info(f"   Provider: {config.provider}")
        log.info(f"   Namespaces: {config.namespaces or 'ALL'}")
        log.info(f"   Poll interval: {config.poll_interval}s")
        log.info(f"   Restart threshold: {config.restart_threshold}")
        log.info(f"   Cooldown: {config.cooldown}s")
        
        # Email notification setup
        self._notifier = None
        if config.email_enabled:
            log.info("📧 Email notifications ENABLED - setting up...")
            from .notifier import EmailConfig, EmailNotifier
            try:
                email_config = EmailConfig.from_env()
                
                if not email_config.smtp_user or not email_config.smtp_password:
                    log.error("❌ Email enabled but SMTP credentials missing in config.env")
                    log.error("   Set SMTP_USER and SMTP_PASSWORD to enable email alerts")
                elif not email_config.alert_email_to:
                    log.warning("⚠️  Email enabled but no recipients configured (ALERT_EMAIL_TO is empty)")
                else:
                    self._notifier = EmailNotifier(email_config)
                    log.info(f"✅ Email notifications configured successfully")
                    log.info(f"   Recipients: {', '.join(email_config.alert_email_to)}")
                    log.info(f"   SMTP: {email_config.smtp_host}:{email_config.smtp_port}")
            except Exception as e:
                log.error(f"❌ Failed to initialize email notifier: {e}")
        else:
            log.info("📧 Email notifications DISABLED (WATCHER_EMAIL_ENABLED=false)")

    async def run(self) -> None:
        """Start the watch loop. Runs forever until interrupted."""
        cfg = self._config
        log.info(
            "Watcher started  namespaces=%s  interval=%ds  provider=%s  "
            "restart_threshold=%d  cooldown=%ds",
            cfg.namespaces or "ALL", cfg.poll_interval, cfg.provider,
            cfg.restart_threshold, cfg.cooldown,
        )
        print(f"\n👁  KubeSherlock Watcher running")
        print(f"   Namespaces   : {cfg.namespaces or 'ALL'}")
        print(f"   Poll interval: {cfg.poll_interval}s")
        print(f"   Provider     : {cfg.provider}")
        print(f"   Cooldown     : {cfg.cooldown}s")
        print(f"   Press Ctrl+C to stop\n")

        server_cmd = self._build_server_cmd()

        async def watch_loop(client):
            from k8s_mcp.tools import PodsTool
            from k8s_mcp.security import SecurityContext
            from k8s_mcp.client import K8sClient

            k8s = K8sClient()
            security = SecurityContext(
                allowed_namespaces=self._config.namespaces,
                destructive_actions_enabled=False,
            )
            pods_tool = PodsTool(k8s, security)

            while True:
                await self._poll(pods_tool, client)
                await anyio.sleep(self._config.poll_interval)

        await run_with_mcp(server_cmd, watch_loop)

    async def _poll(self, pods_tool, mcp_client) -> None:
        """One poll cycle — check all namespaces for failures."""
        namespaces = self._config.namespaces or self._get_all_namespaces()
        failures: list[PodFailure] = []

        log.debug(f"🔄 Starting poll cycle - checking {len(namespaces)} namespace(s)")
        
        for ns in namespaces:
            try:
                log.debug(f"   Checking namespace: {ns}")
                pods = pods_tool.list_pods(ns)
                log.debug(f"   Found {len(pods)} pods in {ns}")
                for pod in pods:
                    failure = self._detect_failure(ns, pod)
                    if failure:
                        failures.append(failure)
                        log.debug(f"   ⚠️  Failure detected: {failure}")
            except Exception as e:
                log.warning(f"❌ Poll failed for namespace {ns}: {e}")

        if not failures:
            log.debug("✅ Poll complete — no failures detected")
            return

        log.info(f"⚠️  Poll complete — {len(failures)} failure(s) detected")
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ⚠️  {len(failures)} failure(s) detected:")
        for f in failures:
            print(f"  • {f}")

        for failure in failures:
            await self._maybe_investigate(failure, mcp_client)

    def _detect_failure(self, namespace: str, pod) -> PodFailure | None:
        """Return a PodFailure if the pod is in a failed state, else None."""
        # Failed phase
        if pod.status == "Failed":
            return PodFailure(namespace, pod.name, "PodFailed", pod.restart_count)

        # High restart count
        if pod.restart_count >= self._config.restart_threshold:
            return PodFailure(namespace, pod.name, f"HighRestarts({pod.restart_count})",
                              pod.restart_count)

        # Check container waiting states (ImagePullBackOff, CrashLoopBackOff, etc.)
        # Need to fetch full pod details to check container states
        try:
            from k8s_mcp.tools import PodsTool
            from k8s_mcp.client import K8sClient
            from k8s_mcp.security import SecurityContext
            
            k8s = K8sClient()
            security = SecurityContext(allowed_namespaces=[namespace])
            pods_tool = PodsTool(k8s, security)
            
            # Get full pod to check container states
            full_pod = k8s.core.read_namespaced_pod(pod.name, namespace)
            
            # Check container statuses for waiting states
            if full_pod.status.container_statuses:
                for cs in full_pod.status.container_statuses:
                    if cs.state and cs.state.waiting:
                        reason = cs.state.waiting.reason
                        if reason in FAILURE_REASONS:
                            return PodFailure(namespace, pod.name, reason, pod.restart_count)
        except Exception as e:
            log.debug("Could not check container states for %s: %s", pod.name, e)

        return None

    async def _maybe_investigate(self, failure: PodFailure, mcp_client) -> None:
        """Trigger an investigation unless the pod is still in cooldown."""
        key = f"{failure.namespace}/{failure.pod_name}"
        now = time.monotonic()
        last = self._last_investigated.get(key, 0)

        if now - last < self._config.cooldown:
            remaining = int(self._config.cooldown - (now - last))
            log.debug(f"⏳ Skipping {key} — cooldown ({remaining}s remaining)")
            print(f"    ⏳ {key} — cooldown ({remaining}s remaining)")
            return

        self._last_investigated[key] = now
        question = (
            f"Why is pod {failure.pod_name} failing in namespace {failure.namespace}? "
            f"Detected: {failure.reason}. Restart count: {failure.restart_count}. "
            f"Investigate and provide root cause and recommendations."
        )

        print(f"\n  🔍 Investigating {key} ({failure.reason})...")
        log.info(f"🔍 Auto-investigation triggered for {key} (reason: {failure.reason})")

        try:
            investigator = Investigator(
                mcp_client=mcp_client,
                provider=self._config.provider,
            )
            log.debug(f"   Running investigation with {self._config.provider}...")
            result = await investigator.investigate(question)
            log.info(f"✅ Investigation completed - {result.iterations} iterations, {len(result.tool_calls)} tool calls")
            
            # Detect severity
            from .severity import detect_severity
            severity = detect_severity(result, failure)
            log.info(f"📊 Severity assessed: {severity}")
            
            # Send email alert if enabled and severity is HIGH or CRITICAL
            if self._notifier and severity in ["HIGH", "CRITICAL"]:
                log.info(f"📧 Triggering email alert (severity: {severity})...")
                try:
                    self._notifier.send_alert(failure, result, severity)
                except Exception as email_err:
                    log.error(f"❌ Email alert failed: {email_err}")
            elif severity in ["HIGH", "CRITICAL"] and not self._notifier:
                log.warning(f"⚠️  {severity} severity detected but email notifications are disabled")
            else:
                log.debug(f"ℹ️  Severity {severity} - no email alert needed")
            
            self._print_report(failure, result, severity)
        except Exception as e:
            log.error(f"❌ Investigation failed for {key}: {type(e).__name__}: {e}")
            print(f"  ❌ Investigation failed: {e}")

    def _build_server_cmd(self) -> list[str]:
        cmd = [sys.executable, "-m", "k8s_mcp.server"]
        if self._config.namespaces:
            cmd += ["--namespaces"] + self._config.namespaces
        return cmd

    def _get_all_namespaces(self) -> list[str]:
        """Fallback: get all namespaces from the cluster."""
        try:
            from k8s_mcp.client import K8sClient
            ns_list = K8sClient().core.list_namespace()
            return [ns.metadata.name for ns in ns_list.items]
        except Exception:
            return ["default"]

    @staticmethod
    def _print_report(failure: PodFailure, result, severity: str) -> None:
        print(f"\n  {'─' * 56}")
        print(f"  📋 Investigation report: {failure.namespace}/{failure.pod_name}")
        print(f"  Severity: {severity}  |  Iterations: {result.iterations}  |  Tools used: {len(result.tool_calls)}")
        for tc in result.tool_calls:
            print(f"    → {tc['tool']}")
        print(f"\n{result.answer}\n")
        print(f"  {'─' * 56}\n")


async def _main() -> None:
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)-5s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    log.info(f"🔧 Log level: {log_level}")
    
    cfg = WatcherConfig()
    if not cfg.enabled:
        log.warning("⚠️  Watcher is disabled (WATCHER_ENABLED=false)")
        print("Watcher is disabled (WATCHER_ENABLED=false)")
        return
    await Watcher(cfg).run()


if __name__ == "__main__":
    anyio.run(_main)
