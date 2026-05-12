"""
Ministry of Electronics and Information Technology (MeitY) source.
MANDATORY: Uses Crawl4AI/Playwright as the primary method due to Next.js hydration.
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

MEITY_ORDERS_URL = "https://www.meity.gov.in/documents/orders-and-notices"


@SourceRegistry.register
class MeitYSource(WebScrapeSource):
    def __init__(self) -> None:
        super().__init__(SourceConfig(
            id="meity_updates",
            name="MeitY",
            url=MEITY_ORDERS_URL,
            source_type=SourceType.WEB_SCRAPE,
            schedule_cron="0 18 * * *",
            region_tags=["national"],
            language="en",
            crawler_class="crawl4ai",
            rate_limit_rpm=10,
            crawler_config={"pages": 2}
        ))

    async def fetch(
        self, since: datetime | None = None
    ) -> AsyncIterator[RawDocument]:
        logger.info("meity_fetch_start_crawl4ai", since=str(since) if since else "latest")
        
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
        
        pages = self._config.crawler_config.get("pages", 3)
        
        async with AsyncWebCrawler() as crawler:
            for page in range(1, pages + 1):
                url = f"{MEITY_ORDERS_URL}?page={page}&target_lang=en"
                logger.info("meity_crawling_page", page=page)
                
                config = CrawlerRunConfig(
                    wait_for="css:.announcementbox, .views-table",
                    cache_mode=CacheMode.BYPASS,
                    page_timeout=60000
                )
                
                result = await crawler.arun(url=url, config=config)
                
                html = ""
                if not result.success:
                    logger.warning("meity_page_failed_crawl4ai", page=page, err=result.error_message)
                    # FALLBACK: Try direct httpx if Crawl4AI is blocked
                    try:
                        resp = await self._get(url)
                        html = resp.text
                        logger.info("meity_fallback_httpx_success", page=page)
                    except Exception as e:
                        logger.error("meity_fallback_httpx_failed", page=page, err=str(e))
                        break
                else:
                    html = result.html

                entries = self._parse_listing(html, url)
                if not entries:
                    logger.warning("meity_no_entries_on_page", page=page)
                    if not result.success: break # If fallback also failed, stop
                    continue

                logger.info("meity_page_success", page=page, count=len(entries))
                
                for entry in entries:
                    title = entry['title']
                    url = entry['url']

                    # Pass title to leverage early deduplication check in base.py
                    content = await self._fetch_pdf_content(url, title=title)
                    
                    if content == "DUPLICATE_SKIPPED":
                        continue
                    
                    doc = self.create_raw_document(
                        title=title,
                        fetch_url=url,
                        raw_content=content,
                        content_type="application/pdf" if content else "text/plain",
                        metadata={"portal_url": str(self._config.url)}
                    )

                    if await self.validate_response(doc):
                        yield doc

        logger.info("meity_fetch_complete")

    def _parse_listing(self, html: str, current_url: str) -> list[dict]:
        entries = []
        soup = BeautifulSoup(html, 'html.parser')
        
        # Try views-table first
        table = soup.find('table', class_='views-table')
        if table:
            for row in table.find_all('tr')[1:]:
                link = row.find('a', href=re.compile(r'\.pdf$', re.IGNORECASE))
                if not link: continue
                
                title = link.get_text(strip=True)
                full_url = urljoin(current_url, link.get('href'))
                
                entries.append({
                    "title": title,
                    "url": full_url,
                })

        # Try announcementbox
        if not entries:
            for box in soup.select('.announcementbox'):
                title_p = box.find('p')
                link = box.find('a', href=re.compile(r'\.pdf$', re.IGNORECASE))
                if not link or not title_p: continue
                
                title = title_p.get_text(strip=True)
                full_url = urljoin(current_url, link.get('href'))
                
                entries.append({
                    "title": title,
                    "url": full_url,
                })

        return entries
