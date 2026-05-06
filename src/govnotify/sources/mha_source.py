"""
Ministry of Home Affairs (MHA) source - What's New.
Targets MHA's media/whats-new section and extracts content from PDFs.
Uses direct HTTP requests for high reliability and efficiency.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import AsyncIterator
from urllib.parse import urljoin

import structlog
from bs4 import BeautifulSoup

from govnotify.models.source import RawDocument, SourceConfig, SourceType
from govnotify.sources.registry import SourceRegistry
from govnotify.sources.base import WebScrapeSource
from govnotify.sources.utils import parse_indian_date

logger = structlog.get_logger(__name__)

MHA_WHATS_NEW_URL = "https://www.mha.gov.in/en/media/whats-new"


@SourceRegistry.register
class MHASource(WebScrapeSource):
    """MHA scraper using direct HTTP requests."""

    def __init__(self) -> None:
        super().__init__(SourceConfig(
            id="mha_updates",
            name="Ministry of Home Affairs",
            url=MHA_WHATS_NEW_URL,
            source_type=SourceType.WEB_SCRAPE,
            schedule_cron="0 */12 * * *",
            region_tags=["national"],
            language="en",
            crawler_class="govnotify.crawlers.crawl4ai_crawler.Crawl4AICrawler",
            rate_limit_rpm=10,
            crawler_config={"limit": 25}
        ))

    async def fetch(
        self, since: datetime | None = None
    ) -> AsyncIterator[RawDocument]:
        """Fetch notifications from MHA What's New table."""
        logger.info("mha_fetch_start", since=str(since) if since else "latest")
        
        try:
            resp = await self._get(str(self._config.url))
            html = resp.text
        except Exception:
            return

        entries = self._parse_listing(html, str(self._config.url))
        limit = self._config.crawler_config.get("limit", 15)
        yielded = 0
        seen_urls = set()
        
        for entry in entries:
            url = entry['url']
            if url in seen_urls:
                continue
            seen_urls.add(url)


            content = await self._fetch_pdf_content(url)
            
            doc = self.create_raw_document(
                title=entry['title'],
                fetch_url=url,
                raw_content=content,
                content_type="application/pdf",
                metadata={"portal_url": str(self._config.url)}
            )

            if await self.validate_response(doc):
                yield doc
                yielded += 1
                if yielded >= limit:
                    break

        logger.info("mha_complete", yielded=yielded)

    def _parse_listing(self, html: str, current_url: str) -> list[dict]:
        """Parse MHA table rows for titles and PDF links."""
        entries = []
        soup = BeautifulSoup(html, 'html.parser')
        
        table = soup.find('table')
        if not table:
            return []
            
        rows = table.find_all('tr')[1:] # Skip header
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 3:
                continue
            
            title_text = cols[1].get_text(separator=' ').strip()
            link_tag = cols[2].find('a', href=re.compile(r'\.pdf$|Download', re.IGNORECASE))
            if not link_tag:
                link_tag = row.find('a', href=re.compile(r'\.pdf$', re.IGNORECASE))
            
            if not link_tag:
                continue
            
            href = link_tag.get('href')
            full_url = urljoin(current_url, href)
            
            date_text = cols[3].get_text(strip=True) if len(cols) > 3 else ""

            entries.append({
                "title": title_text[:400],
                "url": full_url,
            })
        return entries
