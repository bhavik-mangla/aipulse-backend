"""
Income Tax notifications source.
Scrapes the Income Tax India website and extracts content from PDFs.

Uses a hybrid strategy:
1. Wait for React cards to render with robust retries.
2. Extract title, date, and document URL from card structure.
3. Fallback to slug generation for missing links (confirmed by user observation).
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
from govnotify.sources.base import WebScrapeSource
from govnotify.sources.utils import parse_indian_date

logger = structlog.get_logger(__name__)

INCOME_TAX_NOTIFICATIONS_URL = "https://www.incometaxindia.gov.in/notifications"
INCOME_TAX_CIRCULARS_URL = "https://www.incometaxindia.gov.in/circulars"


@SourceRegistry.register
class IncomeTaxSource(WebScrapeSource):
    """Income Tax scraper with PDF support targeting Liferay structures."""

    def __init__(self) -> None:
        super().__init__(SourceConfig(
            id="income_tax",
            name="Income Tax Notifications & Circulars",
            url=INCOME_TAX_NOTIFICATIONS_URL,
            source_type=SourceType.WEB_SCRAPE,
            schedule_cron="0 */12 * * *",
            region_tags=["national"],
            language="en",
            crawler_class="govnotify.crawlers.crawl4ai_crawler.Crawl4AICrawler",
            rate_limit_rpm=15,
            crawler_config={"limit": 25}
        ))

    async def fetch(
        self, since: datetime | None = None
    ) -> AsyncIterator[RawDocument]:
        """Fetch notifications and circulars."""
        logger.info("income_tax_fetch_start", since=str(since) if since else "latest")
        
        target_urls = [INCOME_TAX_NOTIFICATIONS_URL, INCOME_TAX_CIRCULARS_URL]
        
        all_entries = []
        for url in target_urls:
            try:
                entries = await self._crawl_with_robust_rendering(url)
                if entries:
                    logger.info("income_tax_success", url=url, count=len(entries))
                    all_entries.extend(entries)
                else:
                    logger.warning("income_tax_no_entries", url=url)
            except Exception as exc:
                logger.warning("income_tax_exception", url=url, error=str(exc))

        yielded = 0
        seen_urls = set()
        unique_entries = []
        for e in all_entries:
            url_val = e.get('url')
            if not url_val: continue
            
            # Handle list of URL variations for hashing
            hash_key = tuple(url_val) if isinstance(url_val, list) else url_val
            
            if hash_key not in seen_urls:
                seen_urls.add(hash_key)
                unique_entries.append(e)

        # Limit for performance
        limit = self._config.crawler_config.get("limit", 25)
        
        for entry in unique_entries:

            # Resolve the URL if it's a list of variations
            pdf_url = entry.get("url")
            if isinstance(pdf_url, list):
                pdf_url = await self._resolve_working_url(pdf_url)
            
            if not pdf_url:
                logger.warning("income_tax_no_working_url", title=entry['title'])
                continue

            content = await self._fetch_pdf_content(pdf_url)
            
            doc = self.create_raw_document(
                title=entry['title'],
                fetch_url=pdf_url,
                raw_content=content,
                content_type="application/pdf",
                metadata={
                    "notification_number": entry.get("notification_number", ""),
                    "portal_url": entry.get("portal_url") or str(self._config.url),
                    "pdf_url": pdf_url,
                },
            )

            if await self.validate_response(doc):
                yield doc
                yielded += 1
                if yielded >= limit:
                    break

        logger.info("income_tax_complete", yielded=yielded)

    async def _resolve_working_url(self, urls: list[str]) -> str | None:
        """Try multiple URL variations and return the first one that works."""
        import httpx
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            for url in urls:
                try:
                    resp = await client.head(url)
                    if resp.status_code == 200:
                        return url
                except Exception:
                    continue
        return None

    async def _crawl_with_robust_rendering(self, url: str) -> list[dict]:
        """Use Crawl4AI/Playwright with multiple wait strategies, with httpx fallback."""
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
        
        try:
            async with AsyncWebCrawler() as crawler:
                # We wait for the body but use JS to wait specifically for the list content
                config = CrawlerRunConfig(
                    wait_for="css:body", 
                    cache_mode=CacheMode.BYPASS,
                    page_timeout=90000,
                )
                
                js_code = """
                const delay = ms => new Promise(res => setTimeout(res, ms));
                // Wait up to 15 seconds for the cards to appear
                for (let i = 0; i < 30; i++) {
                    if (document.querySelector('.notification-card-width')) break;
                    await delay(500);
                }
                // Small extra buffer for rendering
                await delay(2000);
                return document.body.innerHTML;
                """
                
                result = await crawler.arun(url=url, config=config, js_code=js_code)
                
                if result.success:
                    entries = self._parse_listing(result.html, url)
                    if entries:
                        return entries
                    logger.warning("income_tax_crawl4ai_no_entries", url=url)
                else:
                    logger.warning("income_tax_crawl4ai_failed", url=url, err=result.error_message)
        except Exception as e:
            logger.warning("income_tax_crawl4ai_exception", url=url, err=str(e))

        # FALLBACK: Try direct httpx if Crawl4AI is blocked or empty
        logger.info("income_tax_fallback_httpx", url=url)
        try:
            resp = await self._get(url)
            return self._parse_listing(resp.text, url)
        except Exception as e:
            logger.error("income_tax_fallback_httpx_failed", url=url, err=str(e))
            return []

    def _parse_listing(self, html: str, current_url: str) -> list[dict]:
        """Parse notification entries using card patterns."""
        entries = []
        soup = BeautifulSoup(html, 'html.parser')
        
        # Target the specific card structure seen in the snippet
        cards = soup.select('div.sections-item, div.card-body')
        for card in cards:
            # Title is typically in a span with text-decoration-none or fw-bold
            title_tag = card.find('span', class_=re.compile(r'text-decoration-none|fw-bold', re.IGNORECASE))
            if not title_tag:
                title_tag = card.find(['h5', 'a'], class_=re.compile(r'card-title', re.IGNORECASE))
            
            if not title_tag: continue
            title = title_tag.get_text(strip=True)
            
            portal_url = None
            if title_tag.name == 'a' and title_tag.get('href'):
                portal_url = urljoin(current_url, title_tag.get('href'))

            # Date is in a div with class 'small' (e.g., April 10th, 2026)
            date_tag = card.find('div', class_='small')
            
            # URL resolution
            link_tag = card.find('a', href=re.compile(r'/documents/d/guest/.*|/Documents/d/guest/.*|.*\.pdf$', re.IGNORECASE))
            if not link_tag:
                link_tag = card.find_parent('a', href=True)
            
            full_url = None
            notification_number = ""
            
            # Extract notification number if possible
            num_match = re.search(r'(?:Notification|Circular) No\.\s*([\d/]+)', title, re.IGNORECASE)
            if num_match:
                notification_number = num_match.group(1)

            if link_tag and link_tag.get('href'):
                full_url = urljoin(current_url, link_tag.get('href'))
            else:
                # Fallback: Slug generation confirmed by user
                # Working patterns are inconsistent, so we try multiple
                slug_match = re.search(r'(?:Notification|Circular) No\.\s*(\d+)\s*/\s*(\d+)', title, re.IGNORECASE)
                if slug_match:
                    num, year = slug_match.groups()
                    doc_type = "notification" if "notification" in title.lower() else "circular"
                    
                    variations = []
                    if doc_type == "notification":
                        # Variations for Notifications
                        variations.extend([
                            f"https://www.incometaxindia.gov.in/documents/d/guest/ennotification-no-{num}-{year}-pdf",
                            f"https://www.incometaxindia.gov.in/documents/d/guest/notification-{num}-{year}-pdf",
                            f"https://www.incometaxindia.gov.in/documents/d/guest/en-notification-no-{num}-{year}-pdf",
                            f"https://www.incometaxindia.gov.in/documents/d/guest/notification-no-{num}-{year}-pdf",
                        ])
                    else:
                        # Variations for Circulars
                        variations.extend([
                            f"https://www.incometaxindia.gov.in/documents/d/guest/circular-{num}-{year}-pdf",
                            f"https://www.incometaxindia.gov.in/documents/d/guest/circular-no-{num}-{year}-pdf",
                            f"https://www.incometaxindia.gov.in/documents/d/guest/encircular-{num}-{year}-pdf",
                            f"https://www.incometaxindia.gov.in/documents/d/guest/encircular-no-{num}-{year}-pdf",
                        ])
                    full_url = variations
                else:
                    # Generic slug for non-numbered items
                    clean_title = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
                    full_url = f"https://www.incometaxindia.gov.in/documents/d/guest/{clean_title}-pdf"
            
            if full_url:
                # Filter for relevant document types
                if any(k in title.lower() for k in ["notification", "circular", "order", "instruction", "corrigendum", "f. no"]):
                    if not any(k in title.lower() for k in ["directory", "chart", "charter", "about us", "contact us", "help"]):
                        entries.append({
                            "title": title,
                            "url": full_url,
                            "notification_number": notification_number,
                            "portal_url": portal_url
                        })
                
        return entries
