import logging
from typing import Dict, Any, List
from .base import ToolDefinition, ToolType, RiskLevel

logger = logging.getLogger(__name__)


async def fetch_service_logs(service: str, lines: int = 50, filter_term: str = "") -> Dict[str, Any]:
    """
    Sandboxed diagnostic tool to query structured application logs.
    Read-only, completely non-mutating.
    """
    logger.info(f"[Diagnostic] Querying logs for service '{service}' (lines={lines}, filter='{filter_term}')")
    
    # Realistic simulated diagnostic responses
    if "payment" in service.lower():
        simulated_logs = [
            f"[ERROR] [payment-svc] Failed to connect to postgres: connection pool exhausted (active=50, idle=0)",
            f"[WARN] [payment-svc] Latency threshold breached: P99 > 3200ms",
            f"[ERROR] [payment-svc] DB transaction timed out after 5000ms"
        ]
    elif "order" in service.lower() or "worker" in service.lower():
        simulated_logs = [
            f"[ERROR] [order-worker] Out of Memory (OOMKilled): Container memory limit 512Mi breached (current=518Mi)",
            f"[WARN] [order-worker] Kafka consumer lag growing: topic=orders partition=2 lag=14205"
        ]
    else:
        simulated_logs = [
            f"[INFO] [{service}] Healthcheck probe /health responded 200 OK",
            f"[WARN] [{service}] High CPU usage reported: 88.5% over 5m window",
            f"[DEBUG] [{service}] Cache miss rate: 42%"
        ]

    return {
        "service": service,
        "lines_returned": len(simulated_logs),
        "logs": simulated_logs,
        "diagnostic_status": "COMPLETED"
    }


async def check_k8s_pod_status(namespace: str, selector: str = "app") -> Dict[str, Any]:
    """
    Read-only inspection of Kubernetes pods in the given namespace.
    """
    logger.info(f"[Diagnostic] Inspecting K8s Pods in namespace='{namespace}', selector='{selector}'")
    return {
        "namespace": namespace,
        "pods": [
            {
                "pod_name": f"{selector}-pod-7df4f-8x12k",
                "status": "CrashLoopBackOff",
                "restart_count": 6,
                "last_termination_reason": "OOMKilled",
                "exit_code": 137,
                "cpu_request": "250m",
                "memory_limit": "512Mi"
            },
            {
                "pod_name": f"{selector}-pod-7df4f-9m54l",
                "status": "Running",
                "restart_count": 0,
                "last_termination_reason": None,
                "exit_code": 0,
                "cpu_request": "250m",
                "memory_limit": "512Mi"
            }
        ]
    }


async def query_prometheus_metrics(promql_query: str, step_seconds: int = 15) -> Dict[str, Any]:
    """
    Read-only Prometheus metric query evaluator.
    """
    logger.info(f"[Diagnostic] Querying Prometheus PromQL: {promql_query}")
    return {
        "query": promql_query,
        "step": f"{step_seconds}s",
        "result_type": "vector",
        "metrics": [
            {
                "metric": {"job": "api-gateway", "instance": "10.0.1.20:9090"},
                "value": [1714002000, "0.942"]  # 94.2% error rate or saturation
            }
        ]
    }


async def check_db_connection_pool(database_name: str) -> Dict[str, Any]:
    """
    Read-only diagnostic inspection of active PostgreSQL connection pools.
    """
    logger.info(f"[Diagnostic] Inspecting database connection pool for '{database_name}'")
    return {
        "database": database_name,
        "max_connections": 100,
        "active_connections": 98,
        "waiting_clients": 24,
        "longest_wait_ms": 4200,
        "saturation_percentage": 98.0
    }


DIAGNOSTIC_TOOLS: Dict[str, ToolDefinition] = {
    "fetch_service_logs": ToolDefinition(
        name="fetch_service_logs",
        description="Query recent application logs and error traces for a given service.",
        tool_type=ToolType.DIAGNOSTIC,
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        parameters_schema={
            "service": "str",
            "lines": "int",
            "filter_term": "str"
        }
    ),
    "check_k8s_pod_status": ToolDefinition(
        name="check_k8s_pod_status",
        description="Inspect Kubernetes pod health, restarts, and exit codes.",
        tool_type=ToolType.DIAGNOSTIC,
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        parameters_schema={
            "namespace": "str",
            "selector": "str"
        }
    ),
    "query_prometheus_metrics": ToolDefinition(
        name="query_prometheus_metrics",
        description="Execute a read-only PromQL query against the observability cluster.",
        tool_type=ToolType.DIAGNOSTIC,
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        parameters_schema={
            "promql_query": "str",
            "step_seconds": "int"
        }
    ),
    "check_db_connection_pool": ToolDefinition(
        name="check_db_connection_pool",
        description="Inspect connection pool utilization, wait queues, and connection limits.",
        tool_type=ToolType.DIAGNOSTIC,
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        parameters_schema={
            "database_name": "str"
        }
    )
}
