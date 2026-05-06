"""
Notification and digest models.
Defines schemas for notification items, category digests, and user digests.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl

from govnotify.constants import NoticeCategory
from govnotify.models.user import DeliveryChannel


class NotificationItem(BaseModel):
    """A single notification item in a digest."""
    document_id: str
    title: str
    summary: str  # Now stores JSON string
    category: NoticeCategory
    source_id: str
    source_name: str
    source_url: HttpUrl
    ingested_at: Optional[datetime] = None
    regions: list[str] = Field(
        default_factory=list, description="Tagged regions for this item"
    )
    departments: list[str] = Field(default_factory=list)
    impact_tier: str = Field(default="Medium")
    affected_audience: list[str] = Field(default_factory=list)
    relevance_score: float = Field(default=0.0)


class CategoryDigest(BaseModel):
    """
    Pre-generated digest for ONE category for ONE day.
    Generated once per category per day.
    """
    id: str
    category: NoticeCategory
    date: str = Field(description="YYYY-MM-DD date this digest covers")
    items: list[NotificationItem] = Field(default_factory=list)
    summary_text: str = Field(default="", description="LLM-generated category summary")
    summary_hindi: str = Field(default="", description="Hindi translation of summary")
    item_count: int = 0
    has_updates: bool = Field(default=True)
    no_update_message: str = Field(default="No updates for this category today.")
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    model_used: Optional[str] = Field(default="", description="LLM model used for summary")
    llm_cost_usd: float = Field(default=0.0, description="Cost of LLM generation")


class SourceDigest(BaseModel):
    """
    Pre-generated digest for ONE source for ONE day.
    This is the new primary unit for daily digests.
    """
    id: str
    source_id: str
    source_name: str
    date: str = Field(description="YYYY-MM-DD date this digest covers")
    items: list[NotificationItem] = Field(default_factory=list)
    summary_text: str = Field(default="", description="Consolidated source summary")
    summary_hindi: str = Field(default="", description="Hindi translation of summary")
    item_count: int = 0
    has_updates: bool = Field(default=True)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    model_used: Optional[str] = Field(default="", description="LLM model used for summary")
    llm_cost_usd: float = Field(default=0.0, description="Cost of LLM generation")


class UserDigest(BaseModel):
    """
    Final assembled digest for a specific user.
    Combines SourceDigests for user's subscribed sources.
    """
    id: str
    user_id: str
    source_sections: list[SourceDigest] = Field(default_factory=list)
    category_sections: list[CategoryDigest] = Field(default_factory=list) # Kept for future
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    date: str = Field(description="YYYY-MM-DD")
    total_items: int = 0
    delivery_channel: DeliveryChannel = DeliveryChannel.WEB
    delivered: bool = False
    delivered_at: Optional[datetime] = None
