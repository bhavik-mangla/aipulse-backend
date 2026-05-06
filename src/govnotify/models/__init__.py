"""
GovNotify Pydantic models - single source of truth for all data shapes.
"""
from govnotify.constants import NoticeCategory
from govnotify.models.delivery import DeliveryResult
from govnotify.models.document import (
    DocumentChunk,
    ProcessedDocument,
)
from govnotify.models.notification import (
    CategoryDigest,
    NotificationItem,
    UserDigest,
)
from govnotify.models.source import (
    RawDocument,
    SourceConfig,
    SourceType,
)
from govnotify.models.user import (
    DeliveryChannel,
    DigestFrequency,
    UserPreferences,
    UserProfile,
)

__all__ = [
    # source.py
    "SourceType",
    "SourceConfig",
    "RawDocument",
    # document.py
    "NoticeCategory",
    "ProcessedDocument",
    "DocumentChunk",
    # user.py
    "DigestFrequency",
    "DeliveryChannel",
    "UserPreferences",
    "UserProfile",
    # notification.py
    "CategoryDigest",
    "NotificationItem",
    "UserDigest",
    # delivery.py
    "DeliveryResult",
]
