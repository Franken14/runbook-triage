import logging
from app.agent.state import IncidentState

logger = logging.getLogger(__name__)


def route_after_evaluation(state: IncidentState) -> str:
    """
    Evaluates whether the proposed remediation plan requires human approval
    or can proceed autonomously.
    """
    if state.get("requires_approval", True):
        logger.info("Plan requires approval. Routing to human_approval.")
        return "human_approval"
    logger.info("Plan is low risk / non-mutating. Routing directly to execute_remediation.")
    return "execute_remediation"


def route_after_approval(state: IncidentState) -> str:
    """
    Routes based on the outcome of human review.
    """
    status = state.get("approval_status", "PENDING")
    if status == "APPROVED":
        logger.info("Approval granted. Routing to execute_remediation.")
        return "execute_remediation"
    else:
        logger.info(f"Remediation was not approved (status: {status}). Finalizing/escalating.")
        return "finalize_incident"
