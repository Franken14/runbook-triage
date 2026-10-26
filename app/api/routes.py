import asyncio
import json
import logging
import uuid
from typing import Dict, Any, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, status
from pydantic import BaseModel
from app.resilience.deduplicator import AlertDeduplicator
from app.agent.graph import incident_agent_app

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/incidents", tags=["Incidents"])

deduplicator = AlertDeduplicator()

# In-memory store for active WebSocket connections by incident_id
connected_clients: Dict[str, list[WebSocket]] = {}
# Active execution state cache for rapid API queries
active_incidents: Dict[str, Dict[str, Any]] = {}


class WebhookPayload(BaseModel):
    service: str
    alert_name: str
    severity: str = "HIGH"
    summary: str
    description: Optional[str] = None
    labels: Optional[Dict[str, str]] = {}
    host: Optional[str] = None
    pod: Optional[str] = None


class ApprovalPayload(BaseModel):
    decision: str  # "APPROVED" or "REJECTED"
    approver: str
    notes: Optional[str] = None


async def broadcast_event(incident_id: str, event_data: Dict[str, Any]):
    """Broadcast an event to all connected WebSockets for this incident."""
    if incident_id in connected_clients:
        disconnected = []
        for ws in connected_clients[incident_id]:
            try:
                await ws.send_text(json.dumps(event_data))
            except Exception:
                disconnected.append(ws)
        for dead in disconnected:
            connected_clients[incident_id].remove(dead)


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def ingest_webhook_alert(alert: WebhookPayload):
    """
    Ingests an alert from monitoring tools (Prometheus, Datadog, PagerDuty).
    Applies deduplication to suppress alert storms and starts agent triage.
    """
    payload_dict = alert.dict()
    is_duplicate, fingerprint, count = await deduplicator.check_and_record(payload_dict)

    if is_duplicate:
        return {
            "status": "SUPPRESSED_DUPLICATE",
            "message": f"Alert storm detected. Suppressed duplicate alert (count: {count}).",
            "fingerprint": fingerprint
        }

    incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
    initial_state = {
        "incident_id": incident_id,
        "alert_payload": payload_dict,
        "service": alert.service,
        "severity": alert.severity,
        "fingerprint": fingerprint,
        "status": "INGESTED",
        "diagnostic_results": [],
        "remediation_results": [],
        "stream_events": []
    }

    active_incidents[incident_id] = initial_state

    # Run agent in background thread/task up to HITL checkpoint or completion
    config = {"configurable": {"thread_id": incident_id}}
    
    async def run_agent():
        try:
            async for event in incident_agent_app.astream(initial_state, config=config):
                for node_name, node_update in event.items():
                    logger.info(f"[{incident_id}] Node completed: {node_name}")
                    if "stream_events" in node_update:
                        for evt in node_update["stream_events"]:
                            await broadcast_event(incident_id, evt)
                    
                    # Update local state cache
                    if incident_id in active_incidents:
                        active_incidents[incident_id].update(node_update)

            # Check if stopped at interrupt
            state_snapshot = incident_agent_app.get_state(config)
            if state_snapshot.next:
                logger.info(f"[{incident_id}] Paused at interrupt before {state_snapshot.next}")
                await broadcast_event(incident_id, {
                    "type": "WAITING_APPROVAL",
                    "incident_id": incident_id,
                    "proposed_remediations": state_snapshot.values.get("proposed_remediations"),
                    "requires_approval": state_snapshot.values.get("requires_approval")
                })
        except Exception as e:
            logger.error(f"Error during agent execution: {e}", exc_info=True)

    asyncio.create_task(run_agent())

    return {
        "status": "TRIGGERED",
        "incident_id": incident_id,
        "fingerprint": fingerprint,
        "service": alert.service
    }


@router.post("/{incident_id}/approve", status_code=status.HTTP_200_OK)
async def approve_incident_remediation(incident_id: str, approval: ApprovalPayload):
    """
    Human-in-the-loop endpoint to approve or reject remediation plan.
    Resumes LangGraph execution from checkpoint.
    """
    config = {"configurable": {"thread_id": incident_id}}
    state_snapshot = incident_agent_app.get_state(config)

    if not state_snapshot.values:
        raise HTTPException(status_code=404, detail="Incident not found or no state available.")

    decision = approval.decision.upper()
    if decision not in ["APPROVED", "REJECTED"]:
        raise HTTPException(status_code=400, detail="Decision must be APPROVED or REJECTED.")

    # Update state with human decision
    incident_agent_app.update_state(
        config,
        {
            "approval_status": decision,
            "approved_by": approval.approver,
            "rejection_reason": approval.notes if decision == "REJECTED" else None
        }
    )

    await broadcast_event(incident_id, {
        "type": "APPROVAL_DECISION_RECEIVED",
        "decision": decision,
        "approver": approval.approver
    })

    # Resume execution from checkpoint
    async def resume_agent():
        try:
            async for event in incident_agent_app.astream(None, config=config):
                for node_name, node_update in event.items():
                    if "stream_events" in node_update:
                        for evt in node_update["stream_events"]:
                            await broadcast_event(incident_id, evt)
                    if incident_id in active_incidents:
                        active_incidents[incident_id].update(node_update)
        except Exception as e:
            logger.error(f"Error while resuming agent for {incident_id}: {e}", exc_info=True)

    asyncio.create_task(resume_agent())

    return {
        "incident_id": incident_id,
        "status": f"RESUMED_AS_{decision}",
        "approver": approval.approver
    }


@router.get("/{incident_id}/status")
async def get_incident_status(incident_id: str):
    """Fetches the current status and execution trajectory for an incident."""
    config = {"configurable": {"thread_id": incident_id}}
    state_snapshot = incident_agent_app.get_state(config)
    
    if state_snapshot.values:
        return {
            "incident_id": incident_id,
            "next_nodes": state_snapshot.next,
            "state": state_snapshot.values
        }

    if incident_id in active_incidents:
        return {
            "incident_id": incident_id,
            "state": active_incidents[incident_id]
        }

    raise HTTPException(status_code=404, detail="Incident not found.")


@router.websocket("/{incident_id}/stream")
async def websocket_incident_stream(websocket: WebSocket, incident_id: str):
    """WebSocket endpoint to stream live agent thoughts, diagnostic traces, and HITL updates."""
    await websocket.accept()
    if incident_id not in connected_clients:
        connected_clients[incident_id] = []
    connected_clients[incident_id].append(websocket)

    try:
        # Send initial acknowledgment
        await websocket.send_text(json.dumps({
            "type": "STREAM_CONNECTED",
            "incident_id": incident_id,
            "message": "Connected to incident live event stream."
        }))

        # Keep connection open for incoming pings or client messages
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from stream {incident_id}")
    finally:
        if incident_id in connected_clients and websocket in connected_clients[incident_id]:
            connected_clients[incident_id].remove(websocket)
