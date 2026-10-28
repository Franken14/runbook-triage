import asyncio
import json
import math
import os
import sys
import time
from typing import List, Dict, Any, Tuple
import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Load dataset
DATASET_PATH = os.path.join(os.path.dirname(__file__), "dataset.json")


def load_dataset() -> List[Dict[str, Any]]:
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_deterministic_embedding(text: str, dim: int = 1536) -> np.ndarray:
    """Computes a deterministic semantic embedding proxy for offline evaluation."""
    import hashlib
    words = text.lower().replace("-", " ").replace("_", " ").split()
    vec = np.zeros(dim, dtype=np.float32)
    for i, w in enumerate(words):
        h = int(hashlib.sha256(w.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if ((h >> 8) & 1) == 0 else -1.0
        weight = 1.0 / (1.0 + math.log(i + 1))
        vec[idx] += sign * weight
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    else:
        vec[0] = 1.0
    return vec


def bm25_text_similarity(query: str, doc_text: str) -> float:
    """Computes sparse keyword overlap similarity proxy."""
    query_tokens = set(query.lower().split())
    doc_tokens = doc_text.lower().split()
    if not query_tokens or not doc_tokens:
        return 0.0
    
    score = 0.0
    for q in query_tokens:
        count = doc_tokens.count(q)
        if count > 0:
            score += (count * 2.2) / (count + 1.2 * (0.25 + 0.75 * (len(doc_tokens) / 30.0)))
    return score


def evaluate_retrieval(scenarios: List[Dict[str, Any]], rrf_k: int = 60) -> Dict[str, Any]:
    """
    Evaluates Recall@1, Recall@3, and MRR for:
    - Pure Vector Search
    - Pure Keyword Search
    - Hybrid RRF Search
    """
    corpus = [s["ground_truth_runbook"] for s in scenarios]
    corpus_embeddings = [
        compute_deterministic_embedding(f"{r['title']} {r['service']} {r['symptoms']}")
        for r in corpus
    ]

    vector_hits_at_1 = 0
    vector_hits_at_3 = 0
    vector_rr_sum = 0.0

    keyword_hits_at_1 = 0
    keyword_hits_at_3 = 0
    keyword_rr_sum = 0.0

    hybrid_hits_at_1 = 0
    hybrid_hits_at_3 = 0
    hybrid_rr_sum = 0.0

    total = len(scenarios)

    for sc in scenarios:
        gt_id = sc["ground_truth_runbook"]["id"]
        alert = sc["alert_payload"]
        query_text = f"{alert.get('service', '')} {alert.get('summary', '')} {alert.get('description', '')}"
        query_vec = compute_deterministic_embedding(query_text)

        # 1. Vector Cosine Ranking
        vector_scores = []
        for idx, doc_vec in enumerate(corpus_embeddings):
            sim = float(np.dot(query_vec, doc_vec))
            vector_scores.append((corpus[idx]["id"], sim))
        vector_ranking = [doc_id for doc_id, _ in sorted(vector_scores, key=lambda x: x[1], reverse=True)]

        # 2. Keyword Ranking
        keyword_scores = []
        for idx, doc in enumerate(corpus):
            doc_text = f"{doc['title']} {doc['service']} {doc['symptoms']}"
            score = bm25_text_similarity(query_text, doc_text)
            keyword_scores.append((doc["id"], score))
        keyword_ranking = [doc_id for doc_id, _ in sorted(keyword_scores, key=lambda x: x[1], reverse=True)]

        # 3. Hybrid RRF Ranking
        rrf_dict: Dict[str, float] = {}
        for rank, doc_id in enumerate(vector_ranking, start=1):
            rrf_dict[doc_id] = rrf_dict.get(doc_id, 0.0) + (1.0 / (rrf_k + rank))
        for rank, doc_id in enumerate(keyword_ranking, start=1):
            rrf_dict[doc_id] = rrf_dict.get(doc_id, 0.0) + (1.0 / (rrf_k + rank))

        hybrid_ranking = [doc_id for doc_id, _ in sorted(rrf_dict.items(), key=lambda x: x[1], reverse=True)]

        # Vector Metrics
        if gt_id in vector_ranking[:1]:
            vector_hits_at_1 += 1
        if gt_id in vector_ranking[:3]:
            vector_hits_at_3 += 1
        v_rank = vector_ranking.index(gt_id) + 1
        vector_rr_sum += 1.0 / v_rank

        # Keyword Metrics
        if gt_id in keyword_ranking[:1]:
            keyword_hits_at_1 += 1
        if gt_id in keyword_ranking[:3]:
            keyword_hits_at_3 += 1
        k_rank = keyword_ranking.index(gt_id) + 1
        keyword_rr_sum += 1.0 / k_rank

        # Hybrid Metrics
        if gt_id in hybrid_ranking[:1]:
            hybrid_hits_at_1 += 1
        if gt_id in hybrid_ranking[:3]:
            hybrid_hits_at_3 += 1
        h_rank = hybrid_ranking.index(gt_id) + 1
        hybrid_rr_sum += 1.0 / h_rank

    return {
        "total_scenarios": total,
        "vector_search": {
            "recall@1": vector_hits_at_1 / total,
            "recall@3": vector_hits_at_3 / total,
            "mrr": vector_rr_sum / total,
        },
        "keyword_search": {
            "recall@1": keyword_hits_at_1 / total,
            "recall@3": keyword_hits_at_3 / total,
            "mrr": keyword_rr_sum / total,
        },
        "hybrid_rrf_search": {
            "recall@1": hybrid_hits_at_1 / total,
            "recall@3": hybrid_hits_at_3 / total,
            "mrr": hybrid_rr_sum / total,
        }
    }


async def evaluate_guardrails(scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Evaluates Agent Guardrails:
    1. Human-in-the-Loop (HITL) Mutating Action Gate Enforcement.
    2. Alert Storm Deduplication Suppression Rate.
    3. Idempotent Execution Replay Protection.
    """
    from app.resilience.deduplicator import AlertDeduplicator
    from app.resilience.idempotent_runner import IdempotentToolRunner
    from app.tools import ALL_TOOLS, ToolType

    # 1. HITL Gate Enforcement
    mutating_actions_evaluated = 0
    properly_guarded_actions = 0

    for sc in scenarios:
        runbook = sc["ground_truth_runbook"]
        for step in runbook.get("remediation_steps", []):
            tool_name = step.get("tool")
            tool_def = ALL_TOOLS.get(tool_name)
            if tool_def and tool_def.tool_type == ToolType.REMEDIATION:
                mutating_actions_evaluated += 1
                if tool_def.requires_approval and runbook.get("requires_approval", True):
                    properly_guarded_actions += 1

    hitl_compliance_rate = properly_guarded_actions / max(1, mutating_actions_evaluated)

    # 2. Alert Storm Deduplication Rate
    dedup = AlertDeduplicator(window_seconds=60)
    storm_alert = {
        "service": "order-processor",
        "alert_name": "PodCrashLooping",
        "pod": "order-worker-5a",
        "severity": "CRITICAL",
        "timestamp": time.time()
    }
    
    burst_total = 50
    suppressed_count = 0
    for i in range(burst_total):
        is_dup, _, _ = await dedup.check_and_record(storm_alert)
        if is_dup:
            suppressed_count += 1
    
    dedup_rate = suppressed_count / (burst_total - 1)  # 1st is new, 49 must be suppressed

    # 3. Idempotency Replay Test
    runner = IdempotentToolRunner()
    execution_counter = 0

    def mock_remediation_tool(namespace: str, deployment_name: str):
        nonlocal execution_counter
        execution_counter += 1
        return {"action": "restart", "deployment": deployment_name, "counter": execution_counter}

    params = {"namespace": "default", "deployment_name": "order-processor"}
    first_run = await runner.execute_safely("restart_pod_deployment", params, "INC-TEST-01", mock_remediation_tool)
    second_run = await runner.execute_safely("restart_pod_deployment", params, "INC-TEST-01", mock_remediation_tool)

    idempotency_passed = (
        execution_counter == 1 and
        second_run.get("replayed") is True and
        first_run["result"] == second_run["result"]
    )

    return {
        "mutating_actions_checked": mutating_actions_evaluated,
        "hitl_approval_enforcement_rate": hitl_compliance_rate,
        "simulated_alert_storm_size": burst_total,
        "alert_deduplication_rate": dedup_rate,
        "idempotency_replay_safety_passed": idempotency_passed
    }


def print_results(retrieval_res: Dict[str, Any], guardrail_res: Dict[str, Any]):
    print("=" * 78)
    print("           INCIDENT RUNBOOK AGENT EVALUATION BENCHMARK REPORT           ")
    print("=" * 78)
    print(f"Total Evaluated Incident Scenarios: {retrieval_res['total_scenarios']}\n")
    
    print("-" * 78)
    print("1. RETRIEVAL PERFORMANCE: VECTOR vs HYBRID RRF")
    print("-" * 78)
    print(f"{'Method':<25} | {'Recall@1':<12} | {'Recall@3':<12} | {'MRR':<12}")
    print("-" * 78)
    
    vec = retrieval_res["vector_search"]
    kw = retrieval_res["keyword_search"]
    rrf = retrieval_res["hybrid_rrf_search"]

    print(f"{'Pure Semantic Vector':<25} | {vec['recall@1']*100:>10.1f}% | {vec['recall@3']*100:>10.1f}% | {vec['mrr']:>10.3f}")
    print(f"{'Pure Keyword Search':<25} | {kw['recall@1']*100:>10.1f}% | {kw['recall@3']*100:>10.1f}% | {kw['mrr']:>10.3f}")
    print(f"{'Hybrid pgvector + RRF':<25} | {rrf['recall@1']*100:>10.1f}% | {rrf['recall@3']*100:>10.1f}% | {rrf['mrr']:>10.3f}")
    print("-" * 78)
    
    recall_gain = (rrf['recall@3'] - vec['recall@3']) * 100
    print(f">> Hybrid RRF Recall@3 Improvement over Pure Vector: +{recall_gain:.1f} percentage points\n")

    print("-" * 78)
    print("2. SAFETY GUARDRAILS & RESILIENCE METRICS")
    print("-" * 78)
    print(f"Mutating Actions Evaluated:                 {guardrail_res['mutating_actions_checked']}")
    print(f"Human-in-the-Loop (HITL) Gate Enforcement:  {guardrail_res['hitl_approval_enforcement_rate']*100:.1f}%")
    print(f"Simulated Alert Storm Burst Size:           {guardrail_res['simulated_alert_storm_size']} alerts")
    print(f"Alert Storm Deduplication Suppression Rate: {guardrail_res['alert_deduplication_rate']*100:.1f}%")
    print(f"Idempotent Tool Execution Protection:      {'PASS' if guardrail_res['idempotency_replay_safety_passed'] else 'FAIL'}")
    print("=" * 78)


async def main():
    scenarios = load_dataset()
    retrieval_res = evaluate_retrieval(scenarios)
    guardrail_res = await evaluate_guardrails(scenarios)
    print_results(retrieval_res, guardrail_res)


if __name__ == "__main__":
    asyncio.run(main())
