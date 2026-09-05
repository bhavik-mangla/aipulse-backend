"""
Processed document and chunk models.
Defines schemas for documents after processing (enrichment, classification) and for document chunks optimized for retrieval.
"""
from __future__ import annotations

from datetime import datetime
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
    image_url: Optional[str] = Field(default=None, description="URL to a representative image")
    image_search_query: Optional[str] = Field(default=None, description="LLM-generated query for finding an image")

    # Classification
    categories: list[NoticeCategory] = Field(default_factory=list)
    primary_category: NoticeCategory = NoticeCategory.OTHER
    regions: list[str] = Field(default_factory=list, description="Relevant states/regions")
    departments: list[str] = Field(default_factory=list, description="Issuing departments")
    impact_tier: str = Field(default="Medium", description="Critical/High/Medium/Low")
    country: str = Field(default="world", description="Feed scope: world, in, us")
    notification_worthy: bool = Field(
        default=False, description="Whether interrupting a reader for this is justified"
    )
    affected_audience: list[str] = Field(default_factory=list, description="Target groups")

    # Extracted entities
    entities: dict[str, list[str]] = Field(
        default_factory=dict,
        description="NER results: {persons: [], organizations: [], dates: [], amounts: [], schemes: []}"
    )

    # Metadata
    notification_number: Optional[str] = None
    ingested_at: Optional[datetime] = None
    published_at: Optional[datetime] = Field(
        default=None, description="When the outlet published the story"
    )
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

