"""
Embedding generation for document chunks.
Uses FastEmbed (Qdrant's lightweight library) with BAAI/bge-m3 for dense
embeddings (1024 dimensions, multilingual). Sparse BM25/SPLADE embeddings
are generated alongside for hybrid search.
"""
from typing import Optional

import structlog

from govnotify.config import get_settings
from govnotify.models.document import DocumentChunk

logger = structlog.get_logger(__name__)


class Embedder:
    """Generate dense and sparse embeddings for document chunks."""

    def __init__(self, model_name: str | None = None) -> None:
        settings = get_settings()
        self._model_name = model_name or settings.embedding_model  # BAAI/bge-m3
        self._dense_model = None
        self._sparse_model = None

    def _get_dense_model(self):
        """Lazy-load the dense embedding model."""
        if self._dense_model is None:
            try:
                from fastembed import TextEmbedding
                self._dense_model = TextEmbedding(model_name=self._model_name)
                logger.info("dense_model_loaded", model=self._model_name)
            except Exception as exc:
                logger.error("dense_model_load_failed", error=str(exc))
                raise
        return self._dense_model

    def _get_sparse_model(self):
        """Lazy-load the sparse embedding model (BM25)."""
        if self._sparse_model is None:
            try:
                from fastembed import SparseTextEmbedding
                self._sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
                logger.info("sparse_model_loaded", model="Qdrant/bm25")
            except Exception as exc:
                logger.warning("sparse_model_load_failed", error=str(exc))
                # Sparse embeddings are optional - proceed without
        return self._sparse_model

    async def embed_chunks(
        self, chunks: list[DocumentChunk]
    ) -> list[DocumentChunk]:
        """
        Generate dense and sparse embeddings for a batch of chunks.
        Modifies chunks in-place, setting dense_embedding and sparse_embedding.
        Args:
            chunks: List of DocumentChunk objects (text must be populated).
        Returns:
            The same chunks with embeddings populated.
        """
        if not chunks:
            return chunks

        texts = [chunk.text for chunk in chunks]

        # Dense embeddings (required)
        dense_embeddings = self._embed_dense(texts)
        for chunk, embedding in zip(chunks, dense_embeddings):
            chunk.dense_embedding = embedding

        # Sparse embeddings (optional, for hybrid search)
        sparse_embeddings = self._embed_sparse(texts)
        if sparse_embeddings:
            for chunk, sparse in zip(chunks, sparse_embeddings):
                chunk.sparse_embedding = sparse

        logger.info(
            "embeddings_generated",
            num_chunks=len(chunks),
            has_sparse=sparse_embeddings is not None,
        )
        return chunks

    def _embed_dense(self, texts: list[str]) -> list[list[float]]:
        """Generate dense embeddings for a batch of texts."""
        model = self._get_dense_model()
        embeddings = list(model.embed(texts))
        return [emb.tolist() for emb in embeddings]

    def _embed_sparse(self, texts: list[str]) -> Optional[list[dict]]:
        """Generate sparse BM25 embeddings for a batch of texts."""
        model = self._get_sparse_model()
        if model is None:
            return None
        try:
            results = list(model.embed(texts))
            sparse_embeddings = []
            for sparse in results:
                sparse_embeddings.append({
                    "indices": sparse.indices.tolist(),
                    "values": sparse.values.tolist(),
                })
            return sparse_embeddings
        except Exception as exc:
            logger.warning("sparse_embed_failed", error=str(exc))
            return None

    async def embed_query(self, query: str) -> list[float]:
        """Generate a dense embedding for a search query."""
        embeddings = self._embed_dense([query])
        return embeddings[0]

    async def embed_query_sparse(self, query: str) -> Optional[dict]:
        """Generate a sparse embedding for a search query."""
        sparse = self._embed_sparse([query])
        return sparse[0] if sparse else None
