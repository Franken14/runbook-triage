# System Architecture & Design: Incident Runbook Triage

## 1. Overview & Problem Context

Modern cloud-native systems generate severe operational complexity during outages. Production alert storms from Prometheus, Datadog, or PagerDuty create high cognitive fatigue for on-call engineers who must correlate symptoms, find pertinent runbooks, and perform safe diagnostic and remediation actions under time pressure.

Automating this workflow with standard LLM agents introduces severe operational hazards:
1. **Hallucination & Blast Radius**: Unchecked agent execution can execute destructive commands or misinterpret Kubernetes error states.
2. **Alert Storm Cascades**: Identical alerts firing concurrently across microservices can spawn duplicate remediation loops, causing race conditions and service destabilization.
3. **Fragile Lookup**: Pure semantic search often misses exact alphanumeric error codes (e.g. exit code `137`, HTTP `504`), while keyword search fails when symptoms are described using alternative phrasing.

This system addresses these challenges with a deterministic, state-machine-driven architecture combining LangGraph checkpointing, Reciprocal Rank Fusion (RRF) hybrid retrieval, Redis-backed concurrency guardrails, and strict human-in-the-loop (HITL) approval gates.

---

## 2. Agent Workflow & State Machine

The triage pipeline is orchestrated as a directed graph using LangGraph. State is checkpointed into PostgreSQL after every transition, ensuring durability across container restarts and enabling long-lived human approval pauses.

```
       [ Alert Ingestion ]
               ?
               ?
   [ Hybrid RRF Retrieval ]
               ?
               ?
 [ Sandboxed Diagnostics (Read-Only) ]
               ?
               ?
     [ Root Cause Analysis ]
               ?
               ?
     { Requires Approval? }
            /      \
     (No)  /        \ (Yes)
          /          ?
         ?     [ HITL Interrupt Gate ]
         ?          ?  (POST /approve)
         ?          ??? APPROVED ???
         ?          ??? REJECTED ????> [ Escalate to SRE ]
         ?                         ?          ?
         ?                         ?          ?
   [ Idempotent Remediation Execution ]       ?
               ?                              ?
               ????????????????????????????????
                              ?
                [ Finalize & Resolution ]
```

### State Graph Specification

| Node | Responsibilities | Output State |
| :--- | :--- | :--- |
| `ingest_alert` | Parses alert payload, extracts service, severity, and telemetry hints | `service`, `severity`, `status: RETRIEVING` |
| `retrieve_runbook` | Executes hybrid pgvector + tsvector RRF query to find matching runbooks | `retrieved_runbooks`, `selected_runbook`, `diagnostic_plan` |
| `execute_diagnostics` | Executes safe, read-only diagnostic tools (log sampling, pod status, PromQL) | `diagnostic_results`, `status: EVALUATING_REMEDIATION` |
| `evaluate_remediation` | Synthesizes diagnostic findings into an RCA and determines mutating tool requirements | `root_cause_analysis`, `proposed_remediations`, `requires_approval` |
| `human_approval` | Interrupt gate pausing execution until operator approval is received | `approval_status`, `status: AWAITING_APPROVAL` |
| `execute_remediation` | Executes approved actions through the Redis-locked idempotent runner | `remediation_results`, `status: VERIFYING` |
| `finalize_incident` | Compiles post-incident timeline, resolution summary, and marks status | `status: RESOLVED` (or `ESCALATED`) |

### Checkpointing & Resumption Semantics
To decouple on-call reaction time from runtime state, the workflow compiles with:
```python
workflow.compile(
    checkpointer=checkpointer,
    interrupt_before=["human_approval"]
)
```
Each incident is isolated by a persistent `thread_id` (e.g. `INC-8A3F12CD`). When an operator reviews the RCA via the web console or Slack webhook and submits `POST /api/v1/incidents/{incident_id}/approve`, the checkpoint is updated and the graph resumes execution from the exact point of interruption.

---

## 3. Hybrid RRF Retrieval Engine

### The Vocabulary Mismatch Dilemma
Runbook retrieval exhibits two distinct failure modes under single-paradigm search:
- **Dense Vector Search (Cosine Similarity)**: Captures high-level semantic intent (e.g., "database connection starvation" matches "connection pool exhaustion"), but fails on exact identifiers like error codes (`137`, `OOMKilled`), service names, or Kubernetes labels.
- **Sparse Full-Text Search (tsvector / BM25)**: Accurately isolates exact keywords, but fails when incident reporters use alternative wording (e.g., "memory leak" vs "heap exhaustion").

### Reciprocal Rank Fusion (RRF)
We fuse both retrieval paths using Reciprocal Rank Fusion without requiring brittle score calibration:

$$RRF(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$

Where:
- $M = \{\text{pgvector}, \text{tsvector}\}$
- $k = 60$ (smoothing constant preventing top ranks from dominating)
- $r_m(d)$ is the 1-based rank of document $d$ in retrieval method $m$.

### PostgreSQL Storage & Indexing Strategy
```sql
-- Semantic Cosine Similarity Index
CREATE INDEX idx_runbooks_embedding ON runbooks
USING hnsw (embedding vector_cosine_ops);

-- Full-Text Search GIN Index
CREATE INDEX idx_runbooks_search_vector ON runbooks
USING GIN(search_vector);

-- Weighted tsvector Generation Trigger
CREATE TRIGGER trg_runbooks_search_vector
BEFORE INSERT OR UPDATE ON runbooks
FOR EACH ROW EXECUTE FUNCTION
tsvector_update_trigger(
    search_vector, 'pg_catalog.english',
    title, service, symptoms
);
```

---

## 4. Resilience & Concurrency Guardrails

### Alert Storm Suppression (`AlertDeduplicator`)
During cascading infrastructure failures, monitoring systems often send bursts of identical alerts within seconds. 

1. **Deterministic Fingerprinting**:
   $$\text{Fingerprint} = \text{SHA256}(\text{service} \parallel \text{alert\_name} \parallel \text{entity} \parallel \text{severity})$$
2. **Atomic Sliding Window**:
   ```python
   is_new = await redis_client.set(f"alert:dedup:{fingerprint}", incident_id, ex=window_seconds, nx=True)
   ```
   If `is_new` is false, incoming alerts are flagged as `SUPPRESSED_DUPLICATE` and an atomic counter tracks storm volume without triggering redundant agent instances.

### Distributed Mutex & Idempotency (`IdempotentToolRunner`)
Mutating actions (pod restarts, replica scaling, cache evictions) must never be executed twice due to network timeouts, retries, or duplicate worker loops.

1. **Idempotency Key Formulation**:
   Derived from canonical SHA256 of `incident_id`, `tool_name`, and deterministic JSON-serialized parameters.
2. **Distributed Mutex**:
   Acquires a 30-second Redis lock (`SET lock_key token NX EX 30`). Concurrent calls with the same key block or reject.
3. **Execution Receipt**:
   On completion, the execution result is cached with a 24-hour TTL. Replayed requests return the cached receipt with `"replayed": True`.

---

## 5. Tool Safety & Classification Model

Tools are strictly partitioned by blast radius:

| Tool Name | Class | Risk Tier | Requires Approval | Safeguard Mechanism |
| :--- | :--- | :--- | :--- | :--- |
| `fetch_service_logs` | DIAGNOSTIC | Low | No | Read-only log queries, hard limit on line count |
| `check_k8s_pod_status` | DIAGNOSTIC | Low | No | Read-only Kubernetes API inspection |
| `query_prometheus_metrics` | DIAGNOSTIC | Low | No | Read-only PromQL execution |
| `check_db_connection_pool` | DIAGNOSTIC | Low | No | Read-only connection statistics query |
| `restart_pod_deployment` | REMEDIATION | Medium | **Yes** | Rolling restart policy, operator sign-off required |
| `scale_service_replicas` | REMEDIATION | Medium | **Yes** | Replicas bounded between [1, 20], requires approval |
| `flush_redis_cache_key` | REMEDIATION | High | **Yes** | Key prefix restriction, operator sign-off required |
| `rollback_canary_deployment`| REMEDIATION | Critical | **Yes** | Revision verification, senior SRE approval required |

---

## 6. Benchmarking & Offline Evaluation

The evaluation harness in `evals/benchmark.py` evaluates the retrieval pipeline against 25 synthetic incidents with ground-truth runbooks.

### Key Benchmark Metrics
- **Recall@1 / Recall@3**: Evaluates how often the correct runbook is retrieved in the top candidates. Hybrid RRF achieves higher recall than pure vector or keyword search on noisy incident descriptions.
- **Mean Reciprocal Rank (MRR)**: Measures ranking precision for the target runbook.
- **Safety Gate Enforcement**: Verifies that 100% of mutating remediation tools halt at the human-in-the-loop gate before execution.
- **Storm Suppression Rate**: Validates that duplicate alert bursts within the debounce window are intercepted without triggering duplicate runs.
