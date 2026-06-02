"""
Robust News Crawler using curl_cffi and trafilatura.
Isolated from core shared logic to bypass aggressive anti-bot protections.
"""
import asyncio
import json
import time
from typing import Optional, Union

import feedparser
import structlog
import trafilatura
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

from govnotify.crawlers.base import AbstractCrawler, CrawlResult
from govnotify.constants import DEFAULT_USER_AGENT

logger = structlog.get_logger(__name__)

class RobustNewsCrawler(AbstractCrawler):
    """
    Crawler that impersonates a real browser to bypass Cloudflare/Akamai.
    Uses trafilatura for high-quality news extraction.
    Supports proxy rotation via ProxyManager.
    """

    def __init__(self):
        # We don't keep a persistent session here to avoid state issues between sources
        pass

    async def _fetch(self, url: str, impersonate: str = "chrome120", proxy: Optional[str] = None) -> tuple[Optional[str], int]:
        """Fetch content using browser impersonation and optional proxy."""
        try:
            proxies = None
            if proxy:
                proxies = {"http": proxy, "https": proxy}
                
            async with AsyncSession() as session:
                resp = await session.get(
                    url, 
                    impersonate=impersonate, 
                    timeout=30,
                    headers={
                        "Referer": "https://www.google.com/",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                    proxies=proxies
                )
                return resp.text, resp.status_code
        except Exception as exc:
            logger.error("robust_news_fetch_failed", url=url, error=str(exc), proxy=proxy)
            return None, 0

    def _extract_images_comprehensive(self, html: str) -> list[str]:
        """Extract all possible images using meta tags, JSON-LD, etc."""
        images = []
        try:
            soup = BeautifulSoup(html, "html.parser")
            
            # 1. OpenGraph
            for prop in ["og:image", "og:image:url", "og:image:secure_url"]:
                tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
                if tag and tag.get("content"):
                    images.append(tag.get("content"))

            # 2. Twitter Cards
            for name in ["twitter:image", "twitter:image:src"]:
                tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", property=name)
                if tag and tag.get("content"):
                    images.append(tag.get("content"))

            # 3. Link rel="image_src" (common in older ET pages)
            link_tag = soup.find("link", rel="image_src")
            if link_tag and link_tag.get("href"):
                images.append(link_tag.get("href"))

            # 4. JSON-LD
            json_ld_scripts = soup.find_all("script", type="application/ld+json")
            for script in json_ld_scripts:
                try:
                    if not script.string:
                        continue
                    data = json.loads(script.string)
                    images.extend(self._find_images_in_json_ld(data))
                except:
                    continue
            
            # 5. Schema.org Microdata (fallback)
            itemprop_image = soup.find(attrs={"itemprop": "image"})
            if itemprop_image:
                if itemprop_image.name == "meta" and itemprop_image.get("content"):
                    images.append(itemprop_image.get("content"))
                elif itemprop_image.get("src"):
                    images.append(itemprop_image.get("src"))
                elif itemprop_image.get("href"):
                    images.append(itemprop_image.get("href"))

        except Exception as e:
            logger.warning("robust_news_image_extraction_failed", error=str(e))
        
        # Deduplicate while preserving order
        return list(dict.fromkeys(images))

    def _find_images_in_json_ld(self, data: Union[dict, list]) -> list[str]:
        """Recursively find image URLs in JSON-LD data."""
        images = []
        if isinstance(data, list):
            for item in data:
                images.extend(self._find_images_in_json_ld(item))
        elif isinstance(data, dict):
            # Direct image key
            img = data.get("image")
            if img:
                if isinstance(img, str):
                    images.append(img)
                elif isinstance(img, list):
                    for i in img:
                        if isinstance(i, str): images.append(i)
                        elif isinstance(i, dict) and i.get("url"): images.append(i.get("url"))
                elif isinstance(img, dict) and img.get("url"):
                    images.append(img.get("url"))
            
            # thumbnailUrl
            thumb = data.get("thumbnailUrl")
            if thumb and isinstance(thumb, str):
                images.append(thumb)
            
            # Recurse
            for v in data.values():
                if isinstance(v, (dict, list)):
                    images.extend(self._find_images_in_json_ld(v))
        return images

    async def crawl(self, url: str, config: dict) -> Union[CrawlResult, list[CrawlResult]]:
        """
        Main entry point. If it's an RSS feed, returns a list of results.
        If it's an article URL, returns a single result.
        """
        start = time.monotonic()
        
        is_rss = config.get("is_rss", False)
        if not is_rss:
            url_low = url.lower()
            if any(ext in url_low for ext in [".rss", "/rss", "rssfeed"]):
                is_rss = True
            elif ".cms" in url_low and not any(x in url_low for x in ["articleshow", "articlelist"]):
                is_rss = True
        
        from govnotify.sources.proxy_manager import proxy_manager
        
        content = None
        status = 0
        
        # Try direct fetch first
        content, status = await self._fetch(url)
        
        # If extraction is requested (not RSS), and first attempt fails or is low quality, try with proxy
        if not is_rss and (not content or status != 200 or len(content) < 2000):
            for _ in range(2): # Try up to 2 proxies
                proxy = await proxy_manager.get_proxy()
                if not proxy: break
                logger.info("robust_news_retry_with_proxy", url=url, proxy=proxy)
                content, status = await self._fetch(url, proxy=proxy)
                if content and status == 200 and len(content) > 2000:
                    break
                await proxy_manager.mark_bad_proxy(proxy)

        if not content:
            return [] if is_rss else CrawlResult(url=url, status_code=status, content="", content_type="text/plain")

        if is_rss:
            # Parse RSS feed
            parsed = feedparser.parse(content)
            results = []
            feed_title = parsed.feed.get("title", "")
            
            for entry in parsed.entries:
                # We only return metadata for RSS entries; content is fetched later via extract()
                results.append(
                    CrawlResult(
                        url=entry.link,
                        status_code=status,
                        content=entry.get("summary", "") or entry.get("description", ""),
                        content_type="text/html",
                        metadata={
                            "title": entry.get("title", ""),
                            "published": entry.get("published", ""),
                            "author": entry.get("author", ""),
                            "feed_title": feed_title,
                        },
                        elapsed_ms=(time.monotonic() - start) * 1000
                    )
                )
            return results
        else:
            # Single article extraction
            text = trafilatura.extract(content, include_comments=False, include_tables=True)
            
            # Extract metadata for Tier 1 image resolution
            metadata = {}
            try:
                tm = trafilatura.extract_metadata(content)
                if tm:
                    metadata = {
                        "title": tm.title,
                        "author": tm.author,
                        "date": tm.date,
                        "description": tm.description,
                        "image_url": tm.image,
                        "og:image": tm.image,
                    }
                
                # Comprehensive fallback for images
                all_images = self._extract_images_comprehensive(content)
                if all_images:
                    # If trafilatura missed it or we want to ensure best one
                    if not metadata.get("image_url"):
                        metadata["image_url"] = all_images[0]
                        metadata["og:image"] = all_images[0]
                    metadata["all_images"] = all_images
            except Exception as e:
                logger.warning("robust_news_metadata_extraction_failed", url=url, error=str(e))

            # If extraction returned nothing but we have content, it might be a block page.
            if (not text or len(text) < 200) and status == 200:
                proxy = await proxy_manager.get_proxy()
                if proxy:
                    logger.info("robust_news_retry_with_proxy_low_quality", url=url, proxy=proxy)
                    proxy_content, proxy_status = await self._fetch(url, proxy=proxy)
                    if proxy_content and proxy_status == 200:
                        proxy_text = trafilatura.extract(proxy_content, include_comments=False, include_tables=True)
                        if proxy_text and (not text or len(proxy_text) > len(text)):
                            text = proxy_text
                            # Also re-extract images from proxy content if needed
                            proxy_images = self._extract_images_comprehensive(proxy_content)
                            if proxy_images and not metadata.get("image_url"):
                                metadata["image_url"] = proxy_images[0]
                                metadata["og:image"] = proxy_images[0]
                                metadata["all_images"] = proxy_images
                    else:
                        await proxy_manager.mark_bad_proxy(proxy)

            return CrawlResult(
                url=url,
                status_code=status,
                content=text or "",
                content_type="text/markdown",
                metadata=metadata,
                elapsed_ms=(time.monotonic() - start) * 1000
            )

    async def extract(self, url: str) -> Optional[CrawlResult]:
        """Convenience method for full-text extraction. Now returns CrawlResult for metadata."""
        result = await self.crawl(url, {"is_rss": False})
        if isinstance(result, CrawlResult):
            return result
        return None
