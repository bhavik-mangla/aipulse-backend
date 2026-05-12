"""
IBBI (Insolvency and Bankruptcy Board of India) source.
Scrapes the IBBI website for what's new, including orders, press releases, and circulars.
Extracts content from linked PDFs.

URL: https://ibbi.gov.in/whats-new
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import AsyncIterator
from urllib.parse import urljoin

import structlog
from bs4 import BeautifulSoup

from govnotify.models.source import RawDocument, SourceConfig, SourceType
from govnotify.sources.registry import SourceRegistry
from govnotify.sources.base import WebScrapeSource, SourceFetchError
from govnotify.sources.utils import clean_text

logger = structlog.get_logger(__name__)

IBBI_WHATS_NEW_URL = "https://ibbi.gov.in/whats-new"


@SourceRegistry.register
class IBBISource(WebScrapeSource):
    """IBBI (Insolvency and Bankruptcy Board of India) news and orders source."""

    def __init__(self) -> None:
        super().__init__(SourceConfig(
            id="ibbi_updates",
            name="IBBI Updates",
            url=IBBI_WHATS_NEW_URL,
            source_type=SourceType.WEB_SCRAPE,
            schedule_cron="0 */12 * * *",
            region_tags=["national"],
            language="en",
            crawler_class="govnotify.sources.ibbi_source.IBBISource",
            rate_limit_rpm=20,
        ))
        self._headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        })

    async def fetch(
        self, since: datetime | None = None
    ) -> AsyncIterator[RawDocument]:
        """
        Fetch documents from IBBI's 'What's New' page.
        Iterates through the table and extracts PDF content.
        """
        logger.info("ibbi_fetch_start", since=str(since) if since else "latest")
        
        try:
            resp = await self._get(str(self._config.url))
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            table = soup.find('table', class_='responsive-enabled')
            if not table:
                logger.error("ibbi_table_not_found", url=str(self._config.url))
                return

            rows = table.find('tbody').find_all('tr')
            yielded = 0
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) < 3:
                    continue
                
                # Column 1: Date (YYYY-MM-DD)
                date_str = cols[1].get_text(strip=True)
                # Column 2: Subject and Link
                link_tag = cols[2].find('a', class_='snd')
                
                if not link_tag:
                    continue
                
                title = link_tag.get_text(strip=True)
                # Remove extra spaces and PDF size info from title
                title = re.sub(r'\s*\(\d+(\.\d+)?\s*(KB|MB)\)\s*$', '', title)
                title = clean_text(title)
                
                href = link_tag.get('href')
                if not href:
                    continue
                    
                pdf_url = urljoin(str(self._config.url), href)

                logger.debug("ibbi_fetching_pdf", url=pdf_url)
                content = await self._fetch_pdf_content(pdf_url, title=title)
                
                if content == "DUPLICATE_SKIPPED":
                    continue

                # Determine content type based on URL and successful fetch
                if ".pdf" in pdf_url.lower():
                    content_type = "application/pdf"
                else:
                    content_type = "text/html"
                
                if not content:
                    content = title
                    content_type = "text/plain"

                doc = self.create_raw_document(
                    title=title,
                    fetch_url=pdf_url,
                    raw_content=content,
                    content_type=content_type,
                    metadata={
                        "portal_url": str(self._config.url),
                    },
                )

                if await self.validate_response(doc):
                    yield doc
                    yielded += 1
                
                # Safety break for large fetches (hard limit)
                if yielded >= 30:
                    break
                
            logger.info("ibbi_fetch_complete", yielded=yielded)
            
        except Exception as exc:
            raise SourceFetchError(
                source_id=self.source_id,
                message=f"Failed to fetch IBBI updates: {exc}",
                cause=exc,
            ) from exc

    def _parse_date(self, date_str: str) -> datetime | None:
        """Parse IBBI date format YYYY-MM-DD."""
        if not date_str:
            return None
        try:
            dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            # Try generic parser if IBBI format fails
            from govnotify.sources.utils import parse_indian_date
            return parse_indian_date(date_str)
