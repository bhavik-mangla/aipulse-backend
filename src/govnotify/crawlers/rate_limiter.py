"""
Crawler rate-limiting utilities.
Provides:
- TokenBucket: per-source RPM enforcement
- check_robots_txt: fetch and cache robots.txt rules
- CrawlerRateLimiter: combines semaphore + token bucket + jitter
"""
from __future__ import annotations

import asyncio
import random
import time
from urllib.parse import urlparse

import httpx
import structlog

logger = structlog.get_logger(__name__)

_USER_AGENT = "GovNotify/1.0 (government notification aggregator; contact@govnotify.in)"

# Cache robots.txt per domain (domain -> (allowed bool, timestamp float))
_robots_cache: dict[str, tuple[bool, float]] = {}
ROBOTS_CACHE_TTL = 3600  # 1 hour


class TokenBucket:
    """Token-bucket rate limiter for requests-per-minute enforcement."""

    def __init__(self, rpm: int = 30):
        self._rate = rpm / 60.0  # tokens per second
        self._tokens = float(rpm)
        self._capacity = rpm
        self._lock = asyncio.Lock()
        self._last_refill = time.monotonic()

    async def acquire(self) -> None:
        """Wait until a token is available, then consume one."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < 1.0:
                wait_time = (1.0 - self._tokens) / self._rate
                self._tokens = 0.0
                await asyncio.sleep(wait_time)
                self._last_refill = time.monotonic()
            else:
                self._tokens -= 1.0


class CrawlerRateLimiter:
    """
    Combined rate limiter for web crawlers.
    Combines:
    - asyncio.Semaphore for max concurrency
    - TokenBucket for RPM enforcement
    - Random jitter between requests
    - Exponential backoff on 429/503
    """

    def __init__(self, rpm: int = 30, max_concurrent: int = 3):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._bucket = TokenBucket(rpm)
        self._backoff_until = 0.0

    async def __aenter__(self):
        await self._semaphore.acquire()
        
        # Wait for backoff period if we were told to slow down
        now = time.monotonic()
        if self._backoff_until > now:
            await asyncio.sleep(self._backoff_until - now)
            
        await self._bucket.acquire()
        
        # Random jitter 1-3 seconds
        await asyncio.sleep(random.uniform(1.0, 3.0))
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._semaphore.release()
        return False

    def backoff(self, attempt: int):
        """Set exponential backoff for a 429/503."""
        # Delays: 2s -> 4s -> 8s -> 16s (max 5 retries)
        delay = min(2 ** (attempt + 1), 16)
        self._backoff_until = time.monotonic() + delay
        logger.warning("crawler_backoff", delay=delay, attempt=attempt)


async def check_robots_txt(url: str) -> bool:
    """
    Check if the given URL is allowed by the site's robots.txt.
    Returns True if crawling is allowed (or robots.txt is unavailable).
    Results are cached for 1 hour per domain.
    """
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    # Check cache
    cached = _robots_cache.get(domain)
    if cached and (time.monotonic() - cached[1] < ROBOTS_CACHE_TTL):
        return cached[0]

    robots_url = f"{domain}/robots.txt"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(robots_url, headers={"User-Agent": _USER_AGENT})
            
            if resp.status_code != 200:
                # No robots.txt - assume allowed
                _robots_cache[domain] = (True, time.monotonic())
                return True

            text = resp.text.lower()
            # Simple check: look for Disallow directives under User-agent: * or User-agent: govnotify
            path = parsed.path or "/"
            
            for block in text.split("user-agent:"):
                block = block.strip()
                if not block:
                    continue
                
                lines = block.split("\n")
                agent_line = lines[0].strip()
                
                if agent_line == "*" or "govnotify" in agent_line:
                    for line in lines[1:]:
                        line = line.strip()
                        if line.startswith("disallow:"):
                            parts = line.split(":", 1)
                            if len(parts) > 1:
                                disallowed = parts[1].strip()
                                if disallowed and path.startswith(disallowed):
                                    _robots_cache[domain] = (False, time.monotonic())
                                    logger.info("robots_disallowed", domain=domain, path=path)
                                    return False
            
            _robots_cache[domain] = (True, time.monotonic())
            return True
    except Exception:
        # Can't fetch robots.txt - assume allowed
        _robots_cache[domain] = (True, time.monotonic())
        return True
