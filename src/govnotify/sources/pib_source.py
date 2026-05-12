"""
PIB (Press Information Bureau) RSS source.
The easiest source - official government RSS feed providing press releases from all ministries and departments of the Government of India.
The PIB RSS feed is a headline feed (title + link only, no description). For each entry, we fetch the linked page to extract the full press release content.

Feed URL: https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import AsyncIterator
from urllib.parse import urljoin

import structlog
from bs4 import BeautifulSoup

from govnotify.crawlers.rss_crawler import RSSCrawler
from govnotify.models.source import RawDocument, SourceConfig, SourceType
from govnotify.sources.registry import SourceRegistry
from govnotify.sources.base import WebScrapeSource, SourceFetchError

logger = structlog.get_logger(__name__)

PIB_FEED_URL = "https://www.pib.gov.in/RssMain.aspx?ModId=6&lang=1&reg=3"


@SourceRegistry.register
class PIBSource(WebScrapeSource):
    """Press Information Bureau RSS feed source."""

    def __init__(self) -> None:
        super().__init__(SourceConfig(
            id="pib_press_releases",
            name="PIB Press Releases",
            url=PIB_FEED_URL,
            source_type=SourceType.RSS,
            schedule_cron="0 18 * * *",
            region_tags=["national"],
            language="en",
            crawler_class="govnotify.crawlers.rss_crawler.RSSCrawler",
            rate_limit_rpm=30,
        ))
        self._crawler = RSSCrawler()

    async def fetch(
        self, since: datetime | None = None
    ) -> AsyncIterator[RawDocument]:
        """
        The RSS feed only contains titles and links. For each entry,
        we fetch the linked page to extract the full press release text.
        """
        logger.info("pib_fetch_start", since=str(since) if since else "latest")
        try:
            results = await self._crawler.crawl(
                str(self._config.url), self._config.crawler_config
            )
        except Exception as exc:
            raise SourceFetchError(
                source_id=self.source_id,
                message=f"Failed to crawl PIB RSS feed: {exc}",
                cause=exc,
            ) from exc

        if not results:
            logger.warning("pib_fetch_empty", url=str(self._config.url))
            return

        yielded = 0
        for result in results:
            title = result.metadata.get("title", "Untitled")
            
            # Efficient pre-fetch check
            partial_doc = self.create_raw_document(title=title, fetch_url=result.url, raw_content=title)
            is_dup, _ = await self.check_duplicate(partial_doc)
            if is_dup:
                logger.info("pib_skip_duplicate_pre_fetch", title=title[:50])
                continue

            content, pdf_url = await self._fetch_pib_page(result.url)
            
            if not content:
                content = title

            doc = self.create_raw_document(
                title=title,
                fetch_url=result.url,
                raw_content=content,
                content_type="text/html",
                metadata={
                    "tags": result.metadata.get("tags", []),
                    "author": result.metadata.get("author", ""),
                    "feed_title": result.metadata.get("feed_title", ""),
                    "links": result.links,
                    "pdf_url": pdf_url,
                    "portal_url": result.url,
                },
            )

            if await self.validate_response(doc):
                yield doc
                yielded += 1

        logger.info("pib_fetch_complete", yielded=yielded)

    async def _fetch_pib_page(self, url: str) -> tuple[str, str | None]:
        """Fetch PIB page, extract clean text from hidden input or div, and find PDF link."""
        try:
            resp = await self._get(url)
            html = resp.text
            soup = BeautifulSoup(html, 'html.parser')
            
            # 1. Look for PDF link
            pdf_url = None
            pdf_link = soup.find('a', href=re.compile(r'\.pdf$', re.IGNORECASE))
            if pdf_link:
                pdf_url = urljoin(url, pdf_link.get('href'))
            
            # 2. Extract content (PIB special cleaning)
            # Look for hidden input first (contains the pure press release text)
            hidden_input = soup.find('input', {'id': 'ltrDescriptionn'})
            if hidden_input:
                raw_val = hidden_input.get('value', '')
                if "<" in raw_val:
                    return await self._parser.extract(raw_val, "text/html"), pdf_url
                return raw_val, pdf_url
            
            # Fallback to ReleaseText div
            release_div = soup.find('div', class_='ReleaseText')
            if release_div:
                return await self._parser.extract(str(release_div), "text/html"), pdf_url
                
            # Final fallback
            return await self._parser.extract(html, "text/html"), pdf_url
        except Exception as exc:
            logger.warning("pib_page_fetch_failed", url=url, error=str(exc))
            return "", None

    def _parse_rss_date(self, date_str: str) -> datetime | None:
        """Parse RSS date strings safely."""
        if not date_str:
            return None
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str).astimezone(timezone.utc)
        except Exception:
            return None
