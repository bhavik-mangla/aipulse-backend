"""
Simplified subscription - passwordless access/update via email or telegram.
Includes a hard limit of 100 users for security/misuse prevention.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

import structlog
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from govnotify.api.deps import get_db
from govnotify.config import get_settings
from govnotify.storage.postgres import UserORM
from govnotify.utils.time import get_utc_now

logger = structlog.get_logger(__name__)
router = APIRouter()

MAX_USERS = 100


class AccessRequest(BaseModel):
    email: Optional[EmailStr] = None
    telegram_chat_id: Optional[str] = None
    name: Optional[str] = None
    language: Optional[str] = None
    sources: Optional[list[str]] = None
    profile_description: Optional[str] = None
    preferences: Optional[dict] = None

    @model_validator(mode="after")
    def check_identifier(self) -> "AccessRequest":
        if not self.email and not self.telegram_chat_id:
            raise ValueError("Either email or telegram_chat_id must be provided")
        return self


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token TTL in seconds")


def _create_access_token(user_id: str) -> tuple[str, int]:
    settings = get_settings()
    expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    expire = get_utc_now() + expires_delta
    payload = {"sub": user_id, "exp": expire, "type": "access", "jti": str(uuid4())}
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, int(expires_delta.total_seconds())


def _create_refresh_token(user_id: str) -> str:
    settings = get_settings()
    expire = get_utc_now() + timedelta(days=settings.jwt_refresh_token_expire_days)
    payload = {"sub": user_id, "exp": expire, "type": "refresh", "jti": str(uuid4())}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@router.post("/access", response_model=TokenResponse)
async def access(body: AccessRequest, db: AsyncSession = Depends(get_db)):
    """Subscribe or Update preferences based on identifier. No password required."""
    logger.info("access_request_received", email=body.email, telegram=body.telegram_chat_id)
    filters = []
    if body.email:
        filters.append(UserORM.email == body.email)
    if body.telegram_chat_id:
        filters.append(UserORM.telegram_chat_id == body.telegram_chat_id)
        
    result = await db.execute(select(UserORM).where(or_(*filters)))
    user = result.scalar_one_or_none()
    
    if user:
        # Update existing user preferences if provided
        new_prefs = dict(user.preferences or {})
        if body.preferences:
            new_prefs.update(body.preferences)
            
        if body.language:
            new_prefs["language"] = body.language
        if body.sources is not None:
            new_prefs["sources"] = body.sources
            
        user.preferences = new_prefs
            
        if body.name and not user.name:
            user.name = body.name
            
        user.last_active_at = get_utc_now()
        user.is_active = True
        logger.info("user_updated", user_id=user.id, identifier=body.email or body.telegram_chat_id)
    else:
        # Check user limit before creating new one
        count_res = await db.execute(select(func.count(UserORM.id)))
        user_count = count_res.scalar() or 0
        
        if user_count >= MAX_USERS:
            logger.warning("user_limit_reached", count=user_count)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Subscription limit reached. Please try again later."
            )

        # Build preferences with defaults
        prefs = {
            "categories": [],
            "sources": body.sources or [],
            "regions": [],
            "language": body.language or "en",
            "delivery_channels": ["email"] if body.email else ["telegram"],
            "digest_frequency": "daily",
            "max_items_per_digest": 20,
        }
        
        # Override with body.preferences if provided
        if body.preferences:
            prefs.update(body.preferences)
        
        user = UserORM(
            id=str(uuid4()),
            email=body.email,
            telegram_chat_id=body.telegram_chat_id,
            name=body.name,
            preferences=prefs,
            is_active=True,
        )
        db.add(user)
        logger.info("user_created", user_id=user.id, identifier=body.email or body.telegram_chat_id)
    
    await db.flush()
    access_token, expires_in = _create_access_token(user.id)
    refresh_token = _create_refresh_token(user.id)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )
