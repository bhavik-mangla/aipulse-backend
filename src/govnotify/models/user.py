"""
User profile and preferences models.
Defines schemas for user accounts and their preferences.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from govnotify.constants import NoticeCategory


class UserPreferences(BaseModel):
    """User preferences (semantic + filters)."""
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
    include_general_news: bool = Field(
        default=False, description="Include news from general outlets"
    )
    language: str = Field(
        default="en", description="Preferred language for summaries"
    )


class UserProfile(BaseModel):
    """Full user profile."""
    id: str
    email: Optional[str] = None
    phone: Optional[str] = None
    name: Optional[str] = None
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    
    last_active_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True
