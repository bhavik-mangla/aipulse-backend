"""
GovNotify Pydantic models - single source of truth for all data shapes.
"""
from govnotify.constants import NoticeCategory
from govnotify.models.document import (
    ProcessedDocument,
)
from govnotify.models.source import (
    RawDocument,
    SourceConfig,
    SourceType,
)
from govnotify.models.user import (
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
    # user.py
    "UserPreferences",
    "UserProfile",
]
