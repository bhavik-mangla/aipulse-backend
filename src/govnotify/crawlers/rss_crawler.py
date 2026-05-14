"""
RSS Crawler using feedparser.
Parses RSS/Atom feeds into structured CrawlResult objects.
Zero web-scraping needed - feeds provide structured data directly.
Uses httpx for the HTTP request (async, follows redirects, respects proxy)
and feedparser for XML/RSS parsing.
"""
import time
from typing import Optional

import feedparser
import httpx
import structlog

from govnotify.crawlers.base import AbstractCrawler, CrawlResult
from govnotify.constants import DEFAULT_USER_AGENT

logger = structlog.get_logger(__name__)

DEFAULT_TIMEOUT = 30.0


class RSSCrawler(AbstractCrawler):
    """Crawl RSS/Atom feeds using httpx + feedparser."""

    async def crawl(self, url: str, config: dict) -> list[CrawlResult]:
        """
        Parse an RSS/Atom feed and return a CrawlResult per entry.
        Uses httpx to fetch the feed (async, handles redirects/proxy)
        then feedparser to parse the XML content.
        Args:
            url: RSS feed URL.
            config: Optional config. Supports:
                - user_agent (str): Custom User-Agent header.
                - timeout (float): Request timeout in seconds.
        Returns:
            List of CrawlResult, one per feed entry.
        """
        start = time.monotonic()
        logger.info("rss_crawl_start", url=url)

        # Fetch with httpx (async, follows redirects)
        user_agent = config.get("user_agent", DEFAULT_USER_AGENT)
        timeout = config.get("timeout", DEFAULT_TIMEOUT)
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }

        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=timeout
            ) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                feed_content = response.text
                http_status = response.status_code
        except httpx.HTTPError as exc:
            logger.error("rss_fetch_error", url=url, error=str(exc))
            return []

        # Parse the feed content with feedparser
        feed = feedparser.parse(feed_content)

        # feedparser doesn't raise on parse errors - check bozo flag
        if feed.bozo and not feed.entries:
            logger.error(
                "rss_parse_error",
                url=url,
                bozo_exception=str(feed.bozo_exception),
            )
            return []

        elapsed = (time.monotonic() - start) * 1000
        results: list[CrawlResult] = []

        for entry in feed.entries:
            # Extract content: prefer summary, fall back to description
            content = (
                entry.get("summary", "")
                or entry.get("description", "")
            )

            # If content is a list of content objects (Atom), take the first
            if isinstance(content, list) and content:
                content = content[0].get("value", "") if isinstance(content[0], dict) else str(content[0])

            # Collect links from entry
            links: list[str] = []
            if hasattr(entry, "links"):
                links = [
                    link.get("href", "")
                    for link in entry.links
                    if link.get("href")
                ]

            results.append(
                CrawlResult(
                    url=entry.get("link", url),
                    status_code=http_status,
                    content=content,
                    content_type="text/html",
                    links=links,
                    metadata={
                        "title": entry.get("title", ""),
                        "published": entry.get("published", ""),
                        "author": entry.get("author", ""),
                        "feed_title": feed.feed.get("title", ""),
                    },
                    elapsed_ms=elapsed,
                )
            )

        logger.info(
            "rss_crawl_complete",
            url=url,
            entries=len(results),
            elapsed_ms=round(elapsed, 1),
        )

        return results
