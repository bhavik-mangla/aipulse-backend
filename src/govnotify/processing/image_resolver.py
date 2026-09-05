"""
Image Resolution Logic.
Resolves a representative image URL for a news item using a 5-tier fallback:
1. Article metadata (og:image) - all sources
2. Wikipedia page image - from the entity the summarizer identified
3. DuckDuckGo image search - fallback for that entity
4. Source-specific logo, where one is bundled
5. Nothing, and the app falls back to its own placeholder

"""
from __future__ import annotations

import asyncio
import httpx
import re
import structlog
from typing import Optional

from ddgs import DDGS

from govnotify.config import get_settings
from govnotify.models.source import RawDocument

logger = structlog.get_logger(__name__)

WIKIPEDIA_USER_AGENT = (
    "AIPulse/1.0 (news aggregator; https://github.com/bhavik-mangla/aipulse-backend)"
)

# Mapping of source_id to local static logo URLs
# These are used as Tier 3 fallbacks
SOURCE_LOGOS = {
    "et_top_stories": "/static/logos/et_top_stories.png",
    "mint_top_stories": "/static/logos/mint_top_stories.png",
    "bs_top_stories": "/static/logos/bs_top_stories.png",
}

def is_news_source(source_id: str) -> bool:
    """
    Whether a source is eligible for entity image search.

    Every source is now a news outlet, so this is always true. It is kept as a
    named predicate because it replaced a hardcoded allow-list of three Indian
    outlets, and keeping the seam makes it obvious where to reintroduce a
    restriction rather than scattering source ids through the resolver again.
    """
    return bool(source_id)

# Domains to ignore in search results (stock photo sites that return generic/sus images)
DOMAIN_BLACKLIST = {
    "photolibrary.jp",
    "shutterstock.com",
    "gettyimages.com",
    "dreamstime.com",
    "123rf.com",
    "istockphoto.com",
    "adobe.com",
    "depositphotos.com"
}

class ImageResolver:
    """Resolves image URLs for processed documents."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def resolve_image(self, raw_doc: RawDocument, search_query: Optional[str] = None) -> Optional[str]:
        """
        Main entry point to resolve an image for a document.
        """
        source_id = raw_doc.source_id

        # Tier 1: Metadata from Crawler (Fastest, most accurate)
        image_url = self._extract_from_metadata(raw_doc)
        if image_url:
            logger.info("image_resolved_metadata", source_id=source_id, url=image_url)
            return image_url

        # Tier 2: Wikipedia Page Image (Only for allowed news sources)
        if search_query and is_news_source(source_id):
            image_url = await self._search_wikipedia_image(search_query)
            if image_url:
                logger.info("image_resolved_wikipedia", query=search_query, url=image_url)
                return image_url

        # Tier 3: DuckDuckGo Images (Only for allowed news sources)
        if search_query and is_news_source(source_id):
            # Append 'official' to query if it's a person/character to get better results
            refined_query = search_query
            if len(search_query.split()) >= 2:
                 refined_query = f"{search_query} official"
            
            image_url = await self._search_duckduckgo_images(refined_query)
            if image_url:
                logger.info("image_resolved_ddg", query=refined_query, url=image_url)
                return image_url

        # Tier 4: Source-specific Logo (Reliable fallback for official sources)
        logo_url = SOURCE_LOGOS.get(source_id)
        if logo_url:
            logger.info("image_resolved_logo", source_id=source_id, url=logo_url)
            return logo_url

        # Tier 5: Default Fallback (Frontend logic uses assets/icon.png)
        return None

    def _extract_from_metadata(self, raw_doc: RawDocument) -> Optional[str]:
        """Check metadata for image URLs (og:image, twitter:image, etc.)"""
        meta = raw_doc.metadata or {}
        image_keys = ["image_url", "og:image", "thumbnail", "lead_image_url", "hero_image"]
        for key in image_keys:
            val = meta.get(key)
            if val and isinstance(val, str) and val.startswith("http"):
                return val
        return None

    async def _search_wikipedia_image(self, query: str) -> Optional[str]:
        """Search Wikipedia for a representative page image."""
        url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query,
            "gsrlimit": 1,
            "prop": "pageimages",
            "piprop": "original",
        }
        # Wikipedia asks for a contact in the User-Agent and throttles
        # requests that use a placeholder address.
        headers = {"User-Agent": WIKIPEDIA_USER_AGENT}
        
        try:
            async with httpx.AsyncClient(headers=headers, timeout=5.0) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    logger.warning("wikipedia_search_failed_status", query=query, status=resp.status_code)
                    return None
                
                data = resp.json()
                pages = data.get("query", {}).get("pages", {})
                for page_id, page_data in pages.items():
                    image_url = page_data.get("original", {}).get("source")
                    if image_url:
                        return image_url
        except Exception as e:
            logger.warning("wikipedia_search_error", query=query, error=str(e))
        
        return None

    def _sync_ddg_search(self, query: str, proxy: Optional[str] = None) -> Optional[str]:
        """Synchronous search function to be run in a thread with optional proxy support."""
        try:
            with DDGS(proxy=proxy, timeout=10) as ddgs:
                results = ddgs.images(
                    query=query,
                    region="wt-wt",
                    safesearch="on",
                    max_results=10 # Increased to allow filtering
                )
                if results:
                    # Prefer standard image formats and filter domains
                    for res in results:
                        img_url = res.get("image")
                        if not img_url:
                            continue
                        
                        # Filter out blacklisted domains
                        domain_match = re.search(r"https?://([^/]+)", img_url)
                        if domain_match:
                            domain = domain_match.group(1).lower()
                            if any(blacklisted in domain for blacklisted in DOMAIN_BLACKLIST):
                                continue

                        if any(img_url.lower().split('?')[0].endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                            return img_url
                    
                    # If all filtered, return first result that isn't blacklisted (if any)
                    return results[0].get("image")
        except Exception as e:
            # Re-raise to let the caller know it failed (so they can mark proxy as bad)
            raise e
        return None

    async def _search_duckduckgo_images(self, query: str) -> Optional[str]:
        """Use DuckDuckGo to find a relevant image using a thread pool and rotating proxies."""
        from govnotify.sources.proxy_manager import proxy_manager

        max_attempts = 3
        for attempt in range(max_attempts):
            proxy = await proxy_manager.get_proxy()
            
            if proxy:
                logger.info("ddg_search_attempt", query=query, attempt=attempt+1, proxy=proxy)
            else:
                logger.info("ddg_search_attempt_no_proxy", query=query, attempt=attempt+1)

            try:
                image_url = await asyncio.to_thread(self._sync_ddg_search, query, proxy)
                if image_url:
                    return image_url
            except Exception as e:
                logger.warning("ddg_search_attempt_failed", query=query, attempt=attempt+1, error=str(e), proxy=proxy)
                if proxy:
                    await proxy_manager.mark_bad_proxy(proxy)
            
            if attempt < max_attempts - 1:
                await asyncio.sleep(1) # Small delay before next proxy attempt
        
        logger.warning("ddg_search_all_attempts_failed", query=query)
        return None
