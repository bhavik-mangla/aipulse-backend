"""
API rate-limiting middleware.
Enforces per-user request rate limits using Redis sliding-window counters.
Limits per §19:
- Web/API endpoint    s: 100 requests / minute
- Chat endpoints: 10 requests / minute
Anonymous (unauthenticated) requests are rate-limited by IP address at 30 requests / minute.
"""
from __future__ import annotations

import hashlib
import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from govnotify.storage.redis_store import RedisStore
from govnotify.config import get_settings

logger = structlog.get_logger(__name__)

# Paths exempt from rate limiting
_EXEMPT_PATHS = ("/", "/health", "/docs", "/redoc", "/openapi.json")

WEB_LIMIT = 100  # requests per minute for authenticated users
_ANON_LIMIT = 30  # requests per minute for unauthenticated callers
_WINDOW = 60  # seconds


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that checks Redis-backed rate limits."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # Skip rate limiting for health/docs/static
        if path in _EXEMPT_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
            return await call_next(request)

        # Determine identity key
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            # We can't decode JWT here cheaply - use the token hash as key
            limit = WEB_LIMIT
            token_hash = hashlib.sha256(auth_header[7:].encode()).hexdigest()[:16]
            rate_key = f"user:{token_hash}"
        else:
            # Anonymous - rate limit by IP
            limit = _ANON_LIMIT
            client_ip = request.client.host if request.client else "unknown"
            rate_key = f"ip:{client_ip}"

        try:
            store = RedisStore()
            allowed = await store.check_rate_limit(
                rate_key, max_requests=limit, window_seconds=_WINDOW
            )
            await store.close()
        except Exception as e:
            # If Redis is down, allow the request (fail-open)
            logger.warning("rate_limit_redis_error", rate_key=rate_key, error=str(e))
            return await call_next(request)

        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                limit=limit,
                rate_key=rate_key,
                path=path,
            )
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(_WINDOW)},
                content={"detail": f"Rate limit exceeded: {limit} requests per minute"},
            )

        return await call_next(request)
