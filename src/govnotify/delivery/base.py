"""
Abstract base class for delivery channels.
interface to enable the plugin/registry pattern. Every delivery channel (email, Telegram, WhatsApp, etc.) implements this.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from govnotify.models.delivery import DeliveryResult
from govnotify.models.notification import UserDigest
from govnotify.models.user import DeliveryChannel, UserProfile


class AbstractDeliveryChannel(ABC):
    """Base interface for notification delivery."""

    @property
    @abstractmethod
    def channel_type(self) -> DeliveryChannel:
        """The enum value this channel handles."""
        pass

    @abstractmethod
    async def send(
        self, user: UserProfile, digest: UserDigest
    ) -> DeliveryResult:
        """
        Send a digest to a user via this channel.
        Must not raise - return a 'DeliveryResult' with "success=False" and "error_message" on failure.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the external service is reachable."""
        pass
