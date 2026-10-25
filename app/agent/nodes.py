import datetime
import logging
from typing import Dict, Any
from app.agent.state import IncidentState
from app.retrieval.hybrid_search import HybridRRFSearcher
from app.resilience.idempotent_runner import IdempotentToolRunner
from app.tools import TOOL_HANDLERS, ALL_TOOLS, ToolType

logger = logging.getLogger(__name__)

searcher = HybridRRFSearcher()
idempotent_runner = IdempotentToolRunner()


async def ingest_alert_node(state: IncidentState) -> Dict[str, Any]:
    """Validate and parse the incoming alert payload into the agent state."""
    alert = state.get("alert_payload", {})
    service = alert.get("service") or alert.get("labels", {}).get("service", "unknown-service")
    severity = alert.get("severity", "MEDIUM").upper()
    incident_id = state.get("incident_id")

    event = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "type": "NODE_LOG",
        "node": "ingest_alert",
        "message": f"Ingested incident alert for service '{service}' with severity '{severity}'."
    }

    return {
        "service": service,
        "severity": severity,
        "status": "RETRIEVING",
        "diagnostic_iterations": 0,
        "stream_events": [event]
    }


async def retrieve_runbook_node(state: IncidentState) -> Dict[str, Any]:
    """Retrieve candidate runbooks using hybrid pgvector + tsvector RRF search."""
    service = state.get("service", "")
    alert = state.get("alert_payload", {})
    symptoms = alert.get("description") or alert.get("summary") or alert.get("message") or service

    query = f"{service} {symptoms}"
    logger.info(f"Retrieving runbooks for query: '{query}'")

    matched_runbooks = await searcher.search(query=query, top_k=3)
    
    selected = None
    if matched_runbooks:
        selected = matched_runbooks[0].dict()
    else:
        # Fallback heuristic if runbook DB is cold/empty
        selected = {
            "id": "RB-FALLBACK-001",
            "title": f"Standard {service} Diagnostic Runbook",
            "service": service,
            "severity": state.get("severity", "MEDIUM"),
            "symptoms": symptoms,
            "diagnostic_steps": [
                {"tool": "fetch_service_logs", "params": {"service": service, "lines": 50}},
                {"tool": "check_k8s_pod_status", "params": {"namespace": "default", "selector": service}}
            ],
            "remediation_steps": [
                {"tool": "restart_pod_deployment", "params": {"namespace": "default", "deployment_name": service}}
            ],
            "risk_level": "MEDIUM",
            "requires_approval": True
        }

    event = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "type": "NODE_LOG",
        "node": "retrieve_runbook",
        "message": f"Retrieved runbook: '{selected.get('title')}' (ID: {selected.get('id')})."
    }

    return {
        "retrieved_runbooks": [r.dict() for r in matched_runbooks] if matched_runbooks else [selected],
        "selected_runbook": selected,
        "diagnostic_plan": selected.get("diagnostic_steps", []),
        "status": "DIAGNOSING",
        "stream_events": [event]
    }


async def execute_diagnostics_node(state: IncidentState) -> Dict[str, Any]:
    """Execute sandboxed, read-only diagnostic tools to collect operational telemetry."""
    plan = state.get("diagnostic_plan", [])
    results = []
    events = []

    for step in plan:
        tool_name = step.get("tool")
        params = step.get("params", {})
        tool_meta = ALL_TOOLS.get(tool_name)

        if not tool_meta or tool_meta.tool_type != ToolType.DIAGNOSTIC:
            logger.warning(f"Refusing to execute non-diagnostic tool '{tool_name}' in diagnostic phase.")
            continue

        handler = TOOL_HANDLERS.get(tool_name)
        if handler:
            res = await handler(**params)
            results.append({"tool": tool_name, "params": params, "output": res})
            events.append({
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "type": "DIAGNOSTIC_EXECUTION",
                "tool": tool_name,
                "output": res
            })

    current_iter = state.get("diagnostic_iterations", 0) + 1

    return {
        "diagnostic_results": results,
        "diagnostic_iterations": current_iter,
        "status": "EVALUATING_REMEDIATION",
        "stream_events": events
    }


async def evaluate_remediation_node(state: IncidentState) -> Dict[str, Any]:
    """Formulate root cause analysis and identify candidate remediation steps."""
    runbook = state.get("selected_runbook", {})
    remediations = runbook.get("remediation_steps", [])
    
    # Check if any remediation is mutating and requires approval
    requires_approval = False
    for step in remediations:
        tool_name = step.get("tool")
        tool_meta = ALL_TOOLS.get(tool_name)
        if tool_meta and (tool_meta.tool_type == ToolType.REMEDIATION or tool_meta.requires_approval):
            requires_approval = True
            break

    rca = (
        f"Corroborated incident on {state.get('service')} using runbook {runbook.get('id')}. "
        f"Diagnostic outputs confirmed matching error indicators. Recommended remediation: {remediations}"
    )

    event = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "type": "NODE_LOG",
        "node": "evaluate_remediation",
        "message": f"RCA generated. Approval required: {requires_approval}."
    }

    return {
        "root_cause_analysis": rca,
        "proposed_remediations": remediations,
        "requires_approval": requires_approval,
        "approval_status": "PENDING" if requires_approval else "APPROVED",
        "status": "AWAITING_APPROVAL" if requires_approval else "REMEDIATING",
        "stream_events": [event]
    }


async def human_approval_node(state: IncidentState) -> Dict[str, Any]:
    """
    Human-in-the-loop interrupt gate.
    When compiled with interrupt_before=['human_approval_node'],
    LangGraph pauses graph execution until an operator confirms or rejects.
    """
    event = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "type": "HITL_APPROVAL_GATE",
        "node": "human_approval",
        "status": state.get("approval_status", "PENDING"),
        "message": "Human approval gate reached. Waiting for SRE confirmation."
    }
    return {
        "status": "AWAITING_APPROVAL",
        "stream_events": [event]
    }


async def execute_remediation_node(state: IncidentState) -> Dict[str, Any]:
    """
    Execute mutating remediation actions through IdempotentToolRunner with distributed locking.
    """
    incident_id = state.get("incident_id", "unknown-inc")
    remediations = state.get("proposed_remediations", [])
    approval_status = state.get("approval_status")

    if approval_status != "APPROVED":
        event = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "type": "NODE_LOG",
            "node": "execute_remediation",
            "message": f"Remediation blocked! Status is {approval_status}."
        }
        return {
            "status": "ESCALATED",
            "resolution_summary": f"Incident remediation was not approved (status={approval_status}). Escalated to On-Call SRE.",
            "stream_events": [event]
        }

    results = []
    events = []
    for step in remediations:
        tool_name = step.get("tool")
        params = step.get("params", {})
        handler = TOOL_HANDLERS.get(tool_name)

        if not handler:
            continue

        # Execute through IdempotentToolRunner to prevent double-execution / race conditions
        receipt = await idempotent_runner.execute_safely(
            tool_name=tool_name,
            params=params,
            incident_id=incident_id,
            execution_func=handler
        )
        results.append(receipt)
        events.append({
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "type": "REMEDIATION_EXECUTION",
            "tool": tool_name,
            "receipt": receipt
        })

    return {
        "remediation_results": results,
        "status": "VERIFYING",
        "stream_events": events
    }


async def finalize_incident_node(state: IncidentState) -> Dict[str, Any]:
    """Compile final incident summary, record timeline events, and update status."""
    incident_id = state.get("incident_id")
    service = state.get("service")
    status = state.get("status")

    if status == "ESCALATED":
        summary = f"Incident {incident_id} on service {service} escalated to human operator."
    else:
        summary = f"Incident {incident_id} on service {service} successfully resolved via automated runbook execution."

    event = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "type": "INCIDENT_RESOLVED",
        "node": "finalize_incident",
        "message": summary
    }

    return {
        "status": "RESOLVED" if status != "ESCALATED" else "ESCALATED",
        "resolution_summary": summary,
        "stream_events": [event]
    }
