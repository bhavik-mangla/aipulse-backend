"""
Abstract source interface and exceptions.
Defines the AbstractSource ABC that every data source must implement, plus custom exceptions for source-related errors.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import AsyncIterator, Any, Optional, Callable, Awaitable
from contextlib import asynccontextmanager

import asyncio
import httpx
import structlog

from govnotify.models.source import RawDocument, SourceConfig
from govnotify.exceptions import SourceFetchError # noqa: F401 re-export
from govnotify.crawlers.rate_limiter import CrawlerRateLimiter
from govnotify.processing.parser import TextParser
from govnotify.sources.utils import get_standard_headers

logger = structlog.get_logger(__name__)


class AbstractSource(ABC):
    """Base interface for all data sources. Implement this to add a new source."""

    def __init__(self) -> None:
        self.is_duplicate_callback: Optional[Callable[[RawDocument], Awaitable[tuple[bool, str | None]]]] = None

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Unique identifier for this source."""
        pass

    @property
    @abstractmethod
    def source_config(self) -> SourceConfig:
        """Configuration for this source."""
        pass

    @abstractmethod
    async def fetch(self, since: datetime | None = None) -> AsyncIterator[RawDocument]:
        """
        Fetch new documents from this source.
        Args:
            since: Check for new documents. Time-based gating is now handled primarily by ingested_at.
        Yields:
            RawDocument instances with content_hash already computed.
        Raises:
            SourceFetchError: If the source is unreachable or returns errors.
        """
        pass

    async def check_duplicate(self, doc: RawDocument) -> tuple[bool, str | None]:
        """Helper to check if a document is a duplicate via callback."""
        if self.is_duplicate_callback:
            return await self.is_duplicate_callback(doc)
        return False, None

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if this source is accessible and responding correctly."""
        pass

    async def validate_response(self, response: RawDocument) -> bool:
        """
        Validate that a fetched document meets minimum quality standards.
        Args:
            response: A RawDocument to validate.
        Returns:
            True if the document passes quality checks.
        """
        if not response.title or len(response.title) < 5:
            return False
        # Relax content length check for some sources, but 50 is a good baseline
        if not response.raw_content or len(response.raw_content) < 20:
            return False
        return True


class WebScrapeSource(AbstractSource, ABC):
    """
    Base class for sources that involve scraping government websites.
    Provides standardized rate-limiting, PDF extraction, and HTTP client management.
    """

    def __init__(self, config: SourceConfig) -> None:
        super().__init__()
        self._config = config
        self._rate_limiter = CrawlerRateLimiter(
            rpm=config.rate_limit_rpm,
            max_concurrent=config.crawler_config.get("max_concurrent", 3)
        )
        self._parser = TextParser()
        self._headers = get_standard_headers()
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def source_id(self) -> str:
        return self._config.id

    @property
    def source_config(self) -> SourceConfig:
        return self._config

    @asynccontextmanager
    async def session(self):
        """Context manager to maintain a persistent HTTP session during fetch."""
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers=self._headers,
            http2=True # Enable HTTP/2 for better performance/stealth if supported
        ) as client:
            self._client = client
            try:
                yield client
            finally:
                self._client = None

    async def _get(self, url: str, **kwargs) -> httpx.Response:
        """Rate-limited GET request with proxy rotation and smart fallback."""
        from govnotify.sources.proxy_manager import proxy_manager
        
        max_retries = kwargs.pop("max_retries", 3)
        backoff_factor = kwargs.pop("backoff_factor", 2.0)
        use_proxy = kwargs.pop("use_proxy", False)
        
        last_exc = None
        for attempt in range(max_retries):
            current_headers = {**self._headers, **kwargs.get("headers", {})}
            # Rotate User-Agent on retries
            if attempt > 0:
                current_headers["User-Agent"] = get_standard_headers()["User-Agent"]
            
            try:
                async with self._rate_limiter:
                    # Logic:
                    # 1. First attempt: Direct (unless use_proxy is forced)
                    # 2. Subsequent attempts: Try different proxies
                    # 3. Final attempt: Try direct as a last resort
                    
                    proxy = None
                    if use_proxy or (attempt > 0 and attempt < max_retries - 1):
                        proxy = await proxy_manager.get_proxy()
                        if proxy:
                            logger.info("using_proxy_retry", url=url, proxy=proxy, attempt=attempt+1)
                    
                    client_kwargs = {
                        "follow_redirects": True,
                        "timeout": 30.0,
                        "headers": current_headers,
                        "http2": not proxy, # Disable HTTP/2 for free proxies
                    }
                    if proxy:
                        client_kwargs["proxy"] = proxy
                        
                    async with httpx.AsyncClient(**client_kwargs) as client:
                        resp = await client.get(url, **kwargs)
                    
                    if resp.status_code in (429, 503, 418):
                        self._rate_limiter.backoff(attempt + 1)
                        use_proxy = True # Force proxy on next attempt
                    
                    resp.raise_for_status()
                    return resp
                    
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_exc = exc
                status_code = getattr(exc.response, 'status_code', None) if isinstance(exc, httpx.HTTPStatusError) else None
                
                error_msg = str(exc).lower()
                # If we get a "Malformed reply" while using a proxy, it means the PROXY is bad.
                # We should continue to next retry to get a DIFFERENT proxy.
                if "malformed reply" in error_msg and proxy:
                    logger.warning("bad_proxy_detected_malformed_reply", url=url, proxy=proxy)
                
                is_retryable = (
                    not isinstance(exc, httpx.HTTPStatusError) or 
                    status_code in (418, 429, 403, 503) or 
                    (status_code and status_code >= 500)
                )
                
                if not is_retryable:
                    logger.error("non_retryable_error", url=url, status=status_code, error=str(exc))
                    break
                
                # If blocked, enable proxy for next attempt
                if status_code in (418, 429, 403):
                    use_proxy = True
                
                wait_time = backoff_factor ** attempt
                logger.warning("source_http_get_retry", url=url, attempt=attempt+1, error=repr(exc), wait=wait_time, proxy=use_proxy)
                await asyncio.sleep(wait_time)
            except Exception as exc:
                last_exc = exc
                logger.error("unexpected_error_during_get", url=url, error=str(exc))
                break

        logger.error("source_http_get_failed", url=url, error=str(last_exc))
        raise SourceFetchError(
            source_id=self.source_id,
            message=f"HTTP GET failed for {url} after {max_retries} attempts: {last_exc}",
            cause=last_exc
        ) from last_exc

    async def _fetch_pdf_content(self, url: str, title: str = "", **kwargs) -> str:
        """Download and extract text from a PDF, with early deduplication check and HTML fallback."""
        if title:
            # Check if title already exists before downloading PDF
            partial_doc = self.create_raw_document(title=title, fetch_url=url, raw_content=title)
            is_dup, _ = await self.check_duplicate(partial_doc)
            if is_dup:
                logger.info("skip_expensive_pdf_fetch_duplicate", title=title[:50], url=url)
                return "DUPLICATE_SKIPPED"

        try:
            resp = await self._get(url, **kwargs)
            content_type = resp.headers.get("Content-Type", "").lower()
            
            # If we expected a PDF but got HTML, it's likely a landing page
            if "html" in content_type:
                logger.info("received_html_instead_of_pdf_using_fallback", url=url)
                return await self._parser.extract(resp.text, "text/html")
                
            return await self._parser.extract_pdf_from_bytes(resp.content)
        except Exception as exc:
            logger.warning("source_pdf_extraction_failed", url=url, error=str(exc))
            return ""

    async def _fetch_html_content(self, url: str, title: str = "", selector: str | None = None, **kwargs) -> str:
        """Fetch and extract text from an HTML page, with early deduplication check."""
        if title:
            # Check if title already exists before fetching HTML
            partial_doc = self.create_raw_document(title=title, fetch_url=url, raw_content=title)
            is_dup, _ = await self.check_duplicate(partial_doc)
            if is_dup:
                logger.info("skip_expensive_html_fetch_duplicate", title=title[:50], url=url)
                return "DUPLICATE_SKIPPED"

        try:
            resp = await self._get(url, **kwargs)
            return await self._parser.extract(resp.text, "text/html")
        except Exception as exc:
            logger.warning("source_html_extraction_failed", url=url, error=str(exc))
            return ""

    async def health_check(self) -> bool:
        """Default health check: try to GET the base URL."""
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(str(self._config.url), headers=self._headers)
                return resp.status_code < 400
        except Exception:
            return False

    def create_raw_document(
        self,
        title: str,
        fetch_url: str,
        raw_content: str,
        content_type: str = "text/html",
        metadata: dict[str, Any] | None = None
    ) -> RawDocument:
        """Helper to create a RawDocument with standard defaults."""
        doc = RawDocument(
            source_id=self.source_id,
            source_url=self._config.url,
            fetch_url=fetch_url,
            title=title,
            raw_content=raw_content or title, # Fallback to title if content is empty
            content_type=content_type,
            language=self._config.language,
            metadata=metadata or {}
        )
        doc.compute_content_hash()
        return doc
