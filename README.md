# runbook-triage

Autonomous incident triage and remediation agent for Site Reliability Engineering (SRE) teams, built with **LangGraph**, **PostgreSQL pgvector + tsvector Hybrid RRF**, and **Redis resilience guardrails**.

---

## Architecture Overview

```
Alert Ingestion (Prometheus / Datadog / PagerDuty)
         ?
         ?
[Redis Alert Deduplicator] ?? (Duplicate?) ??> Suppress storm (200 OK)
         ? (New Alert)
         ?
[LangGraph State Machine (PostgresSaver Checkpointed)]
  ??? 1. Ingest & Classify Alert
  ??? 2. Hybrid RRF Search (pgvector + tsvector, k=60)
  ??? 3. Execute Read-Only Sandboxed Diagnostics
  ??? 4. Root Cause Analysis & Plan Formulation
  ??? 5. Safety Gate (Mutating Action Check)
  ?         ?
  ?         ??> Non-Mutating (Low Risk) ??> Auto-Execute
  ?         ?
  ?         ??> Mutating (Medium/High Risk) ??> [PAUSE: HITL Interrupt]
  ?                                                   ?
  ?                                                   ??> POST /approve APPROVED
  ?                                                   ??> POST /approve REJECTED
  ??? 6. Idempotent Tool Execution (Redis Distributed Lock + Receipt)
  ??? 7. Finalize & Post-Incident Summary
```

---

## Core Capabilities

- **Stateful Human-in-the-Loop (HITL) Checkpoints**: Orchestrated via LangGraph. Low-risk diagnostics execute automatically, while high-blast-radius remediation actions pause execution at an interrupt gate until confirmed by an on-call SRE via API/webhook.
- **Hybrid Reciprocal Rank Fusion (RRF)**: Combines dense pgvector cosine embeddings (semantic understanding) with sparse PostgreSQL tsvector text search (exact error codes, service names, and namespaces) using RRF ($k=60$).
- **Alert Storm Deduplication**: Intercepts bursts of concurrent identical alerts using atomic Redis operations and SHA-256 fingerprinting across service, alert name, and severity.
- **Idempotent Tool Execution**: Enforces a distributed Redis mutex lock and 24-hour receipt caching to prevent duplicate executions from network retries or concurrent worker loops.
- **Live Event Streaming**: Exposes real-time agent reasoning steps, diagnostic traces, and HITL gate updates over WebSockets.

---

## Project Structure

```
runbook-triage/
??? app/
?   ??? api/            # FastAPI routes (webhooks, approval resume, WebSocket stream)
?   ??? agent/          # LangGraph nodes, edges, state schema, PostgresSaver checkpointer
?   ??? retrieval/      # PostgreSQL pgvector + tsvector Hybrid RRF search
?   ??? resilience/     # Redis alert deduplicator + idempotent tool execution runner
?   ??? tools/          # Sandboxed diagnostic (read-only) & remediation (mutating) tools
??? docs/
?   ??? ARCHITECTURE.md # Detailed system design, failure modes, and trade-offs
??? evals/
?   ??? dataset.json    # 25 synthetic incident scenarios + ground-truth runbooks
?   ??? benchmark.py    # Offline benchmark harness (Recall@3, MRR, Guardrail metrics)
??? tests/              # Unit test suite (deduplication, tool safety, RRF ranking)
??? docker-compose.yml  # FastAPI + pgvector/pg16 + Redis 7
??? Dockerfile          # Container build definition
??? Makefile            # Developer shortcuts (test, benchmark, docker-up)
??? requirements.txt    # Python dependencies
```

---

## Getting Started

### Prerequisites
- Docker & Docker Compose **or** Python 3.11+
- PostgreSQL 16 with `pgvector` & Redis 7+

### Option 1: Run with Docker Compose (Recommended)

1. Clone and navigate to the repository:
   ```bash
   git clone https://github.com/Franken14/runbook-triage.git
   cd runbook-triage
   ```

2. Start all services:
   ```bash
   docker compose up -d
   ```

3. Verify service health:
   ```bash
   docker compose ps
   curl http://localhost:8000/healthz
   ```

Interactive Swagger documentation is available at `http://localhost:8000/docs`.

---

### Option 2: Local Setup

1. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: .\venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Start the API server:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

---

## API Reference

### 1. Ingest Incident Alert (`POST /api/v1/incidents/webhook`)
Ingests an alert payload from Prometheus Alertmanager, Datadog, or PagerDuty. Deduplicates alerts within a sliding window to stop alert storms.

```bash
curl -X POST http://localhost:8000/api/v1/incidents/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "service": "order-processor",
    "alert_name": "PodCrashLooping",
    "severity": "CRITICAL",
    "summary": "Container order-worker terminated with exit code 137 (OOMKilled)",
    "description": "Pod order-processor-7b6c5-2x9v1 memory limit 512Mi exceeded",
    "pod": "order-processor-7b6c5-2x9v1"
  }'
```

**Response:**
```json
{
  "status": "TRIGGERED",
  "incident_id": "INC-8A3F12CD",
  "fingerprint": "d2e67a42b109...",
  "service": "order-processor"
}
```

### 2. Live Agent Streaming (`WebSocket /api/v1/incidents/{incident_id}/stream`)
Connect via WebSocket to receive real-time JSON events of agent reasoning steps, diagnostic traces, and HITL approval notifications:

```javascript
const ws = new WebSocket("ws://localhost:8000/api/v1/incidents/INC-8A3F12CD/stream");
ws.onmessage = (event) => console.log(JSON.parse(event.data));
```

### 3. Human Approval Gate (`POST /api/v1/incidents/{incident_id}/approve`)
Resumes the paused LangGraph workflow with an SRE decision:

```bash
curl -X POST http://localhost:8000/api/v1/incidents/INC-8A3F12CD/approve \
  -H "Content-Type: application/json" \
  -d '{
    "decision": "APPROVED",
    "approver": "sre-oncall@company.com",
    "notes": "Verified pod memory limit was breached. Approving replica scaling."
  }'
```

### 4. Query Incident Status (`GET /api/v1/incidents/{incident_id}/status`)
```bash
curl http://localhost:8000/api/v1/incidents/INC-8A3F12CD/status
```

---

## Running Tests & Benchmarks

### Unit Tests
Run the test suite covering alert deduplication, tool safety tiers, and RRF rank fusion:
```bash
make test
# or: python3 -m unittest discover -s tests -v
```

### Evaluation Benchmark
Run the offline evaluation benchmark against 25 synthetic incident scenarios:
```bash
make benchmark
# or: python3 evals/benchmark.py
```

The benchmark reports:
- **Recall@1 & Recall@3**: Evaluates retrieval accuracy across Pure Vector, Sparse Keyword, and Hybrid RRF.
- **MRR (Mean Reciprocal Rank)**: Measures rank placement of ground-truth runbooks.
- **HITL Gate Enforcement Rate**: Verifies 100% interruption on mutating tools.
- **Alert Storm Suppression**: Tests burst deduplication efficacy under concurrent identical alerts.
- **Idempotency Replay Protection**: Verifies that replayed actions return cached receipts.

---

## Architecture Deep-Dive

For a detailed breakdown of state machine transitions, pgvector schema and index definitions, Redis locking mechanics, and production trade-offs, refer to [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## License

MIT
