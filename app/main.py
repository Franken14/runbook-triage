from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.routes import router as incident_router
from app.retrieval.hybrid_search import HybridRRFSearcher
from app.resilience.deduplicator import AlertDeduplicator

logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("incident_agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Incident Runbook Agent services...")
    # Initialize background connection pools
    yield
    logger.info("Shutting down Incident Runbook Agent services...")


app = FastAPI(
    title="Incident Runbook Agent API",
    description="Autonomous SRE incident triage and remediation agent powered by LangGraph, pgvector Hybrid RRF, and Redis resilience guardrails.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(incident_router)


@app.get("/healthz", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": "incident-runbook-agent",
        "version": "1.0.0"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
