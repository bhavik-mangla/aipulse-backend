"""
Specialized News RSS Crawler with Proxy and Referer support.
Based on the standard RSSCrawler but isolated for news sources.
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

class NewsRSSCrawler(AbstractCrawler):
    """Crawl News RSS/Atom feeds with proxy support."""

    async def crawl(self, url: str, config: dict) -> list[CrawlResult]:
        """
        Parse an RSS/Atom feed and return a CrawlResult per entry.
        """
        start = time.monotonic()
        logger.info("news_rss_crawl_start", url=url)

        user_agent = config.get("user_agent", DEFAULT_USER_AGENT)
        timeout = config.get("timeout", DEFAULT_TIMEOUT)
        use_proxy = config.get("use_proxy", False)
        
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
            "Referer": "https://www.google.com/",
        }

        proxy = None
        if use_proxy:
            # We use an internal import to avoid circular dependency
            from govnotify.sources.proxy_manager import proxy_manager
            # Fetch a few and pick an usable one
            for _ in range(5):
                p = await proxy_manager.get_proxy()
                if p and (p.startswith("http://") or p.startswith("socks5://") or p.startswith("socks4://")):
                    proxy = p
                    break
            
            if proxy:
                logger.info("news_rss_using_proxy", url=url, proxy=proxy)
            else:
                logger.warning("news_rss_no_usable_proxy_found", url=url)

        try:
            client_kwargs = {
                "follow_redirects": True,
                "timeout": timeout,
            }
            if proxy:
                client_kwargs["mounts"] = {
                    "http://": httpx.AsyncHTTPTransport(proxy=proxy),
                    "https://": httpx.AsyncHTTPTransport(proxy=proxy),
                }

            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                feed_content = response.text
                http_status = response.status_code
        except Exception as exc:
            logger.error("news_rss_fetch_error", url=url, error=str(exc))
            return []

        # Parse feed
        parsed = feedparser.parse(feed_content)
        results = []

        feed_title = parsed.feed.get("title", "")

        for entry in parsed.entries:
            # Extract content (summary or full content if available)
            content = ""
            if "content" in entry:
                content = entry.content[0].value
            elif "summary" in entry:
                content = entry.summary
            elif "description" in entry:
                content = entry.description

            results.append(
                CrawlResult(
                    url=entry.link,
                    status_code=http_status,
                    content=content,
                    content_type="text/html",
                    metadata={
                        "title": entry.get("title", ""),
                        "published": entry.get("published", ""),
                        "author": entry.get("author", ""),
                        "feed_title": feed_title,
                    },
                    elapsed_ms=(time.monotonic() - start) * 1000,
                )
            )

        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            "news_rss_crawl_complete",
            url=url,
            entries=len(results),
            elapsed_ms=round(elapsed, 1),
        )

        return results
