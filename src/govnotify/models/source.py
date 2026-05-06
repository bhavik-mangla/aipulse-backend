"""
Source and raw document models.
Defines the schema for data sources and the raw documents fetched from them.
"""
import hashlib
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl

from govnotify.constants import NoticeCategory


class SourceType(str, Enum):
    """Types of data sources supported by the system."""
    RSS = "rss"
    WEB_SCRAPE = "web_scrape"
    PDF = "pdf"
    API = "api"
    EMAIL = "email"


class SourceConfig(BaseModel):
    """Configuration for a data source. Stored in DB, drives crawling."""
    id: str = Field(description="Unique source identifier, e.g. 'pib_press_releases'")
    name: str = Field(description="Human-readable name")
    source_type: SourceType
    url: HttpUrl = Field(description="Base URL or RSS feed URL")
    schedule_cron: str = Field(default="0 */12 * * *")
    enabled: bool = True
    region_tags: list[str] = Field(
        default_factory=list, description="Default regions"
    )
    language: str = Field(default="en", description="Default language")
    crawler_class: str = Field(
        description="Fully qualified class name of crawler to use"
    )
    crawler_config: dict = Field(
        default_factory=dict, description="Crawler-specific configuration"
    )
    rate_limit_rpm: int = Field(default=30, description="Max requests per minute")
    last_fetched_at: Optional[datetime] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "pib_press_releases",
                    "name": "PIB Press Releases",
                    "source_type": "rss",
                    "url": "https://pib.gov.in/rss/pib_rss.aspx",
                    "language": "en",
                    "crawler_class": "govnotify.crawlers.rss_crawler.RSSCrawler",
                }
            ]
        }
    }


class RawDocument(BaseModel):
    """Raw document as fetched from a source, before processing."""
    source_id: str
    source_url: HttpUrl
    fetch_url: HttpUrl = Field(description="Actual URL this doc was fetched from")
    title: str
    raw_content: str = Field(description="Raw text/HTML/PDF-text content")
    content_type: str = Field(description="MIME type: text/html, application/pdf, text/plain")
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    language: str = Field(default="en")
    content_hash: str = Field(
        default="", description="SHA-256 of raw_content for exact dedup"
    )
    metadata: dict = Field(
        default_factory=dict, description="Source-specific metadata"
    )

    def compute_content_hash(self) -> str:
        """Compute and store SHA-256 hash of normalized raw_content for deduplication."""
        # Normalize: lowercase and collapse whitespace
        normalized = " ".join(self.raw_content.lower().split())
        self.content_hash = hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest()
        return self.content_hash
