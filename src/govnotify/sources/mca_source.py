"""
MCA (Ministry of Corporate Affairs) source.
Uses reverse-engineered backend APIs to fetch notifications and circulars.
This bypasses the dynamic frontend and uses direct metadata and document endpoints.

API Strategy:
1. Fetch metadata: /bin/ebook/service/documentMetadata?docCategory={cat}&flag=initial&status=Current
2. Document link is a numeric ID.
3. Download PDF: /bin/ebook/dms/getdocument?doc={base64_id}&docCategory={cat}
"""
from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timezone
from typing import AsyncIterator
from urllib.parse import urlencode

import structlog

from govnotify.models.source import RawDocument, SourceConfig, SourceType
from govnotify.sources.registry import SourceRegistry
from govnotify.sources.base import WebScrapeSource, SourceFetchError
from govnotify.sources.utils import clean_text, parse_indian_date

logger = structlog.get_logger(__name__)

MCA_BASE_URL = "https://www.mca.gov.in"
MCA_METADATA_API = f"{MCA_BASE_URL}/bin/ebook/service/documentMetadata"
MCA_DOCUMENT_API = f"{MCA_BASE_URL}/bin/ebook/dms/getdocument"


@SourceRegistry.register
class MCASource(WebScrapeSource):
    """MCA (Ministry of Corporate Affairs) API-driven source."""

    def __init__(self) -> None:
        super().__init__(SourceConfig(
            id="mca_updates",
            name="MCA Updates",
            url="https://www.mca.gov.in/content/mca/global/en/acts-rules/ebooks/notifications.html",
            source_type=SourceType.WEB_SCRAPE,
            schedule_cron="0 */12 * * *",
            region_tags=["national"],
            language="en",
            crawler_class="govnotify.sources.mca_source.MCASource",
            rate_limit_rpm=20,
        ))
        # Updated headers based on successful user trace
        self._headers.update({
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Mobile Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.mca.gov.in/content/mca/global/en/acts-rules/ebooks/notifications.html",
        })
        self._categories = ["Notifications", "Circulars"]

    async def fetch(
        self, since: datetime | None = None
    ) -> AsyncIterator[RawDocument]:
        """Fetch documents using Playwright to execute API calls from browser context."""
        from playwright.async_api import async_playwright
        from playwright_stealth.stealth import Stealth
        
        logger.info("mca_fetch_start", since=str(since) if since else "latest")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            # Use specific headers from successful user trace
            ua = self._headers["User-Agent"]
            context = await browser.new_context(
                user_agent=ua,
                viewport={"width": 360, "height": 640},
                is_mobile=True,
                extra_http_headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Accept-Language": "en-GB,en;q=0.7",
                    "sec-ch-ua": '"Not:A-Brand";v="99", "Brave";v="145", "Chromium";v="145"',
                    "sec-ch-ua-mobile": "?1",
                    "sec-ch-ua-platform": '"Android"',
                    "sec-gpc": "1",
                    "dnt": "1"
                }
            )
            page = await context.new_page()
            
            # Apply stealth
            stealth = Stealth()
            await stealth.apply_stealth_async(page)
            
            # Block detection scripts
            await page.route("**/clientlib-devtool.js", lambda route: route.abort())
            
            try:
                # Establish session by visiting the notifications page
                await page.goto(str(self._config.url), wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(5)
                
                yielded = 0
                for category in self._categories:
                    logger.debug("mca_fetching_metadata_via_browser", category=category)
                    
                    try:
                        # Call the API from within the browser context
                        eval_result = await page.evaluate("""
                            async (category) => {
                                try {
                                    const res = await fetch(
                                        `/bin/ebook/service/documentMetadata?docCategory=${category}&flag=initial&status=Current`,
                                        {
                                            headers: {
                                                'x-requested-with': 'XMLHttpRequest'
                                            }
                                        }
                                    );
                                    if (!res.ok) return { error: `HTTP ${res.status}`, status: res.status };
                                    const data = await res.json();
                                    return { data: data };
                                } catch (e) {
                                    return { error: e.message };
                                }
                            }
                        """, category)
                        
                        if eval_result.get("error"):
                            logger.warning("mca_browser_fetch_failed", category=category, error=eval_result["error"], status=eval_result.get("status"))
                            continue
                        data = eval_result.get("data")
                    except Exception as e:
                        logger.warning("mca_evaluate_failed", category=category, error=str(e))
                        continue

                    if data is None or not isinstance(data, dict) or "data" not in data:
                        logger.warning("mca_unexpected_response", category=category)
                        continue
                    
                    items = data["data"]
                    if not isinstance(items, list):
                        continue

                    for item in items:
                        title = item.get("docName", "")
                        date_str = item.get("notificationdate", "")
                        doc_id = item.get("link", "")
                        
                        if not doc_id or not title:
                            continue

                        # Base64 encode the link ID
                        encoded_id = base64.b64encode(str(doc_id).encode()).decode()
                        pdf_url = f"{MCA_DOCUMENT_API}?doc={encoded_id}&docCategory={category}&type=open"
                        
                        logger.debug("mca_extracting_pdf_via_browser", doc_id=doc_id)
                        
                        # Fetch PDF bytes inside browser context to bypass 403
                        try:
                            # Pre-check for duplicate title/source via shared helper logic
                            # We simulate it here since we fetch via Playwright
                            partial_doc = self.create_raw_document(title=clean_text(title), fetch_url=pdf_url, raw_content=title)
                            is_dup, _ = await self.check_duplicate(partial_doc)
                            if is_dup:
                                logger.info("mca_skip_duplicate_pre_fetch", title=title[:50])
                                yield partial_doc
                                yielded += 1
                                continue

                            pdf_base64 = await page.evaluate("""
                                async (url) => {
                                    try {
                                        const res = await fetch(url);
                                        if (!res.ok) return null;
                                        const buffer = await res.arrayBuffer();
                                        const bytes = new Uint8Array(buffer);
                                        let binary = '';
                                        for (let i = 0; i < bytes.byteLength; i++) {
                                            binary += String.fromCharCode(bytes[i]);
                                        }
                                        return btoa(binary);
                                    } catch (e) {
                                        return null;
                                    }
                                }
                            """, pdf_url)
                            
                            content = ""
                            if pdf_base64:
                                pdf_bytes = base64.b64decode(pdf_base64)
                                content = await self._parser.extract_pdf_from_bytes(pdf_bytes)
                        except Exception as e:
                            logger.warning("mca_pdf_fetch_failed", doc_id=doc_id, error=str(e))
                            content = ""
                        
                        doc = self.create_raw_document(
                            title=clean_text(title),
                            fetch_url=pdf_url,
                            raw_content=content or title,
                            content_type="application/pdf" if content else "text/html",
                            metadata={
                                "doc_id": doc_id,
                                "category": category,
                                "description": item.get("shortDescription", ""),
                                "portal_url": str(self._config.url)
                            }
                        )

                        if await self.validate_response(doc):
                            yield doc
                            yielded += 1
                        
                        if yielded >= 30:
                            break
                    
                    if yielded >= 30:
                        break

                logger.info("mca_fetch_complete", yielded=yielded)
                
            except Exception as exc:
                raise SourceFetchError(
                    source_id=self.source_id,
                    message=f"Failed to fetch MCA updates via Playwright: {exc}",
                    cause=exc,
                ) from exc
            finally:
                await browser.close()
