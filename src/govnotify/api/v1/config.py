"""
Global configuration and metadata endpoints.
Provides centralized constants (audiences, impact tiers, categories) to the frontend.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Response
from pydantic import BaseModel

from govnotify.constants import (
    AUDIENCES,
    IMPACT_TIERS,
    NoticeCategory,
    CATEGORY_NAMES_HI,
    SOURCE_NAMES,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


class CategoryMetadata(BaseModel):
    id: str
    en: str
    hi: str


class SourceMetadata(BaseModel):
    id: str
    name: str


class MetadataResponse(BaseModel):
    audiences: list[str]
    impact_tiers: list[str]
    categories: list[CategoryMetadata]


@router.get("/metadata", response_model=MetadataResponse)
async def get_metadata(response: Response):
    """Get all master data for filters and UI labels."""
    response.headers["Cache-Control"] = "public, s-maxage=86400, stale-while-revalidate=604800"
    categories = [
        CategoryMetadata(
            id=cat.value,
            en=cat.value.replace("_", " ").title(),
            hi=CATEGORY_NAMES_HI.get(cat.value, cat.value),
        )
        for cat in NoticeCategory
    ]
    
    return MetadataResponse(
        audiences=AUDIENCES,
        impact_tiers=IMPACT_TIERS,
        categories=categories
    )


@router.get("/sources", response_model=list[SourceMetadata])
async def get_sources(response: Response):
    """Get all human-readable source names."""
    response.headers["Cache-Control"] = "public, s-maxage=86400, stale-while-revalidate=604800"
    return [SourceMetadata(id=k, name=v) for k, v in SOURCE_NAMES.items()]
