"""
Income Tax notifications source.
Scrapes the Income Tax India website using Liferay's Headless API for 100% deterministic mapping.

Strategy:
1. Use Headless Structured Contents API to fetch items from multiple categories.
2. Categories: Notification (37788), Circulars (37776), Press Release (37794), Others (37791).
3. Extract definitive PDF URLs directly from JSON metadata (reportFile or documentContent).
"""
from __future__ import annotations

import re
import asyncio
from datetime import datetime
from typing import AsyncIterator

import structlog

from govnotify.models.source import RawDocument, SourceConfig, SourceType
from govnotify.sources.registry import SourceRegistry
from govnotify.sources.base import WebScrapeSource

logger = structlog.get_logger(__name__)

INCOME_TAX_BASE_URL = "https://www.incometaxindia.gov.in"
SITE_ID = "20117"

# Proven Category IDs
CATEGORIES = {
    "37788": "Notification",
    "37776": "Circular",
    "37794": "Press Release",
    "37791": "Others",
    "6386665": "Miscellaneous Communication"
}

@SourceRegistry.register
class IncomeTaxSource(WebScrapeSource):
    """Deterministic Income Tax scraper using Liferay Headless API."""

    def __init__(self) -> None:
        super().__init__(SourceConfig(
            id="income_tax",
            name="Income Tax Notifications & Circulars",
            url=f"{INCOME_TAX_BASE_URL}/notifications",
            source_type=SourceType.WEB_SCRAPE,
            schedule_cron="0 18 * * *",
            region_tags=["national"],
            language="en",
            crawler_class="govnotify.crawlers.base.BaseCrawler", # Using base as we use direct API
            rate_limit_rpm=20,
            crawler_config={"limit": 50}
        ))

    async def fetch(
        self, since: datetime | None = None
    ) -> AsyncIterator[RawDocument]:
        """Fetch latest items across all relevant categories via Headless API."""
        logger.info("income_tax_api_fetch_start", since=str(since) if since else "latest")
        
        # High-quality headers to avoid 403/503
        api_headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0",
            "Accept": "application/json",
            "Referer": f"{INCOME_TAX_BASE_URL}/notifications"
        }

        yielded = 0
        limit = self._config.crawler_config.get("limit", 50)
        seen_hashes = set()

        # Iterate through proven categories
        for cat_id, cat_name in CATEGORIES.items():
            logger.info("income_tax_fetching_category", category=cat_name, id=cat_id)
            
            api_url = f"{INCOME_TAX_BASE_URL}/o/headless-delivery/v1.0/sites/{SITE_ID}/structured-contents"
            params = {
                "flatten": "true",
                "pageSize": 20,
                "sort": "dateModified:desc",
                "filter": f"taxonomyCategoryIds/any(t:t eq {cat_id})"
            }

            try:
                resp = await self._get(api_url, params=params, headers=api_headers)
                items = resp.json().get('items', [])
                
                for item in items:
                    try:
                        title = item.get('title', '').strip()
                        if not title: continue

                        # 1. Deterministic PDF URL Extraction from Metadata
                        pdf_url = self._extract_pdf_from_meta(item)
                        
                        # 2. Content Fallback (extracting text from description/content if no PDF)
                        content = title
                        content_type = "text/html"
                        
                        if pdf_url:
                            # Pass title to leverage early deduplication check in base.py
                            extracted_pdf = await self._fetch_pdf_content(pdf_url, title=title)
                            if extracted_pdf == "DUPLICATE_SKIPPED":
                                continue
                            if extracted_pdf:
                                content = extracted_pdf
                                content_type = "application/pdf"
                        else:
                            # Fallback: Use HTML/Plain text content from fields if PDF is missing
                            # Prioritize documentContent for items that have no PDF attachment
                            desc = (
                                self._get_field_value(item, "documentContent") or 
                                self._get_field_value(item, "description") or 
                                self._get_field_value(item, "shortDescription")
                            )
                            if desc:
                                content = desc
                                content_type = "text/html"

                        fetch_url = pdf_url or item.get('itemURL')
                        if not fetch_url:
                            # Fallback to API URL if no portal URL is found to avoid validation error
                            article_id = item.get('id')
                            fetch_url = f"{INCOME_TAX_BASE_URL}/o/headless-delivery/v1.0/structured-contents/{article_id}"

                        doc = self.create_raw_document(
                            title=title,
                            fetch_url=fetch_url,
                            raw_content=content,
                            content_type=content_type,
                            metadata={
                                "category": cat_name,
                                "portal_url": str(self._config.url),
                                "article_id": item.get('id'),
                                "date_modified": item.get('dateModified')
                            },
                        )

                        if doc.content_hash not in seen_hashes and await self.validate_response(doc):
                            seen_hashes.add(doc.content_hash)
                            yield doc
                            yielded += 1
                            if yielded >= limit:
                                return
                    except Exception as item_exc:
                        logger.error("income_tax_item_failed", title=item.get('title'), error=str(item_exc))
                        continue

            except Exception as exc:
                logger.error("income_tax_category_failed", category=cat_name, error=str(exc))
                continue

        logger.info("income_tax_complete", total_yielded=yielded)

    def _extract_pdf_from_meta(self, item: dict) -> str | None:
        """Recursively find the definitive PDF URL in Liferay metadata."""
        fields = item.get('contentFields', [])
        
        # Priority 1: reportFile field (direct document library link)
        for f in fields:
            if f['name'] == 'reportFile' and f['contentFieldValue'].get('document'):
                return f"{INCOME_TAX_BASE_URL}{f['contentFieldValue']['document']['contentUrl']}"

        # Priority 2: documentContent or description (regex search)
        for f in fields:
            if f['name'] in ['documentContent', 'description', 'shortDescription']:
                data = str(f['contentFieldValue'].get('data', ''))
                match = re.search(r'/documents/[^\s"\'<>]+', data)
                if match:
                    return f"{INCOME_TAX_BASE_URL}{match.group(0)}"

        # Priority 3: externalPortalLink
        for f in fields:
            if f['name'] == 'externalPortalLink' and f['contentFieldValue'].get('data'):
                return f['contentFieldValue']['data']

        return None

    def _get_field_value(self, item: dict, field_name: str) -> str | None:
        """Helper to get a field's raw data."""
        for f in item.get('contentFields', []):
            if f['name'] == field_name:
                return f['contentFieldValue'].get('data')
        return None
