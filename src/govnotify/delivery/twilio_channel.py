"""
WhatsApp delivery channel via Twilio API.
Sends WhatsApp messages to users using the Twilio WhatsApp API.
"""
from __future__ import annotations

import base64
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


class WhatsAppChannel(AbstractDeliveryChannel):
    """Send digest messages via Twilio WhatsApp API."""

    @property
    def channel_type(self) -> DeliveryChannel:
        return DeliveryChannel.WHATSAPP

    async def send(
        self, user: UserProfile, digest: UserDigest
    ) -> DeliveryResult:
        """Send a WhatsApp message with the digest content."""
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
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            return DeliveryResult(
                digest_id=digest.id,
                user_id=user.id,
                channel=DeliveryChannel.WHATSAPP,
                success=False,
                error_message="Twilio credentials not configured",
            )

        language = user.preferences.language if user.preferences else "en"
        text = render_plain_text(digest, language=language)
        
        # Twilio WhatsApp numbers must be prefixed with "whatsapp:"
        # Clean the phone number (must be E.164 format: +919992916829)
        clean_phone = phone.strip()
        if not clean_phone.startswith("+"):
            # Assume India if no prefix? Better to require it.
            if len(clean_phone) == 10:
                clean_phone = f"+91{clean_phone}"
                
        to_number = f"whatsapp:{clean_phone}" if not clean_phone.startswith("whatsapp:") else clean_phone
        from_number = settings.whatsapp_from_number
        if not from_number:
            # Fallback/Default for Twilio Sandbox
            from_number = "+14155238886"
            
        if not from_number.startswith("whatsapp:"):
            from_number = f"whatsapp:{from_number}"

        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
        
        # Basic Auth
        auth_str = f"{settings.twilio_account_sid}:{settings.twilio_auth_token}"
        auth_header = f"Basic {base64.b64encode(auth_str.encode()).decode()}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    data={
                        "To": to_number,
                        "From": from_number,
                        "Body": text,
                    },
                    headers={"Authorization": auth_header},
                )
                
            success = 200 <= response.status_code < 300
            res_json = response.json()
            
            if success:
                external_id = res_json.get("sid")
                logger.info(
                    "whatsapp_sent",
                    user_id=user.id,
                    phone=clean_phone,
                    sid=external_id,
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
                error_msg = res_json.get("message", response.text)
                logger.error(
                    "whatsapp_send_failed",
                    user_id=user.id,
                    status_code=response.status_code,
                    error=error_msg,
                )
                return DeliveryResult(
                    digest_id=digest.id,
                    user_id=user.id,
                    channel=DeliveryChannel.WHATSAPP,
                    success=False,
                    error_message=f"Twilio error ({response.status_code}): {error_msg}",
                )

        except Exception as e:
            logger.error(
                "whatsapp_exception",
                user_id=user.id,
                error=str(e),
            )
            return DeliveryResult(
                digest_id=digest.id,
                user_id=user.id,
                channel=DeliveryChannel.WHATSAPP,
                success=False,
                error_message=str(e),
            )

    async def health_check(self) -> bool:
        """Basic check for credentials."""
        settings = get_settings()
        return bool(settings.twilio_account_sid and settings.twilio_auth_token)
