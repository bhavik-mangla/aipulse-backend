"""
Delivery channel registry - plugin pattern.
Mirrors the SourceRegistry from Step 3. Channels register themselves
and can be looked up by "DeliveryChannel" enum value at runtime.
"""
from __future__ import annotations

from typing import Type

import structlog

from govnotify.delivery.base import AbstractDeliveryChannel
from govnotify.models.user import DeliveryChannel

logger = structlog.get_logger(__name__)


class ChannelRegistry:
    """Singleton-style registry that maps DeliveryChannel -> channel instance."""
    _channels: dict[DeliveryChannel, AbstractDeliveryChannel] = {}

    @classmethod
    def register(cls, channel: AbstractDeliveryChannel) -> None:
        """Register a delivery channel implementation."""
        cls._channels[channel.channel_type] = channel
        logger.info(
            "delivery_channel_registered",
            channel=channel.channel_type.value,
        )

    @classmethod
    def get(cls, channel_type: DeliveryChannel) -> AbstractDeliveryChannel | None:
        """Look up a registered channel by type."""
        return cls._channels.get(channel_type)

    @classmethod
    def get_all(cls) -> dict[DeliveryChannel, AbstractDeliveryChannel]:
        """Return all registered channels."""
        return dict(cls._channels)

    @classmethod
    def clear(cls) -> None:
        """Remove all registered channels (useful in tests)."""
        cls._channels.clear()

    @classmethod
    def available_channels(cls) -> list[DeliveryChannel]:
        """Return the list of registered channel types."""
        return list(cls._channels.keys())
