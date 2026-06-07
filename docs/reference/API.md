# MCP Tools API Reference

All 26 tools available via the MCP server.

---

## Pod Diagnostics

### list_pods
Lists all pods in a namespace.
```
Input:  namespace: str
Output: [{name, namespace, status, restart_count}, ...]
```

### describe_pod
Full diagnostic snapshot of a single pod.
```
Input:  namespace: str, pod_name: str
Output: {name, namespace, node, images, status, restart_count, conditions}
```

### get_pod_logs
Fetch pod logs (capped at 500 lines).
```
Input:  namespace: str, pod_name: str, tail: int (default 100), container: str | null
Output: str (raw log text)
```

### get_all_container_logs
Fetch logs from all containers (including init containers + previous crashed instances).
```
Input:  namespace: str, pod_name: str, tail: int (default 50)
Output: [{pod_name, container, is_init, previous, lines}, ...]
```

---

## Events

### get_events
Return Kubernetes warning events for a namespace.
```
Input:  namespace: str, warnings_only: bool (default true)
Output: [{name, reason, message, type, involved_object, count}, ...]
```

---

## Nodes

### list_nodes
Node health: ready status, pressures, capacity.
```
Input:  (none)
Output: [{name, ready, schedulable, conditions, capacity, pressures}, ...]
```

### describe_node
Full health snapshot of a single node.
```
Input:  node_name: str
Output: {name, ready, schedulable, conditions, capacity, pressures}
```

---

## Workloads

### list_deployments
Deployment rollout status (desired/ready/available replicas).
```
Input:  namespace: str
Output: [{name, namespace, desired, ready, available, updated, strategy, conditions}, ...]
```

### list_statefulsets
StatefulSet rollout status.
```
Input:  namespace: str
Output: [{name, namespace, desired, ready, current, update_revision, current_revision, ordered}, ...]
```

---

## Metrics

### get_pod_metrics
Live CPU/memory usage for all pods in a namespace.
```
Input:  namespace: str
Output: [{name, namespace, containers: [{name, cpu, memory}, ...]}, ...]
Note:   Requires metrics-server installed
```

### get_node_metrics
Live CPU/memory usage for all nodes.
```
Input:  (none)
Output: [{name, cpu, memory}, ...]
Note:   Requires metrics-server installed
```

---

## Storage

### list_pvcs
PersistentVolumeClaims with binding status.
```
Input:  namespace: str
Output: [{name, namespace, status, storage_class, capacity, access_modes, volume_name}, ...]
```

### describe_pvc
Single PVC details.
```
Input:  namespace: str, pvc_name: str
Output: {name, namespace, status, storage_class, capacity, access_modes, volume_name}
```

---

## Config & Network

### list_configmaps
ConfigMaps in a namespace (with secret redaction).
```
Input:  namespace: str
Output: [{name, namespace, data: {key: value, ...}}, ...]
```

### get_configmap
Single ConfigMap details.
```
Input:  namespace: str, name: str
Output: {name, namespace, data: {key: value, ...}}
```

### list_services
Services with endpoint counts.
```
Input:  namespace: str
Output: [{name, namespace, type, cluster_ip, ports, selector, endpoint_count}, ...]
```

### describe_service
Single service with endpoint details.
```
Input:  namespace: str, service_name: str
Output: {name, namespace, type, cluster_ip, ports, selector, endpoint_count}
```

---

## Quotas & Limits

### list_resource_quotas
ResourceQuota usage vs hard limits. Flags near-limit resources (≥80%).
```
Input:  namespace: str
Output: [{name, namespace, hard, used, near_limit}, ...]
```

### list_limit_ranges
LimitRange defaults and min/max constraints.
```
Input:  namespace: str
Output: [{name, namespace, limits: [{type, default, defaultRequest, min, max}, ...]}, ...]
```

---

## Composite (Recommended First Tool)

### summarize_pod_health
**Call this first.** Full diagnostic report combining all signals.
```
Input:  namespace: str, pod_name: str
Output: {
  pod_name, namespace, status, restart_count, node, images,
  crashing_container, container_states,
  recent_logs, previous_logs,
  warning_events,
  node_ready, node_pressures,
  pvc_issues, quota_near_limit,
  workload_type, workload_ready,
  pod_metrics,
  probable_causes: [str, ...]
}
```

---

## Destructive Actions (DESTRUCTIVE_ACTIONS_ENABLED=true)

### restart_pod
Delete pod so its controller recreates it.
```
Input:  namespace: str, pod_name: str
Output: {action, namespace, resource, success, message}
```

### delete_pod
Permanent delete with grace period.
```
Input:  namespace: str, pod_name: str, grace_period: int (default 30)
Output: {action, namespace, resource, success, message}
```

### restart_deployment
Rolling restart of all pods in a deployment.
```
Input:  namespace: str, deployment_name: str
Output: {action, namespace, resource, success, message}
```

### scale_deployment
Set replica count (0 = stop workload).
```
Input:  namespace: str, deployment_name: str, replicas: int
Output: {action, namespace, resource, success, message}
```

### rollback_deployment
Roll back to previous revision.
```
Input:  namespace: str, deployment_name: str
Output: {action, namespace, resource, success, message}
```

### exec_in_pod
Run command inside container.
```
Input:  namespace: str, pod_name: str, command: [str], container: str | null
Output: {pod_name, container, command, stdout, stderr, truncated}
```
