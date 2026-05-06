"""
FastAPI dependency injection - shared across all route modules.
Provides:
- get_db: async DB session (via SQLAlchemy)
- get_current_user: JWT bearer token -> UserORM
- require_admin: raise 403 if user is not admin (placeholder)
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

import structlog
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from govnotify.config import get_settings
from govnotify.storage.postgres import UserORM, get_engine, get_session_factory
from govnotify.storage.redis_store import RedisStore
from govnotify.utils.time import get_utc_now

logger = structlog.get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


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


# JWT helpers

def _decode_token(token: str) -> dict:
    """Decode and validate a JWT access token."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# Current user dependency

async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    db: AsyncSession = Depends(get_db),
) -> UserORM:
    """
    Extract the current user from the JWT bearer token.
    Raises 401 if token is missing/invalid or user not found.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    payload = _decode_token(credentials.credentials)
    user_id: str | None = payload.get("sub")
    
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
        
    result = await db.execute(select(UserORM).where(UserORM.id == user_id))
    user = result.scalar_one_or_none()
    
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
        
    # Update last_active_at
    user.last_active_at = get_utc_now()
    return user


# Admin guard

async def require_admin(
    user: Annotated[UserORM, Depends(get_current_user)],
) -> UserORM:
    """
    Placeholder admin check - in production, check a role column.
    For V1, any authenticated user can access admin endpoints (protect via deployment-level auth instead).
    """
    # TODO: Add role-based check when roles are implemented
    return user
