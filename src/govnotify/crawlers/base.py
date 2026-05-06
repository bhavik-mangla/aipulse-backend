"""
Base crawler interfaces and data models.
Defines the AbstractCrawler ABC and CrawlResult model used by all crawler implementations (RSS, Crawl4AI, etc.).
"""
from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field


class CrawlResult(BaseModel):
    """Structured result from crawling a single URL."""
    url: str
    status_code: int
    content: str = Field(description="Extracted text/markdown")
    content_type: str = Field(description="MIME type: text/html, application/pdf, etc.")
    links: list[str] = Field(default_factory=list, description="Discovered links")
    metadata: dict = Field(default_factory=dict, description="Page-specific metadata")
    raw_html: Optional[str] = Field(default=None, description="Original HTML if needed")
    elapsed_ms: float = 0.0


class AbstractCrawler(ABC):
    """Base crawler interface. All crawlers must implement this."""

    @abstractmethod
    async def crawl(self, url: str, config: dict) -> CrawlResult | list[CrawlResult]:
        """
        Crawl a URL and return structured result(s).
        Args:
            url: The URL to crawl.
            config: Crawler-specific configuration dict.
        Returns:
            A single CrawlResult or a list of CrawlResult objects (e.g. RSS feeds).
        """
        pass
