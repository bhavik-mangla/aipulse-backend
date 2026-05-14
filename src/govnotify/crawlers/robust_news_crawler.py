"""
Robust News Crawler using curl_cffi and trafilatura.
Isolated from core shared logic to bypass aggressive anti-bot protections.
"""
import asyncio
import time
from typing import Optional, Union

import feedparser
import structlog
import trafilatura
from curl_cffi.requests import AsyncSession

from govnotify.crawlers.base import AbstractCrawler, CrawlResult
from govnotify.constants import DEFAULT_USER_AGENT

logger = structlog.get_logger(__name__)

class RobustNewsCrawler(AbstractCrawler):
    """
    Crawler that impersonates a real browser to bypass Cloudflare/Akamai.
    Uses trafilatura for high-quality news extraction.
    """

    def __init__(self):
        # We don't keep a persistent session here to avoid state issues between sources
        pass

    async def _fetch(self, url: str, impersonate: str = "chrome120") -> tuple[Optional[str], int]:
        """Fetch content using browser impersonation."""
        try:
            async with AsyncSession() as session:
                resp = await session.get(
                    url, 
                    impersonate=impersonate, 
                    timeout=30,
                    headers={"Referer": "https://www.google.com/"}
                )
                return resp.text, resp.status_code
        except Exception as exc:
            logger.error("robust_news_fetch_failed", url=url, error=str(exc))
            return None, 0

    async def crawl(self, url: str, config: dict) -> Union[CrawlResult, list[CrawlResult]]:
        """
        Main entry point. If it's an RSS feed, returns a list of results.
        If it's an article URL, returns a single result.
        """
        start = time.monotonic()
        
        # Determine if it's an RSS feed based on URL or config
        is_rss = any(ext in url.lower() for ext in [".rss", ".cms", "/rss"]) or config.get("is_rss", False)
        
        content, status = await self._fetch(url)
        if not content:
            return [] if is_rss else CrawlResult(url=url, status_code=status, content="", content_type="text/plain")

        if is_rss:
            # Parse RSS feed
            parsed = feedparser.parse(content)
            results = []
            feed_title = parsed.feed.get("title", "")
            
            for entry in parsed.entries:
                # We only return metadata for RSS entries; content is fetched later via extract()
                results.append(
                    CrawlResult(
                        url=entry.link,
                        status_code=status,
                        content=entry.get("summary", "") or entry.get("description", ""),
                        content_type="text/html",
                        metadata={
                            "title": entry.get("title", ""),
                            "published": entry.get("published", ""),
                            "author": entry.get("author", ""),
                            "feed_title": feed_title,
                        },
                        elapsed_ms=(time.monotonic() - start) * 1000
                    )
                )
            return results
        else:
            # Single article extraction
            text = trafilatura.extract(content, include_comments=False, include_tables=True)
            return CrawlResult(
                url=url,
                status_code=status,
                content=text or "",
                content_type="text/markdown",
                metadata={},
                elapsed_ms=(time.monotonic() - start) * 1000
            )

    async def extract(self, url: str) -> Optional[str]:
        """Convenience method for full-text extraction."""
        result = await self.crawl(url, {"is_rss": False})
        if isinstance(result, CrawlResult):
            return result.content
        return None
