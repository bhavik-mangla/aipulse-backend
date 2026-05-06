"""
Redis cache and queue operations.
Manages connections and key patterns for:
- Content hash dedup cache
- Pre-generated category digest cache
- Rate limiting
- Task locks
"""
from typing import Any

import redis.asyncio as autoredis
import structlog

from govnotify.config import get_settings

logger = structlog.get_logger(__name__)

# Global client instance
_redis_client: autoredis.Redis | None = None

# --- Key Patterns ---
# These match §9.3 of the system prompt exactly.

DEDUP_HASH_KEY = "dedup:hash:{content_hash}"  # TTL: 120 days
DIGEST_CATEGORY_KEY = "digest:category:{category}:{date}"  # TTL: 48h
DIGEST_ALL_KEY = "digest:all_categories:{date}"  # TTL: 48h
CACHE_CATEGORY_LATEST = "cache:category:{category}:latest"  # TTL: 24h
RATELIMIT_USER_KEY = "ratelimit:user:{user_id}"
LOCK_SOURCE_KEY = "lock:source:{source_id}"
LOCK_DIGEST_KEY = "lock:digest_generation:{date}"

# TTLs in seconds
TTL_DEDUP = 120 * 24 * 3600  # 120 days
TTL_DIGEST = 48 * 3600  # 48 hours
TTL_CACHE_LATEST = 24 * 3600  # 24 hours
TTL_LOCK = 30 * 60  # 30 minutes (task lock)


def get_redis_client(url: str | None = None) -> autoredis.Redis:
    """Create or return the global async Redis client."""
    global _redis_client
    if _redis_client is None:
        redis_url = url or get_settings().redis_url
        _redis_client = autoredis.from_url(
            redis_url,
            decode_responses=True,
            max_connections=20,
        )
    return _redis_client


class RedisStore:
    """High-level Redis operations for GovNotify."""

    def __init__(self, client: autoredis.Redis | None = None):
        self._client = client

    @property
    def client(self) -> autoredis.Redis:
        if self._client is None:
            self._client = get_redis_client()
        return self._client

    # --- Dedup Cache ---

    async def set_content_hash(self, content_hash: str, document_id: str) -> None:
        """Register a content hash for dedup checking."""
        key = DEDUP_HASH_KEY.format(content_hash=content_hash)
        await self.client.set(key, document_id, ex=TTL_DEDUP)

    async def get_content_hash(self, content_hash: str) -> str | None:
        """Check if a content hash already exists. Returns document_id or None."""
        key = DEDUP_HASH_KEY.format(content_hash=content_hash)
        return await self.client.get(key)

    # --- Category Digest Cache ---

    async def set_category_digest(
        self, category: str, date: str, digest_json: str
    ) -> None:
        """Cache a pre-generated category digest."""
        key = DIGEST_CATEGORY_KEY.format(category=category, date=date)
        await self.client.set(key, digest_json, ex=TTL_DIGEST)

    async def get_category_digest(self, category: str, date: str) -> str | None:
        """Retrieve a cached category digest."""
        key = DIGEST_CATEGORY_KEY.format(category=category, date=date)
        return await self.client.get(key)

    # --- Task Locks ---

    async def acquire_lock(self, lock_key: str, worker_id: str) -> bool:
        """Acquire a distributed lock. Returns True if acquired."""
        return await self.client.set(lock_key, worker_id, nx=True, ex=TTL_LOCK)

    async def release_lock(self, lock_key: str) -> None:
        """Release a distributed lock."""
        await self.client.delete(lock_key)

    # --- Rate Limiting ---

    async def check_rate_limit(
        self, user_id: str, max_requests: int = 100, window_seconds: int = 60
    ) -> bool:
        """Check if user is within rate limit. Returns True if allowed."""
        key = RATELIMIT_USER_KEY.format(user_id=user_id)
        current = await self.client.incr(key)
        if current == 1:
            await self.client.expire(key, window_seconds)
        return current <= max_requests

    # --- Analytics ---

    async def increment_visitor_count(self) -> int:
        """Increment the total visitor counter."""
        return await self.client.incr("analytics:total_visits")

    async def get_visitor_count(self) -> int:
        """Retrieve the current total visitor count."""
        val = await self.client.get("analytics:total_visits")
        return int(val) if val else 0

    # --- Health Check ---

    async def health_check(self) -> bool:
        """Check if Redis is reachable."""
        try:
            return await self.client.ping()
        except Exception:
            return False

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
