"""
User profile and preferences models.
Defines schemas for user accounts and their notification preferences.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from govnotify.constants import NoticeCategory


class DeliveryChannel(str, Enum):
    """Supported notification delivery channels."""
    EMAIL = "email"
    WEB = "web"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"


class DigestFrequency(str, Enum):
    """Frequency of digest delivery."""
    REALTIME = "realtime"
    DAILY = "daily"
    WEEKLY = "weekly"


class UserPreferences(BaseModel):
    """User notification preferences (V2: semantic + filters)."""
    categories: list[NoticeCategory] = Field(default_factory=list)
    sources: list[str] = Field(
        default_factory=list, description="IDs of sources to subscribe to"
    )
    regions: list[str] = Field(
        default_factory=list, description="States/regions of interest"
    )
    audiences: list[str] = Field(
        default_factory=list, description="Target audiences (e.g. Farmers, Investors)"
    )
    high_impact_only: bool = Field(
        default=False, description="Filter for Critical/High impact only"
    )
    language: str = Field(
        default="en", description="Preferred language for summaries"
    )
    delivery_channels: list[DeliveryChannel] = Field(
        default=[DeliveryChannel.WEB]
    )
    digest_frequency: DigestFrequency = DigestFrequency.DAILY
    max_items_per_digest: int = Field(default=20, ge=1, le=100)


class UserProfile(BaseModel):
    """Full user profile."""
    id: str
    email: Optional[str] = None
    phone: Optional[str] = None
    name: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    
    last_active_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True
