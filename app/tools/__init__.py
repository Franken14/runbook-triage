from .base import ToolType, RiskLevel, ToolDefinition
from .diagnostics import (
    DIAGNOSTIC_TOOLS,
    fetch_service_logs,
    check_k8s_pod_status,
    query_prometheus_metrics,
    check_db_connection_pool
)
from .remediation import (
    REMEDIATION_TOOLS,
    restart_pod_deployment,
    scale_service_replicas,
    flush_redis_cache_key,
    rollback_canary_deployment
)

ALL_TOOLS = {**DIAGNOSTIC_TOOLS, **REMEDIATION_TOOLS}

TOOL_HANDLERS = {
    "fetch_service_logs": fetch_service_logs,
    "check_k8s_pod_status": check_k8s_pod_status,
    "query_prometheus_metrics": query_prometheus_metrics,
    "check_db_connection_pool": check_db_connection_pool,
    "restart_pod_deployment": restart_pod_deployment,
    "scale_service_replicas": scale_service_replicas,
    "flush_redis_cache_key": flush_redis_cache_key,
    "rollback_canary_deployment": rollback_canary_deployment,
}

__all__ = [
    "ToolType",
    "RiskLevel",
    "ToolDefinition",
    "DIAGNOSTIC_TOOLS",
    "REMEDIATION_TOOLS",
    "ALL_TOOLS",
    "TOOL_HANDLERS"
]
