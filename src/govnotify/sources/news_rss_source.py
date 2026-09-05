"""
News RSS Source: reads a feed, then extracts each article's full text.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncIterator

import structlog

from govnotify.constants import Country
from govnotify.crawlers.robust_news_crawler import RobustNewsCrawler
from govnotify.models.source import RawDocument, SourceConfig, SourceType
from govnotify.sources.base import WebScrapeSource
from govnotify.sources.registry import SourceRegistry

logger = structlog.get_logger(__name__)

# Articles to take from one feed in one run.
#
# Feeds vary wildly in length - Indian Express returns 200 items - and every
# article costs a page fetch plus an LLM call. Without a cap, adding a source
# meant an unbounded first run. Anything not taken this run is still there in
# the next one 30 minutes later.
MAX_ARTICLES_PER_RUN = 25

# Article extractions in flight at once.
#
# Extraction used to be strictly serial: every article waited for the previous
# one to finish a fetch that can take up to 30 seconds. This was the dominant
# cost in wall-clock time and the main thing standing between this pipeline and
# more sources. Kept modest so a single outlet is not hammered.
EXTRACT_CONCURRENCY = 5

# Below this, extracted text is treated as a block page or a stub.
MIN_CONTENT_CHARS = 500
MIN_RSS_SUMMARY_CHARS = 200

_ERROR_MARKERS = (
    "securitycompromiseerror",
    "ddos attack suspected",
    "blocked until",
    "access denied",
)


class NewsRSSSource(WebScrapeSource):
    """Source for news outlets via RSS plus full-article extraction."""

    def __init__(self, config: SourceConfig) -> None:
        super().__init__(config)
        self._crawler = RobustNewsCrawler()

    async def fetch(self, since: datetime | None = None) -> AsyncIterator[RawDocument]:
        """Read the feed, then extract new articles concurrently."""
        logger.info("news_fetch_start", source_id=self.source_id, url=str(self._config.url))

        entries = await self._read_feed()
        if not entries:
            return

        candidates = await self._select_new(entries)
        if not candidates:
            logger.info("news_no_new_entries", source_id=self.source_id)
            return

        logger.info(
            "news_extracting",
            source_id=self.source_id,
            candidates=len(candidates),
            concurrency=EXTRACT_CONCURRENCY,
        )

        semaphore = asyncio.Semaphore(EXTRACT_CONCURRENCY)

        async def extract(entry):
            async with semaphore:
                try:
                    return entry, await self._crawler.extract(entry.url)
                except Exception as exc:
                    logger.error("news_extraction_failed", url=entry.url, error=str(exc))
                    return entry, None

        tasks = [asyncio.create_task(extract(entry)) for entry in candidates]
        try:
            for completed in asyncio.as_completed(tasks):
                entry, crawl_result = await completed
                doc = self._build_document(entry, crawl_result)
                if doc and await self.validate_response(doc):
                    yield doc
        finally:
            # A consumer that stops early must not leave extractions running.
            for task in tasks:
                if not task.done():
                    task.cancel()

    async def _read_feed(self) -> list:
        """Fetch and parse the RSS feed into entries."""
        try:
            results = await self._crawler.crawl(str(self._config.url), {"is_rss": True})
        except Exception as exc:
            logger.error("news_rss_crawl_failed", source_id=self.source_id, error=str(exc))
            return []

        if not isinstance(results, list):
            logger.error("news_rss_crawl_invalid_response", source_id=self.source_id)
            return []
        return results

    async def _select_new(self, entries: list) -> list:
        """
        Drop entries we already have, then cap the batch.

        Duplicates are filtered before extraction so an already-seen article
        never costs a page fetch.
        """
        selected = []
        for entry in entries:
            if len(selected) >= MAX_ARTICLES_PER_RUN:
                logger.info(
                    "news_batch_capped",
                    source_id=self.source_id,
                    cap=MAX_ARTICLES_PER_RUN,
                    available=len(entries),
                )
                break

            title = entry.metadata.get("title", "")
            if not entry.url or not title:
                continue

            placeholder = self.create_raw_document(
                title=title, fetch_url=entry.url, raw_content=title
            )
            is_duplicate, _ = await self.check_duplicate(placeholder)
            if is_duplicate:
                logger.debug("news_skip_duplicate", title=title[:50])
                continue

            selected.append(entry)
        return selected

    def _build_document(self, entry, crawl_result) -> RawDocument | None:
        """Turn an extracted article into a RawDocument, or None if unusable."""
        title = entry.metadata.get("title", "")
        content = crawl_result.content if crawl_result else ""

        if not content or len(content) < MIN_CONTENT_CHARS:
            # Fall back to the feed's own summary when it carries enough text.
            rss_summary = entry.content or ""
            if len(rss_summary) >= MIN_RSS_SUMMARY_CHARS:
                logger.warning("news_using_rss_summary", url=entry.url)
                content = rss_summary
            else:
                logger.warning("news_skip_article_no_content", title=title[:50])
                return None

        metadata = dict(entry.metadata)
        if crawl_result and crawl_result.metadata:
            metadata.update(crawl_result.metadata)
        metadata["is_news"] = True
        metadata["original_url"] = entry.url
        metadata["country"] = self._config.country

        return self.create_raw_document(
            title=title,
            fetch_url=entry.url,
            raw_content=content,
            content_type="text/markdown",
            metadata=metadata,
        )

    async def validate_response(self, doc: RawDocument) -> bool:
        """Reject documents whose body is an anti-bot or error page."""
        if not await super().validate_response(doc):
            return False

        content = doc.raw_content.lower()
        for marker in _ERROR_MARKERS:
            if marker in content:
                logger.warning(
                    "news_validation_failed_error_keywords",
                    url=str(doc.fetch_url),
                    keyword=marker,
                )
                return False
        return True

    async def health_check(self) -> bool:
        return await super().health_check()


# Feeds by scope.
#
# Selection rule: prefer outlets whose editorial independence is structural
# rather than promised - public broadcasters operating under an independence
# charter, and papers with a straight-news reporting record. Excluded are
# outlets whose ownership or funding gives a documented editorial steer, and
# any outlet with a documented paid-news practice.
#
# Reuters and AP would be the natural first choice, being wire services, but
# both retired their public RSS feeds; AP now returns 401 and Reuters 404.
#
# Every feed below was checked live: it parses, returns items, and carries
# per-item publication dates.
#
# Scope is deliberately small. Each source costs LLM calls on every run and
# the free Gemini tier is the binding constraint, so breadth is traded for
# staying inside quota.
NEWS_FEEDS = [
    # --- World: public broadcasters, each under an editorial independence
    # charter and funded by a different state, so no single government's
    # perspective dominates the scope.
    {
        "id": "bbc_world",
        "name": "BBC News",
        "country": Country.WORLD.value,
        "url": "https://feeds.bbci.co.uk/news/rss.xml",
    },
    {
        "id": "france24_world",
        "name": "France 24",
        "country": Country.WORLD.value,
        "url": "https://www.france24.com/en/rss",
    },
    {
        "id": "dw_world",
        "name": "DW",
        "country": Country.WORLD.value,
        "url": "https://rss.dw.com/rdf/rss-en-world",
    },
    # --- India ---
    {
        "id": "thehindu_in",
        "name": "The Hindu",
        "country": Country.INDIA.value,
        "url": "https://www.thehindu.com/news/national/feeder/default.rss",
    },
    {
        "id": "indianexpress_in",
        "name": "Indian Express",
        "country": Country.INDIA.value,
        "url": "https://indianexpress.com/feed/",
    },
    # Business papers: narrower remit, but their reporting is factual and they
    # already carry stored history readers can page back into.
    {
        "id": "et_top_stories",
        "name": "Economic Times",
        "country": Country.INDIA.value,
        "url": "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
    },
    {
        "id": "mint_top_stories",
        "name": "Mint",
        "country": Country.INDIA.value,
        "url": "https://www.livemint.com/rss/news",
    },
    {
        "id": "bs_top_stories",
        "name": "Business Standard",
        "country": Country.INDIA.value,
        "url": "https://www.business-standard.com/rss/home_page_top_stories.rss",
    },
    # --- United States ---
    {
        "id": "npr_us",
        "name": "NPR",
        "country": Country.UNITED_STATES.value,
        "url": "https://feeds.npr.org/1001/rss.xml",
    },
    {
        "id": "pbs_us",
        "name": "PBS NewsHour",
        "country": Country.UNITED_STATES.value,
        "url": "https://www.pbs.org/newshour/feeds/rss/headlines",
    },
    {
        "id": "cbs_us",
        "name": "CBS News",
        "country": Country.UNITED_STATES.value,
        "url": "https://www.cbsnews.com/latest/rss/main",
    },
    {
        "id": "abc_us",
        "name": "ABC News",
        "country": Country.UNITED_STATES.value,
        "url": "https://abcnews.go.com/abcnews/topstories",
    },
]

# Sources are staggered across the hour rather than all firing every 30
# minutes. Nothing is gained by re-reading a feed that publishes a few dozen
# items a day more often than that, and staggering keeps any single ingestion
# run small enough to finish inside a GitHub Actions job.
SCHEDULES = ["7 */2 * * *", "22 */2 * * *", "37 */2 * * *", "52 */2 * * *"]


def register_news_sources() -> None:
    """Register every configured news outlet with the source registry."""
    for index, feed in enumerate(NEWS_FEEDS):
        config = SourceConfig(
            id=feed["id"],
            name=feed["name"],
            source_type=SourceType.RSS,
            url=feed["url"],
            country=feed["country"],
            schedule_cron=SCHEDULES[index % len(SCHEDULES)],
            crawler_class="govnotify.sources.news_rss_source.NewsRSSSource",
            crawler_config={"is_news": True},
            rate_limit_rpm=10,
        )
        SourceRegistry.add(NewsRSSSource(config))


register_news_sources()
