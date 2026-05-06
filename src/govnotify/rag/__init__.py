"""
RAG engine - Retrieval-Augmented Generation for GovNotify.
Provides:
- Hybrid search (dense + sparse + metadata filtering)
- Reciprocal Rank Fusion (RRF) for combining rankings
- Semantic deduplication (Layer 3, cosine threshold >= 0.92)
- Search interface for API and bot endpoints

V1 uses simple SQL search for the /feed/search endpoint. This module provides the RAG infrastructure for V2 upgrade
and the semantic dedup check used during ingestion.
"""
from __future__ import annotations

import structlog
from qdrant_client import AsyncQdrantClient, models

from govnotify.config import get_settings

logger = structlog.get_logger(__name__)

# Semantic dedup: same category, same week, cosine >= 0.92
SEMANTIC_DEDUP_THRESHOLD = 0.92
RRF_K = 60  # Reciprocal Rank Fusion constant


class RAGEngine:
    """Hybrid retrieval + reranking engine backed by Qdrant."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client: AsyncQdrantClient | None = None
        self._host = settings.qdrant_host
        self._port = settings.qdrant_port
        self._collection = settings.qdrant_collection

    async def _get_client(self) -> AsyncQdrantClient:
        if self._client is None:
            self._client = AsyncQdrantClient(host=self._host, port=self._port)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    # --- Semantic Dedup (Layer 3) ---

    async def check_semantic_duplicate(
        self,
        embedding: list[float],
        category: str,
        *,
        threshold: float = SEMANTIC_DEDUP_THRESHOLD,
        limit: int = 5,
    ) -> tuple[bool, str | None]:
        """
        Check if a document is a semantic duplicate within the same category.
        Searches Qdrant for vectors with cosine similarity >= threshold.
        Returns (is_duplicate, original_doc_id).
        Args:
            embedding: Dense embedding vector (1024-dim BGE-M3).
            category: Primary category to scope the search.
            threshold: Cosine similarity threshold (default 0.92).
            limit: Max candidates to check.
        Returns:
            Tuple of (is_duplicate: bool, duplicate_of: str | None).
        """
        try:
            client = await self._get_client()
            results = await client.query_points(
                collection_name=self._collection,
                query=embedding,
                using="dense",
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="categories",
                            match=models.MatchValue(value=category),
                        )
                    ]
                ),
                limit=limit,
                with_payload=["document_id"],
                score_threshold=threshold,
            )

            if results.points:
                best = results.points[0]
                doc_id = best.payload.get("document_id", "") if best.payload else ""
                logger.info(
                    "semantic_duplicate_found",
                    duplicate_of=doc_id,
                    score=best.score,
                )
                return True, doc_id

            return False, None
        except Exception as exc:
            logger.warning(
                "semantic_dedup_check_failed",
                error=str(exc),
            )
            # Fail open - if Qdrant is down, don't block ingestion
            return False, None

    # --- Hybrid Search ---

    async def hybrid_search(
        self,
        query_embedding: list[float],
        regions: list[str] | None = None,
        categories: list[str] | None = None,
        top_k: int = 50,
    ) -> list[dict]:
        """
        Hybrid dense search with metadata filtering.
        V1 implementation - dense vector search with Qdrant filters.
        V2 will add sparse search + RRF fusion + cross-encoder rerank.
        Args:
            query_embedding: Dense embedding of the query.
            categories: Filter by these categories.
            regions: Filter by these regions.
            top_k: Number of candidates to retrieve.
        Returns:
            List of dicts with document_id, score, and payload data.
        """
        try:
            client = await self._get_client()

            # Build filters
            must_conditions = []
            if categories:
                must_conditions.append(
                    models.FieldCondition(
                        key="categories",
                        match=models.MatchAny(any=categories),
                    )
                )
            if regions:
                must_conditions.append(
                    models.FieldCondition(
                        key="regions",
                        match=models.MatchAny(any=regions),
                    )
                )

            query_filter = (
                models.Filter(must=must_conditions)
                if must_conditions
                else None
            )

            results = await client.query_points(
                collection_name=self._collection,
                using="dense",
                query=query_embedding,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )

            return [
                {
                    "id": str(point.id),
                    "score": point.score,
                    "document_id": point.payload.get("document_id", "") if point.payload else "",
                    "text": point.payload.get("text", "") if point.payload else "",
                    "categories": point.payload.get("categories", []) if point.payload else [],
                    "source_id": point.payload.get("source_id", "") if point.payload else "",
                }
                for point in results.points
            ]

        except Exception as exc:
            logger.error("hybrid_search_failed", error=str(exc))
            return []

    @staticmethod
    def rrf_fuse(*rankings: list[dict], k: int = RRF_K) -> list[dict]:
        """
        Reciprocal Rank Fusion to combine multiple rankings.
        Each ranking is a list of dicts with at minimum an "id" key.
        Returns fused ranking sorted by RRF score descending.
        Formula: rrf_score(d) = sum(1 / (k + rank_i)) for each ranking.
        """
        scores: dict[str, float] = {}
        items: dict[str, dict] = {}

        for ranking in rankings:
            for rank, item in enumerate(ranking):
                doc_id = item.get("id", item.get("document_id", ""))
                scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
                items[doc_id] = item

        fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [
            {**items[doc_id], "rrf_score": score}
            for doc_id, score in fused
        ]
