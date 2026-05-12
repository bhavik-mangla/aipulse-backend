"""
RBI (Reserve Bank of India) circulars and press releases source.
Extracts "entire content" from PDFs as requested by the user.
Scrapes rbi.org.in for notification links and downloads/parses the linked PDFs.

Sources:
1. Circulars: https://rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx
2. Press Releases: https://rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import AsyncIterator
from urllib.parse import urljoin

import structlog
from bs4 import BeautifulSoup

from govnotify.models.source import RawDocument, SourceConfig, SourceType
from govnotify.sources.base import WebScrapeSource
from govnotify.sources.registry import SourceRegistry
from govnotify.sources.utils import parse_indian_date

logger = structlog.get_logger(__name__)

RBI_CIRCULARS_URL = "https://rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx"
RBI_PRESS_URL = "https://rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"


class BaseRBISource(WebScrapeSource):
    """Common logic for RBI sources."""

    async def fetch(
        self, since: datetime | None = None
    ) -> AsyncIterator[RawDocument]:
        """Scrape RBI table and extract content."""
        logger.info(f"{self.source_id}_fetch_start", since=str(since) if since else "latest")

        resp = await self._get(str(self._config.url))
        entries = _parse_rbi_table(resp.text, str(self._config.url))
        
        limit = self._config.crawler_config.get("limit", 25)
        yielded = 0
        
        for entry in entries:
            title = entry.get("title", "RBI Notification")
            pdf_url = entry.get("pdf_url")
            
            content = ""
            is_pdf = False
            if pdf_url:
                content = await self._fetch_pdf_content(pdf_url, title=title)
                if content == "DUPLICATE_SKIPPED":
                    continue
                if content:
                    is_pdf = True
            
            if not content:
                detail_url = entry.get("url")
                if detail_url:
                    content = await self._fetch_html_content(detail_url, title=title)
                    if content == "DUPLICATE_SKIPPED":
                        continue

            doc = self.create_raw_document(
                title=title,
                fetch_url=entry.get("url") or str(self._config.url),
                raw_content=content or title,
                content_type="application/pdf" if is_pdf else "text/html",
                metadata={
                    "pdf_url": pdf_url,
                    "portal_url": entry.get("url")
                }
            )

            if await self.validate_response(doc):
                yield doc
                yielded += 1
                if yielded >= limit:
                    break

        logger.info(f"{self.source_id}_complete", yielded=yielded)


@SourceRegistry.register
class RBICircularsSource(BaseRBISource):
    """RBI Circulars source with PDF extraction."""

    def __init__(self) -> None:
        super().__init__(SourceConfig(
            id="rbi_circulars",
            name="RBI Circulars",
            source_type=SourceType.WEB_SCRAPE,
            url=RBI_CIRCULARS_URL,
            schedule_cron="0 18 * * *",
            language="en",
            region_tags=["national"],
            crawler_class="govnotify.crawlers.crawl4ai_crawler.Crawl4AICrawler",
            rate_limit_rpm=20,
            crawler_config={"limit": 25}
        ))


@SourceRegistry.register
class RBIPressReleasesSource(BaseRBISource):
    """RBI Press Releases source with PDF extraction."""

    def __init__(self) -> None:
        super().__init__(SourceConfig(
            id="rbi_press_releases",
            name="RBI Press Releases",
            source_type=SourceType.WEB_SCRAPE,
            url=RBI_PRESS_URL,
            schedule_cron="0 18 * * *",
            region_tags=["national"],
            language="en",
            crawler_class="govnotify.crawlers.crawl4ai_crawler.Crawl4AICrawler",
            rate_limit_rpm=20,
            crawler_config={"limit": 25}
        ))


def _parse_rbi_table(html: str, base_url: str) -> list[dict]:
    """Robust parser for RBI tables, capturing both HTML and PDF links."""
    entries = []
    soup = BeautifulSoup(html, 'html.parser')
    
    rows = soup.find_all('tr')
    for row in rows:
        links = row.find_all('a')
        if not links:
            continue
        
        main_link = links[0]
        title = main_link.text.strip()
        if not title or len(title) < 10:
            continue
            
        href = main_link.get('href', '')
        if not href or 'javascript' in href:
            continue
            
        full_url = urljoin(base_url, href)
        
        pdf_url = None
        for link in links:
            lhref = link.get('href', '').upper()
            if lhref.endswith('.PDF'):
                pdf_url = urljoin(base_url, link.get('href'))
                break
        
        # Extract date from row text
        row_text = row.get_text()
        
        entries.append({
            "title": title,
            "url": full_url,
            "pdf_url": pdf_url,
        })

    return entries
