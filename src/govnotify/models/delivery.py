"""
Delivery payload and result models.
Defines schemas for delivery attempts and their outcomes.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from govnotify.models.user import DeliveryChannel


class DeliveryResult(BaseModel):
    """Result of attempting to deliver a notification."""
    digest_id: str
    user_id: str
    channel: DeliveryChannel
    success: bool
    delivered_at: Optional[datetime] = None
    error_message: Optional[str] = None
    external_id: Optional[str] = Field(
        default=None,
        description="ID from external service (SendGrid, Telegram, etc.)",
    )
