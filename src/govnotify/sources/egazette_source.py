"""
Central e-Gazette source using SearchNotificationDate.aspx.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import AsyncIterator

import httpx
import structlog
from bs4 import BeautifulSoup

from govnotify.models.source import RawDocument, SourceConfig, SourceType
from govnotify.sources.registry import SourceRegistry
from govnotify.sources.base import WebScrapeSource
from govnotify.sources.utils import parse_indian_date
from govnotify.utils.time import get_utc_now

logger = structlog.get_logger(__name__)

EGAZETTE_BASE = "https://egazette.gov.in"


@SourceRegistry.register
class GazetteSource(WebScrapeSource):
    def __init__(self) -> None:
        super().__init__(SourceConfig(
            id="egazette_central",
            name="Central e-Gazette",
            url=EGAZETTE_BASE + "/default.aspx",
            source_type=SourceType.WEB_SCRAPE,
            schedule_cron="0 */12 * * *",
            region_tags=["national"],
            language="en",
            crawler_class="httpx_direct",
            rate_limit_rpm=10,
            crawler_config={"limit": 50, "days_back": 2}
        ))

    async def fetch(
        self, since: datetime | None = None
    ) -> AsyncIterator[RawDocument]:
        logger.info("egazette_fetch_start_search", since=str(since) if since else "latest")
        
        total_yielded = 0
        limit = self._config.crawler_config.get("limit", 200)

        # We use a custom client here because of the session token in the URL
        async with httpx.AsyncClient(headers=self._headers, follow_redirects=True, timeout=90.0) as client:
            try:
                # 1. Establish Session
                resp = await client.get(EGAZETTE_BASE + "/")
                home_url = str(resp.url)
                token_match = re.search(r'/\(S\([^)]+\)\)/', home_url)
                session_token = token_match.group(0) if token_match else "/"
                
                # 2. Get Search Menu Hiddens
                menu_url = f"{EGAZETTE_BASE}{session_token}SearchMenu.aspx"
                resp = await client.get(menu_url, headers={"Referer": home_url})
                soup_menu = BeautifulSoup(resp.text, 'html.parser')
                hiddens_menu = self._extract_all_hiddens(soup_menu)
                
                # 3. Trigger Search by Notification Date to get Dynamic ID
                payload_menu = {**hiddens_menu, "btnNotification": "Search by Notification Date"}
                resp = await client.post(menu_url, data=payload_menu, headers={"Referer": menu_url})
                search_url = str(resp.url)
                
                if "SearchNotificationDate.aspx" not in search_url:
                    logger.error("egazette_search_page_not_found", final_url=search_url)
                    return

                # 4. Prepare Search Range
                lookback_days = self._config.crawler_config.get("days_back", 3)
                if not since:
                    lookback_days = 30 # Initial fetch
                
                end_date = get_utc_now()
                start_date = end_date - timedelta(days=lookback_days)
                
                current_date = start_date
                while current_date <= end_date:
                    if total_yielded >= limit: break
                    
                    date_str = current_date.strftime("%d-%b-%Y")
                    logger.info("egazette_searching_date", date=date_str)
                    
                    resp = await client.get(search_url, headers={"Referer": menu_url})
                    soup_search = BeautifulSoup(resp.text, 'html.parser')
                    hiddens_search = self._extract_all_hiddens(soup_search)
                    
                    payload_search = {
                        "__EVENTTARGET": "",
                        "__EVENTARGUMENT": "",
                        "__VIEWSTATE": hiddens_search.get("__VIEWSTATE", ""),
                        "__VIEWSTATEGENERATOR": hiddens_search.get("__VIEWSTATEGENERATOR", ""),
                        "__VIEWSTATEENCRYPTED": "",
                        "__EVENTVALIDATION": hiddens_search.get("__EVENTVALIDATION", ""),
                        "hidden1": hiddens_search.get("hidden1", ""),
                        "txtDateFrom": date_str,
                        "txtDateTo": date_str,
                        "ImgSubmit.x": "47",
                        "ImgSubmit.y": "13"
                    }
                    
                    resp = await client.post(search_url, data=payload_search, headers={"Referer": search_url})
                    soup_results = BeautifulSoup(resp.text, 'html.parser')
                    table = soup_results.find("table", id="gvGazetteList")
                    
                    if not table:
                        current_date += timedelta(days=1)
                        continue

                    rows = table.find_all("tr")
                    for row in rows[1:]: # Skip header
                        if total_yielded >= limit: break
                        
                        cols = row.find_all("td")
                        if len(cols) < 10: continue
                        
                        ministry = cols[1].get_text(strip=True)
                        subject = cols[4].get_text(strip=True)
                        category = cols[5].get_text(strip=True)
                        issue_date_str = cols[7].get_text(strip=True)
                        publish_date_str = cols[8].get_text(strip=True)
                        gazette_id = cols[9].get_text(strip=True)
                        
                        if not gazette_id or not re.search(r'[A-Z0-9]+-[A-Z0-9-]+-\d+', gazette_id):
                            continue

                        issue_at = parse_indian_date(issue_date_str)
                        publish_at = parse_indian_date(publish_date_str)

                        title = f"[{category}] {ministry}: {subject}"[:400]
                        
                        # Extract PDF URL from ID using robust pattern matching
                        year, doc_num = None, None
                        
                        # Try long format first: ...-YYYY-NNNNN
                        long_match = re.search(r'-(\d{4})-(\d+)$', gazette_id)
                        if long_match:
                            year, doc_num = long_match.groups()
                        else:
                            # Fallback to short format: ...-NNNNN
                            short_match = re.search(r'-(\d+)$', gazette_id)
                            if short_match:
                                doc_num = short_match.group(1)
                                year = str(publish_at.year) if publish_at else None

                        if not (year and doc_num):
                            logger.warning("egazette_invalid_id_format", gazette_id=gazette_id)
                            continue
                            
                        pdf_url = f"{EGAZETTE_BASE}/WriteReadData/{year}/{doc_num}.pdf"
                        
                        content = await self._fetch_pdf_content_custom_client(client, pdf_url, title=title)
                        
                        if content == "DUPLICATE_SKIPPED":
                            continue
                        
                        doc = self.create_raw_document(
                            title=title,
                            fetch_url=pdf_url,
                            raw_content=content,
                            content_type="application/pdf",
                            metadata={
                                "gazette_id": gazette_id,
                                "ministry": ministry,
                                "issue_date": issue_date_str,
                                "publish_date": publish_date_str,
                                "portal_url": f"{EGAZETTE_BASE}/default.aspx"
                            }
                        )

                        if await self.validate_response(doc):
                            yield doc
                            total_yielded += 1
                    
                    current_date += timedelta(days=1)

            except Exception as e:
                logger.error("egazette_fetch_failed", error=str(e))

        logger.info("egazette_fetch_complete", yielded=total_yielded)

    async def _fetch_pdf_content_custom_client(self, client: httpx.AsyncClient, url: str, title: str = "") -> str:
        """Download and extract PDF using the already established session client with retries."""
        if title:
            partial_doc = self.create_raw_document(title=title, fetch_url=url, raw_content=title)
            is_dup, _ = await self.check_duplicate(partial_doc)
            if is_dup:
                logger.info("egazette_skip_duplicate_pre_fetch", title=title[:50])
                return "DUPLICATE_SKIPPED"

        max_retries = 3
        backoff_factor = 2.0
        
        for attempt in range(max_retries):
            try:
                resp = await client.get(url, timeout=60.0)
                resp.raise_for_status()
                if b"%PDF" in resp.content[:100]:
                    return await self._parser.extract_pdf_from_bytes(resp.content)
                else:
                    logger.warning("egazette_not_a_pdf", url=url, content_start=resp.content[:50])
                    return ""
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500 and exc.response.status_code != 429:
                    break # Don't retry 4xx errors except 429
                
                wait_time = backoff_factor ** attempt
                logger.warning("egazette_pdf_retry", url=url, attempt=attempt+1, error=str(exc), wait=wait_time)
                await asyncio.sleep(wait_time)
            except Exception as exc:
                logger.warning("egazette_pdf_failed_unrecoverable", url=url, error=str(exc))
                break
        return ""

    def _extract_all_hiddens(self, soup: BeautifulSoup) -> dict[str, str]:
        return {tag.get("name"): tag.get("value", "") for tag in soup.find_all("input", type="hidden") if tag.get("name")}

    async def health_check(self) -> bool:
        """HEAD might fail on main page due to redirects, so try GET."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(EGAZETTE_BASE + "/", headers=self._headers)
                return resp.status_code < 400
        except Exception:
            return False
