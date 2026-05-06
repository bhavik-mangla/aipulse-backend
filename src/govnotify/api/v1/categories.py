"""
Category listing and statistics endpoints.
GET /categories - list all available categories
GET /categories/{id}/stats - category statistics (notice count, latest date)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from govnotify.api.deps import get_db
from govnotify.constants import NoticeCategory, CATEGORY_DESCRIPTIONS
from govnotify.storage.postgres import CategoryDigestORM, DocumentORM
from govnotify.utils.time import get_utc_now

logger = structlog.get_logger(__name__)
router = APIRouter()


# Response schemas

class CategoryInfo(BaseModel):
    id: str
    name: str
    description: str


class CategoryListResponse(BaseModel):
    categories: list[CategoryInfo]
    total: int


class CategoryStatsResponse(BaseModel):
    category: str
    name: str
    total_documents: int = 0
    documents_today: int = 0
    latest_digest_date: Optional[str] = None
    latest_digest_items: int = 0


# Endpoints

@router.get("", response_model=CategoryListResponse)
async def list_categories():
    """List all available notification categories."""
    categories = [
        CategoryInfo(
            id=cat.value,
            name=cat.value.replace("_", " ").title(),
            description=CATEGORY_DESCRIPTIONS.get(cat.value, ""),
        )
        for cat in NoticeCategory
    ]
    return CategoryListResponse(categories=categories, total=len(categories))


@router.get("/{category_id}/stats", response_model=CategoryStatsResponse)
async def category_stats(
    category_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get statistics for a specific category."""
    # Validate category
    try:
        cat = NoticeCategory(category_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category '{category_id}' not found",
        )

    # Total documents in this category
    total_q = select(func.count(DocumentORM.id)).where(
        DocumentORM.primary_category == category_id,
        DocumentORM.is_duplicate == False,  # noqa: E712
    )
    total_result = await db.execute(total_q)
    total_docs = total_result.scalar() or 0

    # Documents today
    today_start = get_utc_now().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_q = select(func.count(DocumentORM.id)).where(
        DocumentORM.primary_category == category_id,
        DocumentORM.ingested_at >= today_start,
        DocumentORM.is_duplicate == False,  # noqa: E712
    )
    
    try:
        today_result = await db.execute(today_q)
        today_docs = today_result.scalar() or 0
    except Exception:
        today_docs = 0

    # Latest digest
    digest_q = (
        select(CategoryDigestORM)
        .where(CategoryDigestORM.category == category_id)
        .order_by(CategoryDigestORM.date.desc())
        .limit(1)
    )
    digest_result = await db.execute(digest_q)
    latest_digest = digest_result.scalar_one_or_none()

    return CategoryStatsResponse(
        category=category_id,
        name=cat.value.replace("_", " ").title(),
        total_documents=total_docs,
        documents_today=today_docs,
        latest_digest_date=latest_digest.date if latest_digest else None,
        latest_digest_items=latest_digest.item_count if latest_digest else 0,
    )
