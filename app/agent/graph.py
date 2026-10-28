import logging
from typing import Optional, Any
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from app.agent.state import IncidentState
from app.agent.nodes import (
    ingest_alert_node,
    retrieve_runbook_node,
    execute_diagnostics_node,
    evaluate_remediation_node,
    human_approval_node,
    execute_remediation_node,
    finalize_incident_node,
)
from app.agent.edges import (
    route_after_evaluation,
    route_after_approval,
)

logger = logging.getLogger(__name__)


def build_incident_graph(checkpointer: Optional[Any] = None):
    """
    Constructs the LangGraph state machine with human-in-the-loop interruption.
    """
    workflow = StateGraph(IncidentState)

    # 1. Register Nodes
    workflow.add_node("ingest_alert", ingest_alert_node)
    workflow.add_node("retrieve_runbook", retrieve_runbook_node)
    workflow.add_node("execute_diagnostics", execute_diagnostics_node)
    workflow.add_node("evaluate_remediation", evaluate_remediation_node)
    workflow.add_node("human_approval", human_approval_node)
    workflow.add_node("execute_remediation", execute_remediation_node)
    workflow.add_node("finalize_incident", finalize_incident_node)

    # 2. Add Fixed Transitions
    workflow.add_edge(START, "ingest_alert")
    workflow.add_edge("ingest_alert", "retrieve_runbook")
    workflow.add_edge("retrieve_runbook", "execute_diagnostics")
    workflow.add_edge("execute_diagnostics", "evaluate_remediation")

    # 3. Add Conditional Transitions
    workflow.add_conditional_edges(
        "evaluate_remediation",
        route_after_evaluation,
        {
            "human_approval": "human_approval",
            "execute_remediation": "execute_remediation"
        }
    )

    workflow.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {
            "execute_remediation": "execute_remediation",
            "finalize_incident": "finalize_incident"
        }
    )

    workflow.add_edge("execute_remediation", "finalize_incident")
    workflow.add_edge("finalize_incident", END)

    # Use MemorySaver by default, or an external checkpointer (e.g., PostgresSaver)
    cp = checkpointer if checkpointer is not None else MemorySaver()

    # Compile with human-in-the-loop pause before entering human_approval
    app = workflow.compile(
        checkpointer=cp,
        interrupt_before=["human_approval"]
    )
    return app


# Default singleton instance for the app
incident_agent_app = build_incident_graph()
