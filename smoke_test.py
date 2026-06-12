"""
smoke_test.py — manual integration test against a live cluster.

Usage:
    python smoke_test.py --namespace db
    python smoke_test.py --namespace db --pod postgres-nodes-3
    python smoke_test.py --namespace db --pod postgres-nodes-3 --destructive
    python smoke_test.py --namespace db --deployment pgbouncer-primary --destructive
"""

import argparse
import os
from dataclasses import asdict
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / "config.env")

import k8s_mcp.client as _cm
_cm.K8sClient._instance = None

from k8s_mcp.logging_config import configure_logging
from k8s_mcp.client import K8sClient
from k8s_mcp.security import SecurityContext
from k8s_mcp.tools import (
    ActionsTool, ConfigTool, EventsTool, ExecTool, LogsTool,
    MetricsTool, NetworkTool, NodesTool, PodsTool, QuotaTool,
    StorageTool, SummaryTool, WorkloadsTool,
)

configure_logging()

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
SKIP = "\033[33m–\033[0m"


def check(label: str, fn):
    try:
        result = fn()
        print(f"  {PASS} {label}")
        return result
    except PermissionError as e:
        print(f"  {FAIL} {label}  →  PermissionError: {e}")
    except Exception as e:
        print(f"  {FAIL} {label}  →  {type(e).__name__}: {e}")
    return None


def section(title: str) -> None:
    print(f"\n[ {title} ]")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--pod", default=None)
    parser.add_argument("--deployment", default=None)
    parser.add_argument("--allowed", nargs="*", default=None)
    parser.add_argument("--destructive", action="store_true")
    args = parser.parse_args()

    ns = args.namespace
    allowed = args.allowed if args.allowed is not None else [ns]
    destructive = args.destructive or os.environ.get("DESTRUCTIVE_ACTIONS_ENABLED", "false").lower() == "true"

    print(f"\nKubeSherlock smoke test")
    print(f"  namespace  : {ns}")
    print(f"  allowed    : {allowed}")
    print(f"  destructive: {destructive}")

    client = K8sClient()
    sec = SecurityContext(allowed_namespaces=allowed, destructive_actions_enabled=destructive)
    pods_tool      = PodsTool(client, sec)
    logs_tool      = LogsTool(client, sec)
    events_tool    = EventsTool(client, sec)
    metrics_tool   = MetricsTool(client, sec)
    storage_tool   = StorageTool(client, sec)
    config_tool    = ConfigTool(client, sec)
    nodes_tool     = NodesTool(client, sec)
    workloads_tool = WorkloadsTool(client, sec)
    network_tool   = NetworkTool(client, sec)
    actions_tool   = ActionsTool(client, sec)
    exec_tool      = ExecTool(client, sec)
    quota_tool     = QuotaTool(client, sec)
    summary_tool   = SummaryTool(client, sec)

    # ── list_pods ─────────────────────────────────────────────────────────────
    section("list_pods")
    pods = check(f"list_pods(ns={ns!r})", lambda: pods_tool.list_pods(ns))
    if pods:
        for p in pods:
            flag = "  ⚠ high restarts" if p.restart_count >= 5 else ""
            print(f"      {p.name:<50} {p.status:<12} restarts={p.restart_count}{flag}")
    elif pods is not None:
        print("      (no pods)")

    # ── namespace ACL check ───────────────────────────────────────────────────
    section("security: namespace ACL")
    try:
        pods_tool.list_pods("__blocked__")
        print(f"  {FAIL} NOT blocked — unexpected")
    except PermissionError:
        print(f"  {PASS} correctly denied for '__blocked__'")

    # ── describe_pod ──────────────────────────────────────────────────────────
    pod_name = args.pod or (pods[0].name if pods else None)
    section("describe_pod")
    detail = None
    if pod_name:
        detail = check(f"describe_pod(ns={ns!r}, pod={pod_name!r})",
                       lambda: pods_tool.describe_pod(ns, pod_name))
        if detail:
            print(f"      node     : {detail.node}")
            print(f"      images   : {', '.join(detail.image)}")
            print(f"      status   : {detail.status}  restarts={detail.restart_count}")
            for c in detail.conditions:
                print(f"      cond  {c['type']:<24} {c['status']}  reason={c['reason']}")
    else:
        print(f"  {SKIP} no pods")

    # ── logs — all containers ─────────────────────────────────────────────────
    section("get_all_container_logs")
    if pod_name:
        all_logs = check(f"get_all_container_logs(pod={pod_name!r})",
                         lambda: logs_tool.get_all_container_logs(ns, pod_name, tail=20))
        if all_logs:
            for cl in all_logs:
                label = f"[init] " if cl.is_init else "       "
                prev  = " (previous)" if cl.previous else ""
                print(f"      {label}{cl.container}{prev}  —  {len(cl.lines)} line(s)")
                for line in cl.lines[:2]:
                    print(f"        │ {line[:120]}")
    else:
        print(f"  {SKIP} no pods")

    # ── events ────────────────────────────────────────────────────────────────
    section("get_events")
    events = check(f"get_events(ns={ns!r})", lambda: events_tool.get_events(ns))
    if events:
        for e in events:
            print(f"      {e.involved_object:<45} {e.reason:<20} count={e.count}")
    elif events is not None:
        print("      (no warning events)")

    # ── nodes ─────────────────────────────────────────────────────────────────
    section("list_nodes")
    nodes = check("list_nodes()", lambda: nodes_tool.list_nodes())
    if nodes:
        for n in nodes:
            pressures = f"  ⚠ {', '.join(n.pressures)}" if n.pressures else ""
            sched = "" if n.schedulable else "  ⚠ CORDONED"
            print(f"      {n.name:<35} ready={n.ready}{sched}{pressures}")
            print(f"        cpu={n.capacity.get('cpu')}  memory={n.capacity.get('memory')}  pods={n.capacity.get('pods')}")

    # ── statefulsets ──────────────────────────────────────────────────────────
    section("list_statefulsets")
    ssets = check(f"list_statefulsets(ns={ns!r})", lambda: workloads_tool.list_statefulsets(ns))
    if ssets:
        for s in ssets:
            ok = "✓" if s.ready == s.desired else "⚠"
            print(f"      {ok} {s.name:<40} desired={s.desired}  ready={s.ready}")
    elif ssets is not None:
        print("      (none)")

    # ── deployments ───────────────────────────────────────────────────────────
    section("list_deployments")
    deploys = check(f"list_deployments(ns={ns!r})", lambda: workloads_tool.list_deployments(ns))
    if deploys:
        for d in deploys:
            ok = "✓" if d.ready == d.desired else "⚠"
            print(f"      {ok} {d.name:<40} desired={d.desired}  ready={d.ready}  strategy={d.strategy}")
    elif deploys is not None:
        print("      (none)")

    # ── pvcs ─────────────────────────────────────────────────────────────────
    section("list_pvcs")
    pvcs = check(f"list_pvcs(ns={ns!r})", lambda: storage_tool.list_pvcs(ns))
    if pvcs:
        for p in pvcs:
            ok = "✓" if p.status == "Bound" else "⚠"
            print(f"      {ok} {p.name:<40} {p.status:<10} capacity={p.capacity}  volume={p.volume_name}")
    elif pvcs is not None:
        print("      (none)")

    # ── services + endpoints ──────────────────────────────────────────────────
    section("list_services")
    svcs = check(f"list_services(ns={ns!r})", lambda: network_tool.list_services(ns))
    if svcs:
        for s in svcs:
            ok = "✓" if s.endpoint_count > 0 or not s.selector else "⚠"
            print(f"      {ok} {s.name:<40} {s.type:<14} endpoints={s.endpoint_count}")
    elif svcs is not None:
        print("      (none)")

    # ── configmaps ────────────────────────────────────────────────────────────
    section("list_configmaps")
    cms = check(f"list_configmaps(ns={ns!r})", lambda: config_tool.list_configmaps(ns))
    if cms:
        for cm in cms:
            print(f"      {cm.name:<40} keys={list(cm.data.keys())}")
    elif cms is not None:
        print("      (none)")

    # ── metrics ───────────────────────────────────────────────────────────────
    section("get_pod_metrics (requires metrics-server)")
    pod_metrics = check(f"get_pod_metrics(ns={ns!r})", lambda: metrics_tool.get_pod_metrics(ns))
    if pod_metrics:
        for m in pod_metrics:
            for c in m.containers:
                print(f"      {m.name:<45} {c['name']:<20} cpu={c['cpu']}  mem={c['memory']}")
    elif pod_metrics is not None:
        print("      (metrics-server not available or no data)")

    # ── resource quotas ───────────────────────────────────────────────────────
    section("list_resource_quotas + list_limit_ranges")
    quotas = check(f"list_resource_quotas(ns={ns!r})", lambda: quota_tool.list_resource_quotas(ns))
    if quotas:
        for q in quotas:
            print(f"      {q.name}")
            for resource, hard in q.hard.items():
                used = q.used.get(resource, "0")
                flag = "  ⚠ near limit" if resource in " ".join(q.near_limit) else ""
                print(f"        {resource:<35} {used} / {hard}{flag}")
        if any(q.near_limit for q in quotas):
            print(f"      ⚠ near-limit resources: {[r for q in quotas for r in q.near_limit]}")
    elif quotas is not None:
        print("      (no resource quotas)")

    lrs = check(f"list_limit_ranges(ns={ns!r})", lambda: quota_tool.list_limit_ranges(ns))
    if lrs:
        for lr in lrs:
            for limit in lr.limits:
                print(f"      {lr.name}  type={limit['type']}  default={limit['default']}  max={limit['max']}")
    elif lrs is not None:
        print("      (no limit ranges)")

    # ── summarize_pod_health ──────────────────────────────────────────────────
    section("summarize_pod_health")
    if pod_name:
        report = check(f"summarize_pod_health(ns={ns!r}, pod={pod_name!r})",
                       lambda: summary_tool.summarize_pod_health(ns, pod_name))
        if report:
            print(f"      status         : {report.status}  restarts={report.restart_count}")
            print(f"      workload       : {report.workload_type}  ready={report.workload_ready}")
            print(f"      crashing_ctr   : {report.crashing_container or 'none'}")
            print(f"      node_ready     : {report.node_ready}  pressures={report.node_pressures}")
            print(f"      pvc_issues     : {len(report.pvc_issues)}")
            print(f"      quota_near_lim : {report.quota_near_limit or 'none'}")
            print(f"      warning_events : {len(report.warning_events)}")
            print(f"      recent_logs    : {len(report.recent_logs)} lines")
            print(f"      previous_logs  : {len(report.previous_logs)} lines")
            print(f"\n      ── probable causes ──")
            for cause in report.probable_causes:
                print(f"      • {cause}")
    else:
        print(f"  {SKIP} no pod to summarize")

    # ── destructive guard ─────────────────────────────────────────────────────
    section("destructive guard (always runs)")
    blocked_sec = SecurityContext(allowed_namespaces=allowed, destructive_actions_enabled=False)
    blocked_actions = ActionsTool(client, blocked_sec)
    try:
        blocked_actions.restart_pod(ns, "__fake__")
        print(f"  {FAIL} guard NOT enforced — unexpected")
    except PermissionError:
        print(f"  {PASS} correctly blocked when DESTRUCTIVE_ACTIONS_ENABLED=false")

    if not destructive:
        print(f"\n  {SKIP} skipping live action tests (pass --destructive to enable)")
        print()
        return

    # ── destructive: pod actions ──────────────────────────────────────────────
    section("destructive actions")
    print("  ⚠  These tests mutate the cluster.\n")

    if pod_name:
        r = check(f"restart_pod(pod={pod_name!r})",
                  lambda: actions_tool.restart_pod(ns, pod_name))
        if r:
            print(f"      {r.message}")

    # exec: run a safe read-only command
    if pod_name and detail:
        # Pick a running pod for exec — not the one we just deleted/restarted
        exec_pod = next(
            (p.name for p in (pods or []) if p.name != pod_name and p.status == "Running"),
            None,
        )
        if exec_pod is None:
            print(f"  {SKIP} exec — no other running pod available")
        else:
            raw_pod = client.core.read_namespaced_pod(exec_pod, ns)
            first_container = (
                raw_pod.spec.init_containers[0].name
                if raw_pod.spec.init_containers
                else raw_pod.spec.containers[0].name
            )
            r = check(f"exec_in_pod(pod={exec_pod!r}, container={first_container!r}, cmd=['ls','/'])",
                      lambda: exec_tool.exec(ns, exec_pod, ["ls", "/"], container=first_container))
            if r:
                print(f"      stdout: {r.stdout[:200]}")
                if r.stderr:
                    print(f"      stderr: {r.stderr[:100]}")

    # deployment actions
    deploy_name = args.deployment
    if deploy_name:
        for label, fn in [
            (f"restart_deployment({deploy_name!r})",
             lambda: actions_tool.restart_deployment(ns, deploy_name)),
            (f"scale_deployment({deploy_name!r}, 0)",
             lambda: actions_tool.scale_deployment(ns, deploy_name, 0)),
            (f"scale_deployment({deploy_name!r}, 1)",
             lambda: actions_tool.scale_deployment(ns, deploy_name, 1)),
            (f"rollback_deployment({deploy_name!r})",
             lambda: actions_tool.rollback_deployment(ns, deploy_name)),
        ]:
            r = check(label, fn)
            if r:
                print(f"      {r.message}")
    else:
        print(f"  {SKIP} deployment actions — pass --deployment <name> to test")

    print()


if __name__ == "__main__":
    main()
