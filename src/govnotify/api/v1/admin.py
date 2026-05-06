"""
Admin endpoints - monitoring, source management, digest regeneration.
All endpoints require authentication (V1: any authenticated user).
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from govnotify.api.deps import get_db, require_admin
from govnotify.storage.postgres import (
    CategoryDigestORM,
    DocumentORM,
    SourceORM,
    UserORM,
)
from govnotify.utils.time import get_today_str, get_utc_now

logger = structlog.get_logger(__name__)
router = APIRouter()


# Response schemas

class SourceStatusResponse(BaseModel):
    id: str
    name: str
    source_type: str
    url: str
    enabled: bool
    schedule_cron: str
    last_fetched_at: Optional[datetime] = None


class SourcesListResponse(BaseModel):
    sources: list[SourceStatusResponse]
    total: int


class SystemStatsResponse(BaseModel):
    total_users: int = 0
    active_users: int = 0
    total_sources: int = 0
    total_documents: int = 0
    enabled_sources: int = 0
    digests_generated_today: int = 0
    timestamp: datetime = Field(
        default_factory=get_utc_now
    )


class HealthComponentStatus(BaseModel):
    name: str
    status: str  # "ok" or "error"
    detail: str = ""


class HealthResponse(BaseModel):
    status: str  # "ok" or "degraded"
    components: list[HealthComponentStatus]


class TriggerResponse(BaseModel):
    message: str
    source_id: str


class RegenerateResponse(BaseModel):
    message: str
    date: str


# Endpoints

@router.get("/sources", response_model=SourcesListResponse)
async def list_sources(
    _admin: Annotated[UserORM, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
):
    """List all data sources and their status."""
    result = await db.execute(select(SourceORM))
    sources = result.scalars().all()
    
    return SourcesListResponse(
        sources=[
            SourceStatusResponse(
                id=s.id,
                name=s.name,
                source_type=s.source_type,
                url=str(s.url),
                enabled=s.enabled,
                last_fetched_at=s.last_fetched_at,
                schedule_cron=s.schedule_cron or "0 */12 * * *"
            )
            for s in sources
        ],
        total=len(sources)
    )


@router.post("/sources/{source_id}/trigger", response_model=TriggerResponse)
async def trigger_ingestion(
    source_id: str,
    _admin: Annotated[UserORM, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger ingestion for a source."""
    result = await db.execute(
        select(SourceORM).where(SourceORM.id == source_id)
    )
    source = result.scalar_one_or_none()
    
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
        
    logger.info("manual_ingestion_triggered", source_id=source_id)
    
    from govnotify.tasks.ingest_tasks import ingest_single_source
    ingest_single_source.delay(source_id)
    
    return TriggerResponse(
        message=f"Ingestion triggered for source '{source.name}'",
        source_id=source_id
    )


@router.post("/digests/regenerate", response_model=RegenerateResponse)
async def regenerate_digests(
    _admin: Annotated[UserORM, Depends(require_admin)],
):
    """Re-generate today's category digests."""
    today = get_today_str()
    logger.info("digest_regeneration_triggered", date=today)
    
    from govnotify.tasks.digest_tasks import generate_all_category_digests
    generate_all_category_digests.delay(today)
    
    return RegenerateResponse(
        date=today,
        message="Digest regeneration queued"
    )


@router.get("/stats", response_model=SystemStatsResponse)
async def system_stats(
    _admin: Annotated[UserORM, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
):
    """Get system-wide statistics."""
    today = get_today_str()
    
    total_users = (await db.execute(select(func.count(UserORM.id)))).scalar() or 0
    active_users = (await db.execute(
        select(func.count(UserORM.id)).where(UserORM.is_active == True) # noqa: E712
    )).scalar() or 0
    
    total_docs = (await db.execute(select(func.count(DocumentORM.id)))).scalar() or 0
    total_sources = (await db.execute(select(func.count(SourceORM.id)))).scalar() or 0
    enabled_sources = (await db.execute(
        select(func.count(SourceORM.id)).where(SourceORM.enabled == True) # noqa: E712
    )).scalar() or 0
    
    digests_today = (await db.execute(
        select(func.count(CategoryDigestORM.id)).where(CategoryDigestORM.date == today)
    )).scalar() or 0
    
    return SystemStatsResponse(
        total_users=total_users,
        active_users=active_users,
        total_sources=total_sources,
        total_documents=total_docs,
        enabled_sources=enabled_sources,
        digests_generated_today=digests_today
    )


@router.get("/health", response_model=HealthResponse)
async def health_check(
    _admin: Annotated[UserORM, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
):
    """Health check for all system components."""
    components: list[HealthComponentStatus] = []
    overall = "ok"
    
    # PostgreSQL
    try:
        await db.execute(select(func.now()))
        components.append(HealthComponentStatus(name="postgres", status="ok"))
    except Exception as e:
        components.append(HealthComponentStatus(name="postgres", status="error", detail=str(e)))
        overall = "degraded"
        
    # Qdrant
    try:
        from govnotify.storage.qdrant import get_qdrant_client, health_check as qdrant_hc
        client = get_qdrant_client()
        if qdrant_hc(client):
            components.append(HealthComponentStatus(name="qdrant", status="ok"))
        else:
            components.append(HealthComponentStatus(name="qdrant", status="error", detail="health check failed"))
            overall = "degraded"
    except Exception as e:
        components.append(HealthComponentStatus(name="qdrant", status="error", detail=str(e)))
        overall = "degraded"
        
    # Redis
    try:
        from govnotify.storage.redis_store import RedisStore
        store = RedisStore()
        if await store.health_check():
            components.append(HealthComponentStatus(name="redis", status="ok"))
        else:
            components.append(HealthComponentStatus(name="redis", status="error", detail="ping failed"))
            overall = "degraded"
        await store.close()
    except Exception as e:
        components.append(HealthComponentStatus(name="redis", status="error", detail=str(e)))
        overall = "degraded"
        
    return HealthResponse(status=overall, components=components)
