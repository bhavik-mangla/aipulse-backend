"""
Processed document and chunk models.
Defines schemas for documents after processing (enrichment, classification) and for document chunks optimized for retrieval.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl

from govnotify.constants import NoticeCategory


class ProcessedDocument(BaseModel):
    """A fully processed, enriched government notice."""
    id: str = Field(description="UUID")
    source_id: str
    source_url: HttpUrl
    fetch_url: Optional[HttpUrl] = None
    title: str
    clean_text: str = Field(description="Cleaned, normalized text content")
    summary: str = Field(default="", description="AI-generated plain-language summary")
    summary_hindi: str = Field(default="", description="Hindi translation of summary")

    # Classification
    categories: list[NoticeCategory] = Field(default_factory=list)
    primary_category: NoticeCategory = NoticeCategory.OTHER
    regions: list[str] = Field(default_factory=list, description="Relevant states/regions")
    departments: list[str] = Field(default_factory=list, description="Issuing departments")
    impact_tier: str = Field(default="Medium", description="Critical/High/Medium/Low")
    affected_audience: list[str] = Field(default_factory=list, description="Target groups")

    # Extracted entities
    entities: dict[str, list[str]] = Field(
        default_factory=dict,
        description="NER results: {persons: [], organizations: [], dates: [], amounts: [], schemes: []}"
    )

    # Metadata
    notification_number: Optional[str] = None
    ingested_at: Optional[datetime] = None
    processed_at: datetime = Field(default_factory=datetime.utcnow)
    language: str = Field(default="en")

    # Dedup
    content_hash: str
    simhash: Optional[str] = None
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None

    # Quality
    confidence_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Processing confidence"
    )


class DocumentChunk(BaseModel):
    """A chunk of a processed document, optimized for retrieval."""
    id: str
    document_id: str
    chunk_index: int
    text: str = Field(description="Chunk text content")
    summary_context: str = Field(
        default="", description="Parent document summary for context"
    )

    # Embeddings stored in Qdrant, not serialized by default
    dense_embedding: Optional[list[float]] = Field(default=None, exclude=True)
    sparse_embedding: Optional[dict] = Field(default=None, exclude=True) # {indices: [], values: []}

    # Metadata for filtering in Qdrant
    categories: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    ingested_at: Optional[datetime] = None
    source_id: str = ""
    language: str = "en"
