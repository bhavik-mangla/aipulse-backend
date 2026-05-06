"""
SEBI (Securities and Exchange Board of India) source.
Scrapes the SEBI website for news, orders, circulars and reports.
Extracts content from embedded PDFs in detail pages.

URL: https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListingAll=yes
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import AsyncIterator
from urllib.parse import urljoin, urlparse, parse_qs

import structlog
from bs4 import BeautifulSoup

from govnotify.models.source import RawDocument, SourceConfig, SourceType
from govnotify.sources.registry import SourceRegistry
from govnotify.sources.base import WebScrapeSource, SourceFetchError
from govnotify.sources.utils import parse_indian_date

logger = structlog.get_logger(__name__)

SEBI_LISTING_URL = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListingAll=yes"


@SourceRegistry.register
class SEBISource(WebScrapeSource):
    """SEBI (Securities and Exchange Board of India) news and orders source."""

    def __init__(self) -> None:
        super().__init__(SourceConfig(
            id="sebi_news",
            name="SEBI News & Orders",
            url=SEBI_LISTING_URL,
            source_type=SourceType.WEB_SCRAPE,
            schedule_cron="0 */12 * * *",
            region_tags=["national"],
            language="en",
            crawler_class="govnotify.sources.sebi_source.SEBISource",
            rate_limit_rpm=20,
        ))
        # Update headers with more browser-like values from user's curl
        self._headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.7",
            "Cache-Control": "max-age=0",
            "DNT": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Sec-GPC": "1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Mobile Safari/537.36",
        })

    async def fetch(
        self, since: datetime | None = None
    ) -> AsyncIterator[RawDocument]:
        """
        Fetch documents from SEBI's 'List All' page.
        Iterates through the table and follows links to extract PDF content.
        """
        logger.info("sebi_fetch_start", since=str(since) if since else "latest")
        
        try:
            # SEBI often requires a user-agent and some headers to avoid 403/blocking
            resp = await self._get(str(self._config.url))
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            table = soup.find('table', id='sample_1')
            if not table:
                logger.error("sebi_table_not_found", url=str(self._config.url))
                return

            rows = table.find('tbody').find_all('tr')
            yielded = 0
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) < 3:
                    continue
                
                # Column 0: Date
                date_str = cols[0].get_text(strip=True)
                # Column 1: Type (Orders, Press Releases, Circulars, etc.)
                doc_type = cols[1].get_text(strip=True)
                # Column 2: Title and Link
                link_tag = cols[2].find('a')
                
                if not link_tag:
                    continue
                
                title = link_tag.get_text(strip=True)
                href = link_tag.get('href')
                if not href:
                    continue
                
                detail_url = urljoin(str(self._config.url), href)

                logger.debug("sebi_fetching_detail", url=detail_url)
                content, pdf_url = await self._fetch_detail_and_pdf(detail_url, title=title)
                
                # If we got PDF content, it is plain text. Set content_type accordingly.
                content_type = "text/plain" if pdf_url and content else "text/html"

                doc = self.create_raw_document(
                    title=title,
                    fetch_url=detail_url,
                    raw_content=content,
                    content_type=content_type,
                    metadata={
                        "doc_type": doc_type,
                        "pdf_url": pdf_url,
                        "portal_url": detail_url,
                    },
                )

                if await self.validate_response(doc):
                    yield doc
                    yielded += 1
                
                # Safety break for large fetches (hard limit)
                if yielded >= 30:
                    break
                
            logger.info("sebi_fetch_complete", yielded=yielded)
            
        except Exception as exc:
            raise SourceFetchError(
                source_id=self.source_id,
                message=f"Failed to fetch SEBI news: {exc}",
                cause=exc,
            ) from exc

    async def _fetch_detail_and_pdf(self, url: str, title: str = "") -> tuple[str, str | None]:
        """Fetch detail page, extract PDF link from iframe and extract text."""
        try:
            resp = await self._get(url)
            html = resp.text
            soup = BeautifulSoup(html, 'html.parser')
            
            # SEBI embeds PDFs using an iframe with a 'file' parameter
            # e.g., <iframe src='https://www.sebi.gov.in/web/?file=https://www.sebi.gov.in/sebi_data/attachdocs/...'
            pdf_url = None
            iframe = soup.find('iframe', src=re.compile(r'file='))
            if iframe:
                src = iframe.get('src', '')
                try:
                    parsed_src = urlparse(src)
                    qs = parse_qs(parsed_src.query)
                    if 'file' in qs:
                        pdf_url = qs['file'][0]
                except Exception:
                    pass
            
            # Fallback to direct PDF links in the page
            if not pdf_url:
                pdf_link = soup.find('a', href=re.compile(r'\.pdf$', re.IGNORECASE))
                if pdf_link:
                    pdf_url = urljoin(url, pdf_link.get('href'))

            content = ""
            if pdf_url:
                logger.debug("sebi_extracting_pdf", pdf_url=pdf_url)
                content = await self._fetch_pdf_content(pdf_url, title=title)
            
            if not content:
                # Fallback to HTML extraction if PDF extraction failed or no PDF found
                main_section = soup.find('section', class_='main_section')
                if main_section:
                    content = await self._parser.extract(str(main_section), "text/html")
                else:
                    content = await self._parser.extract(html, "text/html")
            
            return content, pdf_url
            
        except Exception as exc:
            logger.warning("sebi_detail_fetch_failed", url=url, error=str(exc))
            return "", None
