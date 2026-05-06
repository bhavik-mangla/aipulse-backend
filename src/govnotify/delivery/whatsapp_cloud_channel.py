"""
WhatsApp Cloud API (Direct from Meta) delivery channel.
Uses Meta's Graph API directly to avoid middleman markups.
Best and latest strategy as of 2026.

Requires:
1. WhatsApp Template (for business-initiated digests)
2. Meta App with WhatsApp product enabled
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import httpx
import structlog

from govnotify.config import get_settings
from govnotify.delivery.base import AbstractDeliveryChannel
from govnotify.digests.templates import render_plain_text
from govnotify.models.delivery import DeliveryResult
from govnotify.models.notification import UserDigest
from govnotify.models.user import DeliveryChannel, UserProfile
from govnotify.utils.time import get_utc_now

logger = structlog.get_logger(__name__)


class WhatsAppCloudChannel(AbstractDeliveryChannel):
    """Send digest messages via Meta's WhatsApp Cloud API."""

    @property
    def channel_type(self) -> DeliveryChannel:
        # We reuse the same enum but this is the "Modern" implementation
        return DeliveryChannel.WHATSAPP

    async def send(
        self, user: UserProfile, digest: UserDigest
    ) -> DeliveryResult:
        """Send a WhatsApp message using Meta's Cloud API."""
        phone = user.phone
        if not phone:
            return DeliveryResult(
                digest_id=digest.id,
                user_id=user.id,
                channel=DeliveryChannel.WHATSAPP,
                success=False,
                error_message="User has no phone number",
            )

        settings = get_settings()
        if not settings.whatsapp_cloud_access_token or not settings.whatsapp_cloud_phone_number_id:
            return DeliveryResult(
                digest_id=digest.id,
                user_id=user.id,
                channel=DeliveryChannel.WHATSAPP,
                success=False,
                error_message="WhatsApp Cloud API credentials not configured",
            )

        # Clean phone number (Meta requires only digits with country code)
        clean_phone = "".join(filter(str.isdigit, phone))
        if len(clean_phone) == 10:
            clean_phone = f"91{clean_phone}" # Default to India

        language = user.preferences.language if user.preferences else "en"
        text = render_plain_text(digest, language=language)

        url = f"https://graph.facebook.com/{settings.whatsapp_cloud_version}/{settings.whatsapp_cloud_phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {settings.whatsapp_cloud_access_token}",
            "Content-Type": "application/json",
        }

        # STRATEGY: 
        # For business-initiated messages (Digests), Meta REQUIRES templates.
        # For service-initiated (User messaged us first in last 24h), we can send text.
        
        # In a real production app, we would use a Template like 'daily_digest'
        # For now, we'll try a text message (works for testing if you've messaged the bot first)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "text",
            "text": {"body": text}
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                
            res_json = response.json()
            success = 200 <= response.status_code < 300
            
            if success:
                external_id = res_json.get("messages", [{}])[0].get("id")
                logger.info(
                    "whatsapp_cloud_sent",
                    user_id=user.id,
                    phone=clean_phone,
                    msg_id=external_id,
                )
                return DeliveryResult(
                    digest_id=digest.id,
                    user_id=user.id,
                    channel=DeliveryChannel.WHATSAPP,
                    success=True,
                    delivered_at=get_utc_now(),
                    external_id=external_id,
                )
            else:
                error = res_json.get("error", {})
                error_msg = error.get("message", response.text)
                logger.error(
                    "whatsapp_cloud_failed",
                    user_id=user.id,
                    status_code=response.status_code,
                    error=error_msg,
                )
                return DeliveryResult(
                    digest_id=digest.id,
                    user_id=user.id,
                    channel=DeliveryChannel.WHATSAPP,
                    success=False,
                    error_message=f"Meta Error: {error_msg}",
                )

        except Exception as e:
            logger.error("whatsapp_cloud_exception", error=str(e))
            return DeliveryResult(
                digest_id=digest.id,
                user_id=user.id,
                channel=DeliveryChannel.WHATSAPP,
                success=False,
                error_message=str(e),
            )

    async def health_check(self) -> bool:
        """Check if tokens are present."""
        settings = get_settings()
        return bool(settings.whatsapp_cloud_access_token and settings.whatsapp_cloud_phone_number_id)
