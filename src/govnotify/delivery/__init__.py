"""
Notification delivery plugins.
"""
from govnotify.delivery.base import AbstractDeliveryChannel
from govnotify.delivery.email_channel import EmailChannel
from govnotify.delivery.registry import ChannelRegistry
from govnotify.delivery.telegram_channel import TelegramChannel
from govnotify.delivery.twilio_channel import WhatsAppChannel as TwilioChannel
from govnotify.delivery.whatsapp_cloud_channel import WhatsAppCloudChannel

# Instantiate and register channels
ChannelRegistry.register(EmailChannel())
ChannelRegistry.register(TelegramChannel())

# Note: WhatsAppCloudChannel is the PREFERRED (latest) strategy.
# We register it LAST for the 'whatsapp' key so it takes precedence in the registry 
# if both use the same enum value, or we can handle selection logic in the registry.
ChannelRegistry.register(WhatsAppCloudChannel())

# Register Twilio as an alternative (could be used for SMS later)
# For now, we keep it as a legacy option.
# ChannelRegistry.register(TwilioChannel()) 

__all__ = [
    "AbstractDeliveryChannel",
    "ChannelRegistry",
    "EmailChannel",
    "TelegramChannel",
    "WhatsAppCloudChannel",
    "TwilioChannel",
]
