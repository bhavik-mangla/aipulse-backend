"""
User profile and preferences models.
Defines schemas for user accounts and their preferences.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from govnotify.constants import DEFAULT_COUNTRY, NewsCategory


class UserPreferences(BaseModel):
    """Reader preferences."""
    country: str = Field(
        default=DEFAULT_COUNTRY, description="Feed scope: world, in, us"
    )
    categories: list[NewsCategory] = Field(default_factory=list)
    sources: list[str] = Field(
        default_factory=list, description="IDs of outlets to follow"
    )
    top_stories_only: bool = Field(
        default=False, description="Show only the most significant stories"
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
