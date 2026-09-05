"""
FastAPI dependency injection - shared across all route modules.
Provides:
- get_db: async DB session (via SQLAlchemy)
- get_redis: async Redis client
"""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from govnotify.storage.postgres import get_engine, get_session_factory
from govnotify.storage.redis_store import RedisStore

logger = structlog.get_logger(__name__)


# Database session

async def get_db() -> AsyncSession: # type: ignore[misc]
    """Yield an async DB session, commit on success, rollback on error."""
    engine = get_engine()
    factory = get_session_factory(engine)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_redis() -> RedisStore:
    """Dependency provider for RedisStore."""
    return RedisStore()
