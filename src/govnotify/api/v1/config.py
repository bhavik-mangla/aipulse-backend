"""
Global configuration and metadata endpoints.
Provides centralized constants (audiences, impact tiers, categories) to the frontend.
"""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Response
from pydantic import BaseModel

from govnotify.sources.news_rss_source import NEWS_FEEDS

from govnotify.constants import (
    CATEGORY_EMOJIS,
    CATEGORY_NAMES,
    COUNTRIES,
    DEFAULT_COUNTRY,
    IMPACT_TIERS,
    NewsCategory,
    SOURCE_NAMES,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


class CategoryMetadata(BaseModel):
    id: str
    en: str
    emoji: str = ""


class CountryMetadata(BaseModel):
    code: str
    name: str
    flag: str


class SourceMetadata(BaseModel):
    id: str
    name: str
    country: str


class MetadataResponse(BaseModel):
    countries: list[CountryMetadata]
    default_country: str
    impact_tiers: list[str]
    categories: list[CategoryMetadata]


@router.get("/metadata", response_model=MetadataResponse)
async def get_metadata(response: Response):
    """Get all master data for filters and UI labels."""
    response.headers["Cache-Control"] = "public, s-maxage=86400, stale-while-revalidate=604800"
    categories = [
        CategoryMetadata(
            id=cat.value,
            en=CATEGORY_NAMES["en"].get(cat.value, cat.value.title()),
            emoji=CATEGORY_EMOJIS.get(cat.value, ""),
        )
        for cat in NewsCategory
    ]

    return MetadataResponse(
        countries=[CountryMetadata(**c) for c in COUNTRIES],
        default_country=DEFAULT_COUNTRY,
        impact_tiers=IMPACT_TIERS,
        categories=categories,
    )


@router.get("/sources", response_model=list[SourceMetadata])
async def get_sources(response: Response, country: Optional[str] = None):
    """
    List the outlets we carry, optionally narrowed to one feed scope.

    Read from the registry rather than a name table so this cannot drift from
    what is actually ingested.
    """
    response.headers["Cache-Control"] = "public, s-maxage=86400, stale-while-revalidate=604800"

    sources = [
        SourceMetadata(
            id=feed["id"],
            name=SOURCE_NAMES.get(feed["id"], feed["name"]),
            country=feed["country"],
        )
        for feed in NEWS_FEEDS
    ]
    if country:
        sources = [s for s in sources if s.country == country]
    return sources
