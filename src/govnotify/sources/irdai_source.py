"""
IRDAI (Insurance Regulatory and Development Authority of India) source.
Scrapes the IRDAI website for what's new, circulars, and orders.
IRDAI uses a Liferay-based portal with a timeline of updates.
"""
from __future__ import annotations

import re
import json
from datetime import datetime
from typing import AsyncIterator
from urllib.parse import urljoin

import structlog
from bs4 import BeautifulSoup

from govnotify.models.source import RawDocument, SourceConfig, SourceType
from govnotify.sources.registry import SourceRegistry
from govnotify.sources.base import WebScrapeSource, SourceFetchError
from govnotify.sources.utils import parse_indian_date

logger = structlog.get_logger(__name__)

IRDAI_WHATS_NEW_URL = "https://irdai.gov.in/web/guest/whats-new"


@SourceRegistry.register
class IRDAISource(WebScrapeSource):
    """IRDAI (Insurance Regulatory and Development Authority of India) news and circulars source."""

    def __init__(self) -> None:
        super().__init__(SourceConfig(
            id="irdai_updates",
            name="IRDAI Updates",
            url=IRDAI_WHATS_NEW_URL,
            source_type=SourceType.WEB_SCRAPE,
            schedule_cron="0 */12 * * *",
            region_tags=["national"],
            language="en",
            crawler_class="govnotify.sources.irdai_source.IRDAISource",
            rate_limit_rpm=15,
        ))
        # IRDAI needs a decent User-Agent and specific headers to avoid 403/504
        self._headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
        })

    async def fetch(
        self, since: datetime | None = None
    ) -> AsyncIterator[RawDocument]:
        """
        Fetch documents from IRDAI's 'What's New' page.
        Uses Crawl4AI to handle dynamic content rendering with httpx fallback.
        """
        logger.info("irdai_fetch_start", since=str(since) if since else "latest")
        
        try:
            from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
            
            # IRDAI timeline items are rendered by a Liferay portlet.
            # We use a robust wait strategy: wait for body, then use JS loop to wait for content.
            config = CrawlerRunConfig(
                wait_for="css:body",
                cache_mode=CacheMode.BYPASS,
                page_timeout=90000, # Increased timeout for slow Liferay portal
            )
            
            # Robust JS to wait for content and handle slow Liferay rendering
            js_code = """
            const delay = ms => new Promise(res => setTimeout(res, ms));
            // Wait up to 45 seconds for the timeline items to appear
            let found = false;
            for (let i = 0; i < 90; i++) {
                if (document.querySelector('.whatsNew-content') || document.querySelector('#itemsContainer')) {
                    found = true;
                    break;
                }
                // If we see a 504 or Service Unavailable, we can break early and fail
                if (document.title.includes("Service unavailable") || document.body.innerText.includes("504 Gateway Timeout")) {
                    break;
                }
                await delay(500);
            }
            if (!found) {
                throw new Error("Timeline items not found after waiting. Page might be empty or error occurred.");
            }
            // Small extra buffer for final rendering
            await delay(2000);
            return document.body.innerHTML;
            """
            
            html = ""
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(
                    url=str(self._config.url),
                    config=config,
                    js_code=js_code
                )
                
                if result.success:
                    html = result.html
                else:
                    logger.warning("irdai_crawl4ai_failed", error=result.error_message)
                    # FALLBACK: Try direct httpx with robust headers
                    resp = await self._get(str(self._config.url), headers=self._headers)
                    html = resp.text

            soup = BeautifulSoup(html, 'html.parser')
            items = soup.find_all('div', class_='whatsNew-content')
            
            if not items:
                logger.warning("irdai_no_items_found")
                return

            yielded = 0
            for item in items:
                header = item.find('h3', class_='timeline-header')
                if not header:
                    continue
                
                # Header format: "DD-MM-YYYY<br><a ...>Title</a>"
                date_str = ""
                for content in header.contents:
                    if isinstance(content, str) and content.strip():
                        date_str = content.strip()
                        break
                
                link_tag = header.find('a')
                if not link_tag:
                    continue
                
                title = link_tag.get_text(strip=True)
                href = link_tag.get('href')
                if not href:
                    continue
                
                detail_url = urljoin(str(self._config.url), href)
                
                body_div = item.find('div', class_='timeline-body')
                doc_type = body_div.get_text(strip=True) if body_div else "Update"

                logger.debug("irdai_fetching_detail", url=detail_url)
                content, pdf_urls = await self._fetch_detail_and_pdfs(detail_url, title=title)
                
                # If we got PDF content, it is plain text. Set content_type accordingly.
                content_type = "text/plain" if pdf_urls and content else "text/html"

                doc = self.create_raw_document(
                    title=title,
                    fetch_url=detail_url,
                    raw_content=content,
                    content_type=content_type,
                    metadata={
                        "doc_type": doc_type,
                        "pdf_urls": pdf_urls,
                        "primary_pdf_url": pdf_urls[0] if pdf_urls else None,
                        "portal_url": detail_url,
                    },
                )

                if await self.validate_response(doc):
                    yield doc
                    yielded += 1
                
                # Safety break for large fetches (hard limit)
                if yielded >= 30:
                    break
            
            logger.info("irdai_fetch_complete", yielded=yielded)
            
        except Exception as exc:
            raise SourceFetchError(
                source_id=self.source_id,
                message=f"Failed to fetch IRDAI updates: {exc}",
                cause=exc,
            ) from exc

    async def _fetch_detail_and_pdfs(self, url: str, title: str = "") -> tuple[str, list[str]]:
        """Fetch detail page, extract PDF links from script or iframes."""
        try:
            resp = await self._get(url)
            html = resp.text
            soup = BeautifulSoup(html, 'html.parser')
            
            pdf_urls = []
            
            # Strategy 1: Look for pdfDataArray in scripts (often contains multiple attachments)
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string and 'pdfDataArray' in script.string:
                    match = re.search(r'let pdfDataArray = (\[.*?\]);', script.string, re.DOTALL)
                    if match:
                        try:
                            data = json.loads(match.group(1))
                            for entry in data:
                                if 'url' in entry:
                                    pdf_urls.append(entry['url'])
                        except Exception:
                            pass
            
            # Strategy 2: Look for iframes (often used for the primary PDF preview)
            if not pdf_urls:
                iframes = soup.find_all('iframe', src=re.compile(r'\.pdf', re.IGNORECASE))
                for iframe in iframes:
                    src = iframe.get('src')
                    if src:
                        pdf_urls.append(urljoin(url, src))
            
            # Strategy 3: Look for direct download links
            if not pdf_urls:
                links = soup.find_all('a', href=re.compile(r'\.pdf', re.IGNORECASE))
                for link in links:
                    href = link.get('href')
                    if href:
                        pdf_urls.append(urljoin(url, href))

            # Deduplicate while preserving order
            pdf_urls = list(dict.fromkeys(pdf_urls))

            content_parts = []
            for pdf_url in pdf_urls[:2]: # Extract from first 2 PDFs max to avoid huge docs
                logger.debug("irdai_extracting_pdf", pdf_url=pdf_url)
                pdf_content = await self._fetch_pdf_content(pdf_url, title=title)
                if pdf_content:
                    content_parts.append(pdf_content)
            
            content = "\n\n".join(content_parts)
            
            if not content:
                # Fallback to HTML extraction
                main_section = soup.find('section', id='pdfContainer') or soup.find('div', class_='main')
                if main_section:
                    content = await self._parser.extract(str(main_section), "text/html")
                else:
                    content = await self._parser.extract(html, "text/html")
            
            return content, pdf_urls
            
        except Exception as exc:
            logger.warning("irdai_detail_fetch_failed", url=url, error=str(exc))
            return "", []
