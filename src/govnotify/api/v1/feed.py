"""
Feed and document retrieval endpoints.
Provides the main news feed, search, and individual document details.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from govnotify.api.deps import get_db
from govnotify.constants import NoticeCategory, HIDE_BEFORE_DATETIME, get_source_name
from govnotify.storage.postgres import DocumentORM
from govnotify.models.document import ProcessedDocument

logger = structlog.get_logger(__name__)
router = APIRouter()


# Response schemas

class FeedItem(BaseModel):
    """Abbreviated document model for feed listing."""
    id: str
    source_id: str
    source_name: str
    source_url: str
    fetch_url: Optional[str] = None
    title: str
    summary: str
    image_url: Optional[str] = None
    category: str
    impact_level: str
    affected_audience: list[str]
    published_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class FeedResponse(BaseModel):
    items: list[FeedItem]
    total: int
    page: int
    page_size: int


# Helpers

def map_orm_to_feed_item(doc: DocumentORM) -> FeedItem:
    """Map DocumentORM to FeedItem Pydantic model."""
    return FeedItem(
        id=doc.id,
        source_id=doc.source_id,
        source_name=get_source_name(doc.source_id),
        source_url=doc.source_url,
        fetch_url=doc.fetch_url,
        title=doc.title,
        summary=doc.summary or "",
        image_url=doc.image_url,
        category=doc.primary_category or "other",
        impact_level=(doc.impact_tier or "Medium").lower(),
        affected_audience=doc.affected_audience or [],
        published_at=doc.ingested_at,  # Using ingested_at as published_at for now
        created_at=doc.ingested_at or datetime.utcnow(),
    )


# Endpoints

@router.get("/latest", response_model=FeedResponse)
async def get_latest(
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=1, le=100),
    feed_type: str = Query("all"),  # news, official, all
    category: Optional[str] = None,
    source_id: Optional[str] = None,
    audience: Optional[str] = None,
    impact_level: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get the latest documents with filtering and pagination."""
    stmt = select(DocumentORM).where(
        DocumentORM.is_duplicate == False,
        DocumentORM.ingested_at >= HIDE_BEFORE_DATETIME
    )

    # Apply filters
    if category:
        stmt = stmt.where(DocumentORM.primary_category == category)
    
    if source_id:
        stmt = stmt.where(DocumentORM.source_id == source_id)
    
    if audience:
        stmt = stmt.where(DocumentORM.affected_audience.contains([audience]))
    
    if impact_level == "high_only":
        stmt = stmt.where(DocumentORM.impact_tier.in_(["Critical", "High"]))

    if feed_type == "news":
        stmt = stmt.where(DocumentORM.source_id.contains("top_stories"))
    elif feed_type == "official":
        stmt = stmt.where(~DocumentORM.source_id.contains("top_stories"))

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_res = await db.execute(count_stmt)
    total = total_res.scalar() or 0

    # Paginate
    stmt = stmt.order_by(desc(DocumentORM.ingested_at))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    
    result = await db.execute(stmt)
    docs = result.scalars().all()

    items = [map_orm_to_feed_item(doc) for doc in docs]
    
    return FeedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/search", response_model=FeedResponse)
async def search(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=1, le=100),
    feed_type: str = Query("all"),
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Search documents by title or summary."""
    search_filter = or_(
        DocumentORM.title.ilike(f"%{q}%"),
        DocumentORM.summary.ilike(f"%{q}%"),
        DocumentORM.clean_text.ilike(f"%{q}%")
    )
    
    stmt = select(DocumentORM).where(
        DocumentORM.is_duplicate == False,
        DocumentORM.ingested_at >= HIDE_BEFORE_DATETIME,
        search_filter
    )

    if category:
        stmt = stmt.where(DocumentORM.primary_category == category)

    if feed_type == "news":
        stmt = stmt.where(DocumentORM.source_id.contains("top_stories"))
    elif feed_type == "official":
        stmt = stmt.where(~DocumentORM.source_id.contains("top_stories"))

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_res = await db.execute(count_stmt)
    total = total_res.scalar() or 0

    # Paginate
    stmt = stmt.order_by(desc(DocumentORM.ingested_at))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    
    result = await db.execute(stmt)
    docs = result.scalars().all()

    items = [map_orm_to_feed_item(doc) for doc in docs]
    
    return FeedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/{document_id}", response_model=ProcessedDocument)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get full details of a specific document."""
    doc = await db.get(DocumentORM, document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # Return as ProcessedDocument
    return ProcessedDocument(
        id=doc.id,
        source_id=doc.source_id,
        source_url=doc.source_url,
        fetch_url=doc.fetch_url,
        title=doc.title,
        clean_text=doc.clean_text or "",
        summary=doc.summary or "",
        summary_hindi=doc.summary_hindi or "",
        image_url=doc.image_url,
        image_search_query=doc.image_search_query,
        categories=doc.categories or [],
        primary_category=NoticeCategory(doc.primary_category) if doc.primary_category else NoticeCategory.OTHER,
        regions=doc.regions or [],
        departments=doc.departments or [],
        impact_tier=doc.impact_tier or "Medium",
        affected_audience=doc.affected_audience or [],
        entities=doc.entities or {},
        notification_number=doc.notification_number,
        ingested_at=doc.ingested_at,
        processed_at=doc.ingested_at or datetime.utcnow(), # fallback
        language=doc.language or "en",
        content_hash=doc.content_hash,
        simhash=doc.simhash,
        is_duplicate=doc.is_duplicate,
        duplicate_of=doc.duplicate_of,
        confidence_score=doc.confidence_score or 0.0
    )
