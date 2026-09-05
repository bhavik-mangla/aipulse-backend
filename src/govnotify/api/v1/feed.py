"""
Feed and document retrieval endpoints.
Provides the main news feed, search, and individual document details.
"""
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import Select, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from govnotify.api.deps import get_db
from govnotify.constants import (
    DEFAULT_COUNTRY,
    HIDE_BEFORE_DATETIME,
    is_valid_country,
    parse_category,
)
from govnotify.constants import get_source_name
from govnotify.models.document import ProcessedDocument
from govnotify.storage.postgres import DocumentORM

logger = structlog.get_logger(__name__)
router = APIRouter()

# The mobile app asks for 15 but benefits from a wider window, because it
# filters out stories the reader has already seen and would otherwise show a
# near-empty screen. The response reports the size actually applied so clients
# can detect the end of the feed correctly.
MOBILE_PAGE_SIZE = 15
MOBILE_EFFECTIVE_PAGE_SIZE = 60


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
    country: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class FeedResponse(BaseModel):
    items: list[FeedItem]
    # None when the caller opted out of the count with include_total=false.
    total: Optional[int] = None
    page: int
    page_size: int


# Helpers

def map_orm_to_feed_item(doc: DocumentORM) -> FeedItem:
    """Map DocumentORM to FeedItem."""
    return FeedItem(
        id=doc.id,
        source_id=doc.source_id,
        source_name=get_source_name(doc.source_id),
        source_url=doc.source_url,
        fetch_url=doc.fetch_url,
        title=doc.title,
        summary=doc.summary or "",
        image_url=doc.image_url,
        # Tolerates categories stored under the old government taxonomy.
        category=parse_category(doc.primary_category).value,
        impact_level=(doc.impact_tier or "Medium").lower(),
        country=doc.country,
        # Fall back to ingest time for documents stored before publication
        # dates were captured.
        published_at=doc.published_at or doc.ingested_at,
        created_at=doc.ingested_at or datetime.now(timezone.utc),
    )


def resolve_country(code: str) -> str:
    """Fall back to the default scope rather than returning an empty feed."""
    return code if is_valid_country(code) else DEFAULT_COUNTRY


def resolve_page_size(requested: int) -> int:
    """Widen the mobile app's page request; see MOBILE_EFFECTIVE_PAGE_SIZE."""
    return MOBILE_EFFECTIVE_PAGE_SIZE if requested == MOBILE_PAGE_SIZE else requested


def build_feed_query(
    *,
    country: str = DEFAULT_COUNTRY,
    category: Optional[str] = None,
    source_id: Optional[str] = None,
    impact_level: Optional[str] = None,
    on_date: Optional[date_type] = None,
    search: Optional[str] = None,
) -> Select:
    """
    Build the filtered document query shared by the feed and search endpoints.

    Both endpoints previously repeated this block verbatim, which is how the
    date filter came to be accepted by the app but implemented by neither.

    The country filter is always applied. Besides scoping the feed, it is what
    keeps the retired government notices out: those documents have a NULL
    country and so match no scope.
    """
    stmt = select(DocumentORM).where(
        DocumentORM.is_duplicate.is_(False),
        DocumentORM.ingested_at >= HIDE_BEFORE_DATETIME,
        DocumentORM.country == country,
    )

    if category:
        stmt = stmt.where(DocumentORM.primary_category == category)

    if source_id:
        stmt = stmt.where(DocumentORM.source_id == source_id)

    if impact_level == "high_only":
        stmt = stmt.where(DocumentORM.impact_tier.in_(["Critical", "High"]))

    if on_date:
        # Half-open range over the calendar day so the index on the timestamp
        # is still usable, unlike a cast to date.
        start = datetime.combine(on_date, time.min, tzinfo=timezone.utc)
        stmt = stmt.where(
            DocumentORM.ingested_at >= start,
            DocumentORM.ingested_at < start + timedelta(days=1),
        )

    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                DocumentORM.title.ilike(pattern),
                DocumentORM.summary.ilike(pattern),
                DocumentORM.clean_text.ilike(pattern),
            )
        )

    return stmt


async def run_feed_query(
    db: AsyncSession,
    stmt: Select,
    page: int,
    page_size: int,
    include_total: bool,
) -> FeedResponse:
    """Count (optionally), paginate and map a feed query."""
    total = None
    if include_total:
        total = (await db.execute(
            select(func.count()).select_from(stmt.subquery())
        )).scalar() or 0

    stmt = (
        stmt.order_by(desc(DocumentORM.ingested_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    docs = (await db.execute(stmt)).scalars().all()

    return FeedResponse(
        items=[map_orm_to_feed_item(doc) for doc in docs],
        total=total,
        page=page,
        page_size=page_size,
    )


# Endpoints

@router.get("/latest", response_model=FeedResponse)
async def get_latest(
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(MOBILE_PAGE_SIZE, ge=1, le=100),
    country: str = Query(DEFAULT_COUNTRY, description="Feed scope: world, in, us"),
    category: Optional[str] = None,
    source_id: Optional[str] = None,
    impact_level: Optional[str] = None,
    date: Optional[date_type] = Query(None, description="Restrict to one day (YYYY-MM-DD)"),
    include_total: bool = Query(True, description="Set false to skip the count query"),
    db: AsyncSession = Depends(get_db),
):
    """Get the latest documents with filtering and pagination."""
    response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=300"

    stmt = build_feed_query(
        country=resolve_country(country),
        category=category,
        source_id=source_id,
        impact_level=impact_level,
        on_date=date,
    )
    return await run_feed_query(db, stmt, page, resolve_page_size(page_size), include_total)


@router.get("/search", response_model=FeedResponse)
async def search(
    response: Response,
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(MOBILE_PAGE_SIZE, ge=1, le=100),
    country: str = Query(DEFAULT_COUNTRY, description="Feed scope: world, in, us"),
    category: Optional[str] = None,
    source_id: Optional[str] = None,
    impact_level: Optional[str] = None,
    date: Optional[date_type] = Query(None, description="Restrict to one day (YYYY-MM-DD)"),
    include_total: bool = Query(True, description="Set false to skip the count query"),
    db: AsyncSession = Depends(get_db),
):
    """Search documents by title, summary or body text."""
    response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=300"

    stmt = build_feed_query(
        country=resolve_country(country),
        category=category,
        source_id=source_id,
        impact_level=impact_level,
        on_date=date,
        search=q,
    )
    return await run_feed_query(db, stmt, page, resolve_page_size(page_size), include_total)


@router.get("/{document_id}", response_model=ProcessedDocument)
async def get_document(
    document_id: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Get full details of a specific document."""
    response.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=86400"
    doc = await db.get(DocumentORM, document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

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
        primary_category=parse_category(doc.primary_category),
        regions=doc.regions or [],
        departments=doc.departments or [],
        impact_tier=doc.impact_tier or "Medium",
        affected_audience=doc.affected_audience or [],
        country=doc.country or DEFAULT_COUNTRY,
        entities=doc.entities or {},
        notification_number=doc.notification_number,
        ingested_at=doc.ingested_at,
        processed_at=doc.ingested_at or datetime.now(timezone.utc),
        language=doc.language or "en",
        content_hash=doc.content_hash,
        simhash=doc.simhash,
        is_duplicate=doc.is_duplicate,
        duplicate_of=doc.duplicate_of,
        confidence_score=doc.confidence_score or 0.0,
    )
