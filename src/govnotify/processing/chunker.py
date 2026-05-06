"""
Semantic text chunking for RAG retrieval.
Splits documents into chunks at semantic paragraph boundaries with configurable size (default 512 tokens) and overlap (64 tokens).
Each chunk carries the parent document summary as context.
"""
import re
import uuid
import structlog

from govnotify.config import get_settings
from govnotify.models.document import DocumentChunk

logger = structlog.get_logger(__name__)


class Chunker:
    """Split documents into retrieval-optimized chunks."""

    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> None:
        settings = get_settings()
        self.chunk_size = chunk_size or settings.rag_chunk_size
        self.chunk_overlap = chunk_overlap or settings.rag_chunk_overlap
        # Approximate: 1 token = 4 chars (conservative for English)
        self._chars_per_token = 4

    @property
    def _max_chars(self) -> int:
        return self.chunk_size * self._chars_per_token

    @property
    def _overlap_chars(self) -> int:
        return self.chunk_overlap * self._chars_per_token

    def chunk_document(
        self,
        document_id: str,
        text: str,
        summary_context: str = "",
        categories: list[str] | None = None,
        regions: list[str] | None = None,
        departments: list[str] | None = None,
        ingested_at=None,
        source_id: str = "",
        language: str = "en"
    ) -> list[DocumentChunk]:
        """
        Split text into semantic chunks with metadata.
        Strategy:
        1. Split text into paragraphs (semantic boundaries).
        2. Merge short paragraphs until chunk size is reached.
        3. Apply overlap from the end of the previous chunk.
        Args:
            document_id: Parent document UUID.
            text: Full document text.
            summary_context: Parent document summary.
            categories: Document categories for metadata.
            regions: Document regions for metadata.
            departments: Document departments for metadata.
            source_id: Source identifier.
        Returns:
            List of DocumentChunk objects.
        """
        if not text or not text.strip():
            return []

        # Split into semantic paragraphs
        paragraphs = self._split_paragraphs(text)

        # Merge paragraphs into chunks
        raw_chunks = self._merge_into_chunks(paragraphs)
        if not raw_chunks:
            return []

        # Build DocumentChunk objects
        chunks: list[DocumentChunk] = []
        for i, chunk_text in enumerate(raw_chunks):
            chunk = DocumentChunk(
                id=str(uuid.uuid4()),
                document_id=document_id,
                chunk_index=i,
                text=chunk_text,
                summary_context=summary_context,
                categories=categories or [],
                regions=regions or [],
                departments=departments or [],
                source_id=source_id,
                language=language,
                ingested_at=ingested_at,
            )
            chunks.append(chunk)

        logger.debug(
            "chunking_complete",
            document_id=document_id,
            num_chunks=len(chunks),
            avg_chars=sum(len(c.text) for c in chunks) // len(chunks) if chunks else 0,
        )
        return chunks

    def _split_paragraphs(self, text: str) -> list[str]:
        """
        Split text into semantic paragraphs.
        Uses double newline as primary boundary, single newline as secondary.
        """
        # Split on double newlines (paragraph boundaries)
        paragraphs = re.split(r"\n\s*\n", text)
        
        # Further split very long paragraphs on single newlines or sentence boundaries
        result: list[str] = []
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            if len(para) > self._max_chars:
                # Split on sentence boundaries within the paragraph
                sentences = re.split(r"(?<=[.!?])\s+", para)
                result.extend(s.strip() for s in sentences if s.strip())
            else:
                result.append(para)
        return result

    def _merge_into_chunks(self, paragraphs: list[str]) -> list[str]:
        """
        Merge paragraphs into chunks respecting size and overlap.
        """
        if not paragraphs:
            return []

        chunks: list[str] = []
        current_parts: list[str] = []
        current_len = 0

        for para in paragraphs:
            para_len = len(para)

            if para_len > self._max_chars:
                # If a single paragraph exceeds max, force-split it
                # Flush current buffer
                if current_parts:
                    chunks.append("\n\n".join(current_parts))
                    current_parts = []
                    current_len = 0
                
                # Force-split the long paragraph
                for i in range(0, para_len, self._max_chars - self._overlap_chars):
                    chunk_text = para[i : i + self._max_chars]
                    if chunk_text.strip():
                        chunks.append(chunk_text.strip())
                continue

            new_len = current_len + para_len + (2 if current_parts else 0)
            
            # Check if adding this paragraph exceeds the limit
            if new_len > self._max_chars and current_parts:
                # Flush current chunk
                chunks.append("\n\n".join(current_parts))
                
                # Apply overlap: keep tail of previous chunk
                overlap_text = self._get_overlap(current_parts)
                current_parts = [overlap_text] if overlap_text else []
                current_len = len(overlap_text)
                
            current_parts.append(para)
            current_len += para_len + (2 if len(current_parts) > 1 else 0)

        # Flush remaining
        if current_parts:
            chunks.append("\n\n".join(current_parts))
            
        return chunks

    def _get_overlap(self, parts: list[str]) -> str:
        """Get the overlap text from the end of the current chunk parts."""
        if not parts:
            return ""
            
        combined = "\n\n".join(parts)
        if len(combined) <= self._overlap_chars:
            return combined
            
        # Take the last overlap_chars characters
        overlap = combined[-self._overlap_chars:]
        
        # Try to start at a word boundary
        space_idx = overlap.find(" ")
        if space_idx > 0 and space_idx < len(overlap) // 2:
            overlap = overlap[space_idx + 1:]
            
        return overlap
