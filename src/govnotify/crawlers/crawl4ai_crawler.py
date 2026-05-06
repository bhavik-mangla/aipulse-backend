"""
Crawl4AI web crawler wrapper.
Uses the Crawl4AI library (async, LLM-friendly output, anti-bot detection) as the primary web crawling engine for scraping government sites.
"""
import structlog
from govnotify.crawlers.base import AbstractCrawler, CrawlResult

logger = structlog.get_logger(__name__)


class Crawl4AICrawler(AbstractCrawler):
    """Web crawler using Crawl4AI for structured content extraction."""

    async def crawl(self, url: str, config: dict) -> CrawlResult:
        """
        Crawl a web page using Crawl4AI and return structured result.
        Args:
            url: The URL to crawl.
            config: Additional CrawlerRunConfig kwargs (e.g. word_count_threshold, excluded_tags).
        Returns:
            CrawlResult with markdown content and metadata.
        """
        # Lazy import to avoid heavy Crawl4AI dependency at module load time
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

        run_config = CrawlerRunConfig(
            word_count_threshold=config.get("word_count_threshold", 200),
            excluded_tags=config.get(
                "excluded_tags", ["nav", "footer", "header", "sidebar"]
            ),
            **{
                k: v
                for k, v in config.items()
                if k not in ("word_count_threshold", "excluded_tags")
            }
        )

        logger.info("crawl4ai_crawl_start", url=url)
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=run_config)

            # Extract internal links safely
            links: list[str] = []
            if result.links:
                if isinstance(result.links, dict):
                    links = result.links.get("internal", [])
                elif isinstance(result.links, list):
                    links = result.links

            crawl_result = CrawlResult(
                url=url,
                status_code=result.status_code,
                content=result.markdown or "",
                content_type="text/html",
                links=links,
                metadata=result.metadata or {},
                raw_html=result.html,
                elapsed_ms=getattr(result, "elapsed", 0) or 0,
            )

            logger.info(
                "crawl4ai_crawl_complete",
                url=url,
                status=crawl_result.status_code,
                content_len=len(crawl_result.content),
                elapsed_s=round(crawl_result.elapsed_ms / 1000, 1),
            )

            return crawl_result
