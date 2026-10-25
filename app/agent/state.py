from typing import TypedDict, List, Dict, Any, Optional, Annotated
import operator


class IncidentState(TypedDict, total=False):
    """
    LangGraph execution state schema for incident triage and remediation.
    Annotated fields support merging/appending across steps.
    """
    incident_id: str
    alert_payload: Dict[str, Any]
    service: str
    severity: str
    fingerprint: str
    status: str  # INGESTED, RETRIEVING, DIAGNOSING, AWAITING_APPROVAL, REMEDIATING, RESOLVED, ESCALATED
    
    # Runbook Retrieval
    retrieved_runbooks: List[Dict[str, Any]]
    selected_runbook: Optional[Dict[str, Any]]
    
    # Diagnostics
    diagnostic_plan: List[Dict[str, Any]]
    diagnostic_results: Annotated[List[Dict[str, Any]], operator.add]
    diagnostic_iterations: int
    
    # Root Cause & Proposed Actions
    root_cause_analysis: str
    proposed_remediations: List[Dict[str, Any]]
    
    # Guardrails & Human-In-The-Loop (HITL)
    requires_approval: bool
    approval_status: str  # PENDING, APPROVED, REJECTED
    approved_by: Optional[str]
    rejection_reason: Optional[str]
    
    # Execution & Verification
    remediation_results: Annotated[List[Dict[str, Any]], operator.add]
    resolution_summary: str
    
    # Live Streaming Logs
    stream_events: Annotated[List[Dict[str, Any]], operator.add]
