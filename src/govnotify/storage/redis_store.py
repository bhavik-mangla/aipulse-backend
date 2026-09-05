"""
Redis cache and queue operations.
Manages connections and key patterns for:
- Content hash dedup cache
- Rate limiting
- Task locks
"""
import redis.asyncio as autoredis
import structlog

from govnotify.config import get_settings

logger = structlog.get_logger(__name__)

# Global client instance
_redis_client: autoredis.Redis | None = None

# --- Key Patterns ---

DEDUP_HASH_KEY = "dedup:hash:{content_hash}"  # TTL: 120 days
CACHE_CATEGORY_LATEST = "cache:category:{category}:latest"  # TTL: 24h
RATELIMIT_USER_KEY = "ratelimit:user:{user_id}"
LOCK_SOURCE_KEY = "lock:source:{source_id}"

# TTLs in seconds
TTL_DEDUP = 120 * 24 * 3600  # 120 days
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

    # --- Source Health / Rate Limiting ---

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
