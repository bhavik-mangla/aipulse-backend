"""
News RSS Source using RSSCrawler and Jina AI Reader for content extraction.
"""
import asyncio
from datetime import datetime
from typing import AsyncIterator, Any

import structlog
from pydantic import HttpUrl

from govnotify.crawlers.robust_news_crawler import RobustNewsCrawler
from govnotify.models.source import RawDocument, SourceConfig, SourceType
from govnotify.sources.base import WebScrapeSource
from govnotify.sources.registry import SourceRegistry

logger = structlog.get_logger(__name__)

class NewsRSSSource(WebScrapeSource):
    """Source for news outlets via RSS + Robust Extraction."""

    def __init__(self, config: SourceConfig) -> None:
        super().__init__(config)
        self._crawler = RobustNewsCrawler()

    async def fetch(self, since: datetime | None = None) -> AsyncIterator[RawDocument]:
        """Fetch news articles from RSS and extract full content locally."""
        logger.info("news_fetch_start", source_id=self.source_id, url=str(self._config.url))
        
        # 1. Get entries from RSS
        try:
            results = await self._crawler.crawl(str(self._config.url), {"is_rss": True})
            if not isinstance(results, list):
                logger.error("news_rss_crawl_invalid_response", source_id=self.source_id)
                return
        except Exception as exc:
            logger.error("news_rss_crawl_failed", source_id=self.source_id, error=str(exc))
            return

        # 2. Process each entry
        for entry in results:
            article_url = entry.url
            title = entry.metadata.get("title", "")
            
            if not article_url or not title:
                continue

            # Quick check if duplicate
            doc_placeholder = self.create_raw_document(
                title=title,
                fetch_url=article_url,
                raw_content=title 
            )
            is_dup, _ = await self.check_duplicate(doc_placeholder)
            if is_dup:
                logger.debug("news_skip_duplicate", title=title[:50])
                continue

            # 3. Extract full content locally using browser impersonation
            logger.info("news_extract_content", source_id=self.source_id, url=article_url)
            
            try:
                content = await self._crawler.extract(article_url)
                
                if not content or len(content) < 500:
                    logger.warning("news_extraction_low_quality", url=article_url, length=len(content) if content else 0)
                    # Fallback to RSS summary if substantial
                    rss_summary = entry.content or ""
                    if len(rss_summary) > 200:
                        content = rss_summary
                    else:
                        logger.warning("news_skip_article_no_content", title=title[:50])
                        continue
            except Exception as exc:
                logger.error("news_extraction_failed", url=article_url, error=str(exc))
                continue

            # 4. Create and yield RawDocument
            metadata = entry.metadata.copy()
            metadata["is_news"] = True
            metadata["original_url"] = article_url
            
            doc = self.create_raw_document(
                title=title,
                fetch_url=article_url,
                raw_content=content,
                content_type="text/markdown",
                metadata=metadata
            )
            
            if await self.validate_response(doc):
                yield doc

    async def validate_response(self, doc: RawDocument) -> bool:
        """Validate that the document content is not an error message."""
        base_valid = await super().validate_response(doc)
        if not base_valid:
            return False
            
        content = doc.raw_content.lower()
        error_keywords = [
            "securitycompromiseerror",
            "ddos attack suspected",
            "blocked until",
            "access denied"
        ]
        
        for kw in error_keywords:
            if kw in content:
                logger.warning("news_validation_failed_error_keywords", url=doc.fetch_url, keyword=kw)
                return False
                
        return True

    async def health_check(self) -> bool:
        """Check if RSS feed is reachable."""
        return await super().health_check()

# Register the news sources
def register_news_sources():
    news_configs = [
        {
            "id": "et_top_stories",
            "name": "Economic Times",
            "url": "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
        },
        {
            "id": "mint_top_stories",
            "name": "Mint",
            "url": "https://www.livemint.com/rss/news",
        },
        {
            "id": "bs_top_stories",
            "name": "Business Standard",
            "url": "https://www.business-standard.com/rss/home_page_top_stories.rss",
        }
    ]

    for cfg in news_configs:
        config = SourceConfig(
            id=cfg["id"],
            name=cfg["name"],
            source_type=SourceType.RSS,
            url=cfg["url"],
            crawler_class="govnotify.sources.news_rss_source.NewsRSSSource",
            crawler_config={"is_news": True},
            rate_limit_rpm=10
        )
        SourceRegistry.add(NewsRSSSource(config))

register_news_sources()
