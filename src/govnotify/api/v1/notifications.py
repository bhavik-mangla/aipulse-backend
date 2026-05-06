"""
Digest and feed endpoints.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from govnotify.api.deps import get_current_user, get_db
from govnotify.utils.time import get_utc_now, get_today_str
from govnotify.constants import NoticeCategory, HIDE_BEFORE_DATETIME
from govnotify.storage.postgres import (
    CategoryDigestORM,
    DigestORM,
    DocumentORM,
    UserORM,
)

logger = structlog.get_logger(__name__)
router = APIRouter()



# Response Schemas

class SourcePublicResponse(BaseModel):
    id: str
    name: str

class SourcesPublicListResponse(BaseModel):
    sources: list[SourcePublicResponse]

class NotificationItemResponse(BaseModel):
    document_id: str
    title: str
    summary: str
    summary_hindi: str = ""
    category: str
    source_name: str
    source_url: str
    ingested_at: Optional[datetime] = None
    regions: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    impact_tier: str = "Medium"
    affected_audience: list[str] = Field(default_factory=list)
    relevance_score: float = 0.0


class CategoryDigestResponse(BaseModel):
    id: str
    category: str
    date: str
    items: list[NotificationItemResponse] = Field(default_factory=list)
    summary_text: str = ""
    summary_hindi: str = ""
    item_count: int = 0
    has_updates: bool = True
    no_update_message: str = ""
    generated_at: Optional[datetime] = None


class DigestsListResponse(BaseModel):
    date: str
    digests: list[CategoryDigestResponse]
    total_items: int = 0


class NoticeDetailResponse(BaseModel):
    id: str
    source_id: str
    source_url: str
    fetch_url: Optional[str] = None
    title: str
    clean_text: str
    summary: str = ""
    summary_hindi: str = ""
    primary_category: str = ""
    categories: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    impact_tier: str = "Medium"
    affected_audience: list[str] = Field(default_factory=list)
    ingested_at: Optional[datetime] = None
    language: str = "en"


class FeedSearchResponse(BaseModel):
    items: list[NoticeDetailResponse]
    total: int
    page: int
    page_size: int
    has_more: bool
    query_time_us: float = 0.0


class FeedSearchRequest(BaseModel):
    """Search request model per §12.2."""
    query: Optional[str] = None
    categories: Optional[list[str]] = None
    regions: Optional[list[str]] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class UserDigestHistoryItem(BaseModel):
    id: str
    date: str
    total_items: int
    generated_at: Optional[datetime] = None
    delivery_channel: str = ""
    delivered: bool = False


# Helpers

def _orm_to_digest_response(orm: CategoryDigestORM) -> CategoryDigestResponse:
    items_raw = orm.items or []
    items = []
    for item in items_raw:
        # Extract Hindi summary if it exists in the item JSON
        summary_raw = item.get("summary", "")
        summary_hi = ""
        if summary_raw and summary_raw.strip().startswith("{"):
            try:
                import json
                data = json.loads(summary_raw)
                summary_hi = data.get("quick_take_hindi", "")
            except:
                pass

        items.append(
            NotificationItemResponse(
                document_id=item.get("document_id", ""),
                title=item.get("title", ""),
                summary=summary_raw,
                summary_hindi=summary_hi,
                category=item.get("category", orm.category),
                source_name=item.get("source_name", ""),
                source_url=item.get("source_url", ""),
                ingested_at=item.get("ingested_at"),
                regions=item.get("regions", []),
                departments=item.get("departments", []),
                impact_tier=item.get("impact_tier", "Medium"),
                affected_audience=item.get("affected_audience", []),
                relevance_score=item.get("relevance_score", 0.0)
            )
        )
    
    return CategoryDigestResponse(
        id=str(orm.id),
        category=orm.category,
        date=orm.date,
        items=items,
        summary_text=orm.summary_text or "",
        summary_hindi=orm.summary_hindi or "",
        item_count=orm.item_count or 0,
        has_updates=orm.has_updates if orm.has_updates is not None else True,
        no_update_message="" if orm.has_updates else "No new updates in this category today. We'll keep watching!",
        generated_at=orm.generated_at,
    )


def today_str() -> str:
    return get_today_str()


# Category Digest Endpoints (public)

@router.get("/sources", response_model=SourcesPublicListResponse)
async def list_sources_public(
    db: AsyncSession = Depends(get_db),
):
    """Get list of active sources for filtering (public)."""
    from govnotify.storage.postgres import SourceORM
    result = await db.execute(
        select(SourceORM).where(SourceORM.enabled == True).order_by(SourceORM.name)
    )
    sources = result.scalars().all()
    return SourcesPublicListResponse(
        sources=[SourcePublicResponse(id=s.id, name=s.name) for s in sources]
    )


@router.get("/digests/today", response_model=DigestsListResponse)
async def digests_today(db: AsyncSession = Depends(get_db)):
    """Get all category digests for today."""
    today = today_str()
    result = await db.execute(
        select(CategoryDigestORM).where(CategoryDigestORM.date == today)
    )
    digests = result.scalars().all()
    responses = [_orm_to_digest_response(d) for d in digests]
    total = sum(d.item_count for d in responses)
    return DigestsListResponse(date=today, digests=responses, total_items=total)


@router.get("/digests/today/{category}", response_model=CategoryDigestResponse)
async def digest_today_category(
    category: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a single category digest for today."""
    try:
        NoticeCategory(category)
    except ValueError:
        raise HTTPException(status_code=404, detail="Category not found")
        
    today = today_str()
    result = await db.execute(
        select(CategoryDigestORM).where(
            CategoryDigestORM.category == category,
            CategoryDigestORM.date == today
        )
    )
    orm = result.scalar_one_or_none()
    
    if orm is None:
        # Return empty digest
        return CategoryDigestResponse(
            id=str(uuid.uuid4()),
            category=category,
            date=today,
            has_updates=False,
            no_update_message="No digest generated for this category today."
        )
    return _orm_to_digest_response(orm)


@router.get("/digests/{date}", response_model=DigestsListResponse)
async def digests_by_date(date: str, db: AsyncSession = Depends(get_db)):
    """Get all category digests for a specific date (YYYY-MM-DD)."""
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format, use YYYY-MM-DD"
        )
        
    result = await db.execute(
        select(CategoryDigestORM).where(CategoryDigestORM.date == date)
    )
    digests = result.scalars().all()
    responses = [_orm_to_digest_response(d) for d in digests]
    total = sum(d.item_count for d in responses)
    return DigestsListResponse(date=date, digests=responses, total_items=total)


@router.get("/digests/{date}/{category}", response_model=CategoryDigestResponse)
async def digest_by_date_category(
    date: str,
    category: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a single category digest for a specific date."""
    try:
        NoticeCategory(category)
    except ValueError:
        raise HTTPException(status_code=404, detail="Category not found")
        
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
        
    result = await db.execute(
        select(CategoryDigestORM).where(
            CategoryDigestORM.category == category,
            CategoryDigestORM.date == date
        )
    )
    orm = result.scalar_one_or_none()
    
    if orm is None:
        return CategoryDigestResponse(
            id=str(uuid.uuid4()),
            category=category,
            date=date,
            has_updates=False,
            no_update_message="No digest found for this category and date.",
        )
    return _orm_to_digest_response(orm)


# User Feed Endpoints (authenticated)

@router.get("/feed", response_model=DigestsListResponse)
async def user_feed(
    user: Annotated[UserORM, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's assembled feed - digests for subscribed categories."""
    today = today_str()
    prefs = user.preferences or {}
    subscribed = prefs.get("categories", [])
    
    if not subscribed:
        # Return all categories
        result = await db.execute(
            select(CategoryDigestORM).where(CategoryDigestORM.date == today)
        )
    else:
        result = await db.execute(
            select(CategoryDigestORM).where(
                CategoryDigestORM.date == today,
                CategoryDigestORM.category.in_(subscribed)
            )
        )
        
    digests = result.scalars().all()
    responses = [_orm_to_digest_response(d) for d in digests]
    total = sum(d.item_count for d in responses)
    return DigestsListResponse(date=today, digests=responses, total_items=total)


@router.get("/feed/latest", response_model=FeedSearchResponse)
async def feed_latest(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    source_id: Optional[str] = None,
    impact_level: Optional[str] = Query(None, description="high_only to show Critical/High"),
    audience: Optional[str] = None,
    date: Optional[str] = None, # YYYY-MM-DD
    db: AsyncSession = Depends(get_db),
):
    """Get latest notices, paginated. Optionally filter by category, source, date, impact, audience."""
    filters = [
        DocumentORM.is_duplicate == False, # noqa: E712
        DocumentORM.ingested_at >= HIDE_BEFORE_DATETIME,
    ]
    
    if category:
        filters.append(DocumentORM.primary_category == category)
    if source_id:
        filters.append(DocumentORM.source_id == source_id)
    if impact_level == "high_only":
        filters.append(DocumentORM.impact_tier.in_(["Critical", "High"]))
    elif impact_level:
        filters.append(DocumentORM.impact_tier == impact_level)
    
    if audience:
        filters.append(DocumentORM.affected_audience.contains([audience]))

    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
            # Filter by UTC date of ingestion
            filters.append(func.date(DocumentORM.ingested_at) == target_date)
        except ValueError:
            pass

    query = select(DocumentORM).where(and_(*filters))
    count_query = select(func.count(DocumentORM.id)).where(and_(*filters))
        
    # Count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Paginate and sort by ingested_at DESC
    offset = (page - 1) * page_size
    query = (
        query.order_by(DocumentORM.ingested_at.desc(), DocumentORM.id.desc())
        .limit(page_size)
        .offset(offset)
    )
    
    result = await db.execute(query)
    docs = result.scalars().all()
    
    items = [
        NoticeDetailResponse(
            id=str(doc.id),
            source_id=doc.source_id,
            source_url=str(doc.source_url) if doc.source_url else "",
            fetch_url=doc.fetch_url,
            title=doc.title,
            clean_text=doc.clean_text or "",
            summary=doc.summary or "",
            summary_hindi=doc.summary_hindi or "",
            primary_category=doc.primary_category or "",
            categories=doc.categories or [],
            regions=doc.regions or [],
            departments=doc.departments or [],
            impact_tier=doc.impact_tier or "Medium",
            affected_audience=doc.affected_audience or [],
            ingested_at=doc.ingested_at,
            language=doc.language or "en",
        )
        for doc in docs
    ]
    
    return FeedSearchResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(offset + page_size) < total,
    )


@router.get("/feed/search", response_model=FeedSearchResponse)
async def feed_search(
    q: str = Query("", description="Search query"),
    category: Optional[str] = None,
    source_id: Optional[str] = None,
    impact_level: Optional[str] = Query(None, description="high_only to show Critical/High"),
    audience: Optional[str] = None,
    date: Optional[str] = None, # YYYY-MM-DD
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Search notices by text query."""
    filters = [
        DocumentORM.is_duplicate == False, # noqa: E712
        DocumentORM.ingested_at >= HIDE_BEFORE_DATETIME,
    ]
    
    if q:
        like_pattern = f"%{q}%"
        filters.append(
            (DocumentORM.title.ilike(like_pattern) | DocumentORM.clean_text.ilike(like_pattern))
        )
        
    if category:
        filters.append(DocumentORM.primary_category == category)
    if source_id:
        filters.append(DocumentORM.source_id == source_id)
    if impact_level == "high_only":
        filters.append(DocumentORM.impact_tier.in_(["Critical", "High"]))
    elif impact_level:
        filters.append(DocumentORM.impact_tier == impact_level)
    
    if audience:
        filters.append(DocumentORM.affected_audience.contains([audience]))

    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
            filters.append(func.date(DocumentORM.ingested_at) == target_date)
        except ValueError:
            pass
        
    query = select(DocumentORM).where(and_(*filters))
    count_query = select(func.count(DocumentORM.id)).where(and_(*filters))
    
    # Count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Paginate and sort by ingested_at DESC
    offset = (page - 1) * page_size
    query = (
        query.order_by(DocumentORM.ingested_at.desc(), DocumentORM.id.desc())
        .limit(page_size)
        .offset(offset)
    )
    
    result = await db.execute(query)
    docs = result.scalars().all()
    
    items = [
        NoticeDetailResponse(
            id=str(doc.id),
            source_id=doc.source_id,
            source_url=str(doc.source_url) if doc.source_url else "",
            fetch_url=doc.fetch_url,
            title=doc.title,
            clean_text=doc.clean_text or "",
            summary=doc.summary or "",
            summary_hindi=doc.summary_hindi or "",
            primary_category=doc.primary_category or "",
            categories=doc.categories or [],
            regions=doc.regions or [],
            departments=doc.departments or [],
            impact_tier=doc.impact_tier or "Medium",
            affected_audience=doc.affected_audience or [],
            ingested_at=doc.ingested_at,
            language=doc.language or "en",
        )
        for doc in docs
    ]
    
    return FeedSearchResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(offset + page_size) < total,
    )


@router.get("/feed/history", response_model=list[UserDigestHistoryItem])
async def feed_history(
    user: Annotated[UserORM, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    limit: int = Query(30, ge=1, le=100),
):
    """Get the current user's past digest history."""
    result = await db.execute(
        select(DigestORM)
        .where(DigestORM.user_id == user.id)
        .order_by(DigestORM.generated_at.desc())
        .limit(limit)
    )
    digests = result.scalars().all()
    return [
        UserDigestHistoryItem(
            id=str(d.id),
            date=d.date,
            total_items=d.total_items or 0,
            generated_at=d.generated_at,
            delivery_channel=d.delivery_channel or "",
            delivered=d.delivered or False,
        )
        for d in digests
    ]


@router.get("/feed/{notice_id}", response_model=NoticeDetailResponse)
async def notice_detail(
    notice_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get full detail of a single notice by ID."""
    result = await db.execute(
        select(DocumentORM).where(DocumentORM.id == notice_id)
    )
    doc = result.scalar_one_or_none()
    
    if doc is None:
        raise HTTPException(status_code=404, detail="Notice not found")
        
    return NoticeDetailResponse(
        id=str(doc.id),
        source_id=doc.source_id,
        source_url=str(doc.source_url),
        fetch_url=doc.fetch_url,
        title=doc.title,
        clean_text=doc.clean_text or "",
        summary=doc.summary or "",
        summary_hindi=doc.summary_hindi or "",
        primary_category=doc.primary_category or "",
        categories=doc.categories or [],
        regions=doc.regions or [],
        departments=doc.departments or [],
        impact_tier=doc.impact_tier or "Medium",
        affected_audience=doc.affected_audience or [],
        ingested_at=doc.ingested_at,
        language=doc.language or "en",
    )
