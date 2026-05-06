"""
User profile and preferences endpoints.
GET /users/me - current user profile
PUT /users/me - update profile fields
PUT /users/me/preferences - update category subscriptions & settings
DELETE /users/me - deactivate account (soft delete)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from govnotify.api.deps import get_current_user, get_db
from govnotify.constants import NoticeCategory
from govnotify.models.user import DeliveryChannel, DigestFrequency
from govnotify.storage.postgres import UserORM

logger = structlog.get_logger(__name__)
router = APIRouter()


# Response schemas

class UserPreferencesResponse(BaseModel):
    categories: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    language: str = "en"
    digest_frequency: str = "daily"
    delivery_channels: list[str] = Field(default_factory=list)
    max_items_per_digest: int = 20


class UserResponse(BaseModel):
    id: str
    email: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    preferences: UserPreferencesResponse
    is_active: bool = True
    created_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None


# Request schemas

class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    telegram_chat_id: Optional[str] = None


class UpdatePreferencesRequest(BaseModel):
    categories: Optional[list[NoticeCategory]] = None
    sources: Optional[list[str]] = None
    regions: Optional[list[str]] = None
    language: Optional[str] = None
    delivery_channels: Optional[list[DeliveryChannel]] = None
    digest_frequency: Optional[DigestFrequency] = None
    max_items_per_digest: Optional[int] = Field(default=None, ge=1, le=100)


# Helpers

def _user_to_response(user: UserORM) -> UserResponse:
    prefs = user.preferences or {}
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        phone=user.phone,
        telegram_chat_id=user.telegram_chat_id,
        preferences=UserPreferencesResponse(
            language=prefs.get("language", "en"),
            categories=prefs.get("categories", []),
            sources=prefs.get("sources", []),
            regions=prefs.get("regions", []),
            delivery_channels=prefs.get("delivery_channels", ["web"]),
            digest_frequency=prefs.get("digest_frequency", "daily"),
            max_items_per_digest=prefs.get("max_items_per_digest", 20),
        ),
        is_active=user.is_active,
        created_at=user.created_at,
        last_active_at=user.last_active_at,
    )


# Endpoints

@router.get("/me", response_model=UserResponse)
async def get_me(
    user: Annotated[UserORM, Depends(get_current_user)],
):
    """Get the current user's profile."""
    return _user_to_response(user)


@router.put("/me", response_model=UserResponse)
async def update_profile(
    body: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db),
    user: Annotated[UserORM, Depends(get_current_user)] = None,
):
    """Update current user's profile fields (name, phone, telegram)."""
    if body.name is not None:
        user.name = body.name
    if body.phone is not None:
        user.phone = body.phone
    if body.telegram_chat_id is not None:
        user.telegram_chat_id = body.telegram_chat_id
        
    logger.info("user_profile_updated", user_id=user.id)
    return _user_to_response(user)


@router.put("/me/preferences", response_model=UserResponse)
async def update_preferences(
    body: UpdatePreferencesRequest,
    db: AsyncSession = Depends(get_db),
    user: Annotated[UserORM, Depends(get_current_user)] = None,
):
    """Update category subscriptions, language, delivery channels, etc."""
    prefs = dict(user.preferences or {})
    
    if body.categories is not None:
        if not body.categories:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="At least 1 category is required",
            )
        prefs["categories"] = [c.value for c in body.categories]
        
    if body.sources is not None:
        prefs["sources"] = body.sources

    if body.regions is not None:
        prefs["regions"] = body.regions
        
    if body.language is not None:
        prefs["language"] = body.language
        
    if body.delivery_channels is not None:
        prefs["delivery_channels"] = [c.value for c in body.delivery_channels]
        
    if body.digest_frequency is not None:
        prefs["digest_frequency"] = body.digest_frequency.value
        
    if body.max_items_per_digest is not None:
        prefs["max_items_per_digest"] = body.max_items_per_digest
        
    user.preferences = prefs
    logger.info("user_preferences_updated", user_id=user.id)
    return _user_to_response(user)


@router.delete("/me", status_code=204)
async def deactivate_account(
    user: Annotated[UserORM, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Deactivate the current user's account (soft delete)."""
    logger.info("user_deactivated", user_id=user.id)
    user.is_active = False
    return None


@router.get("/unsubscribe", tags=["public"])
async def public_unsubscribe(
    email: str,
    token: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Public GET endpoint to unsubscribe from all notifications.
    Used by the link in email footers.
    """
    from sqlalchemy import select
    
    stmt = select(UserORM).where(UserORM.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        # Return 200 anyway to avoid email enumeration, but log it
        logger.warning("unsubscribe_email_not_found", email=email)
        return {"status": "ok", "message": "Successfully unsubscribed"}
        
    user.is_active = False
    await db.commit()
    
    logger.info("user_unsubscribed_via_link", email=email, user_id=user.id)
    return {"status": "ok", "message": "Successfully unsubscribed from GovNotify"}
