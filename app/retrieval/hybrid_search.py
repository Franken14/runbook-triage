import logging
import math
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import asyncpg
from app.config import settings

logger = logging.getLogger(__name__)


class RunbookRecord(BaseModel):
    id: str
    title: str
    service: str
    severity: str
    symptoms: str
    root_causes: List[str]
    diagnostic_steps: List[Dict[str, Any]]
    remediation_steps: List[Dict[str, Any]]
    risk_level: str
    requires_approval: bool
    rrf_score: Optional[float] = 0.0
    vector_rank: Optional[int] = None
    keyword_rank: Optional[int] = None


class HybridRRFSearcher:
    """
    PostgreSQL pgvector (dense semantic cosine) + tsvector (sparse full-text rank)
    fused via Reciprocal Rank Fusion (RRF) with constant k=60.
    """

    def __init__(self, db_url: str = settings.DATABASE_URL, rrf_k: int = 60):
        self.db_url = db_url
        self.rrf_k = rrf_k
        self._pool: Optional[asyncpg.Pool] = None

    async def get_pool(self) -> asyncpg.Pool:
        if not self._pool:
            self._pool = await asyncpg.create_pool(self.db_url, min_size=1, max_size=10)
        return self._pool

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None

    def compute_mock_embedding(self, text: str, dim: int = 1536) -> List[float]:
        """Deterministic mock embedding for offline evaluation and testing without API costs."""
        import hashlib
        import numpy as np
        
        # Hash text words to pseudo-random uniform distribution and normalize
        tokens = text.lower().split()
        vec = np.zeros(dim, dtype=np.float32)
        for i, token in enumerate(tokens):
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            idx = h % dim
            sign = 1.0 if ((h >> 4) & 1) == 0 else -1.0
            vec[idx] += sign * (1.0 / (1.0 + math.log(i + 1)))
        
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        else:
            vec[0] = 1.0
        return vec.tolist()

    async def search(
        self,
        query: str,
        query_vector: Optional[List[float]] = None,
        top_k: int = 3,
        candidate_limit: int = 20
    ) -> List[RunbookRecord]:
        """
        Executes hybrid search across pgvector and PostgreSQL tsvector, fusing ranks using RRF.
        """
        if query_vector is None:
            query_vector = self.compute_mock_embedding(query)

        try:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                # 1. Semantic Vector Search (Cosine Similarity)
                # Formats vector as string '[0.1, 0.2, ...]' for pgvector
                vector_str = f"[{','.join(f'{x:.6f}' for x in query_vector)}]"
                
                vector_query = """
                    SELECT id, 1 - (embedding <=> $1::vector) as similarity
                    FROM runbooks
                    ORDER BY embedding <=> $1::vector ASC
                    LIMIT $2;
                """
                vector_results = await conn.fetch(vector_query, vector_str, candidate_limit)
                
                # 2. Sparse Text Search (tsvector + plainto_tsquery)
                keyword_query = """
                    SELECT id, ts_rank_cd(search_vector, plainto_tsquery('english', $1)) as text_rank
                    FROM runbooks
                    WHERE search_vector @@ plainto_tsquery('english', $1)
                    ORDER BY text_rank DESC
                    LIMIT $2;
                """
                keyword_results = await conn.fetch(keyword_query, query, candidate_limit)
                
                # 3. Reciprocal Rank Fusion (RRF)
                # RRF Score = SUM( 1 / (k + rank) )
                rrf_scores: Dict[str, Dict[str, Any]] = {}

                for rank, row in enumerate(vector_results, start=1):
                    doc_id = row["id"]
                    if doc_id not in rrf_scores:
                        rrf_scores[doc_id] = {"rrf": 0.0, "vector_rank": rank, "keyword_rank": None}
                    rrf_scores[doc_id]["rrf"] += 1.0 / (self.rrf_k + rank)
                    rrf_scores[doc_id]["vector_rank"] = rank

                for rank, row in enumerate(keyword_results, start=1):
                    doc_id = row["id"]
                    if doc_id not in rrf_scores:
                        rrf_scores[doc_id] = {"rrf": 0.0, "vector_rank": None, "keyword_rank": rank}
                    rrf_scores[doc_id]["rrf"] += 1.0 / (self.rrf_k + rank)
                    rrf_scores[doc_id]["keyword_rank"] = rank

                if not rrf_scores:
                    return []

                # Sort documents by fused RRF score descending
                sorted_doc_ids = sorted(
                    rrf_scores.keys(),
                    key=lambda doc_id: rrf_scores[doc_id]["rrf"],
                    reverse=True
                )[:top_k]

                # Fetch full record details for top results
                records_query = """
                    SELECT id, title, service, severity, symptoms, root_causes,
                           diagnostic_steps, remediation_steps, risk_level, requires_approval
                    FROM runbooks
                    WHERE id = ANY($1::varchar[])
                """
                records_data = await conn.fetch(records_query, sorted_doc_ids)
                data_lookup = {r["id"]: r for r in records_data}

                final_runbooks: List[RunbookRecord] = []
                for doc_id in sorted_doc_ids:
                    if doc_id in data_lookup:
                        raw = data_lookup[doc_id]
                        meta = rrf_scores[doc_id]
                        final_runbooks.append(RunbookRecord(
                            id=raw["id"],
                            title=raw["title"],
                            service=raw["service"],
                            severity=raw["severity"],
                            symptoms=raw["symptoms"],
                            root_causes=raw["root_causes"] or [],
                            diagnostic_steps=raw["diagnostic_steps"] or [],
                            remediation_steps=raw["remediation_steps"] or [],
                            risk_level=raw["risk_level"],
                            requires_approval=raw["requires_approval"],
                            rrf_score=meta["rrf"],
                            vector_rank=meta["vector_rank"],
                            keyword_rank=meta["keyword_rank"]
                        ))

                return final_runbooks

        except Exception as e:
            logger.warning(f"Database hybrid search failed, falling back: {e}")
            return []
