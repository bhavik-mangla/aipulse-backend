"""
Email delivery channel via SendGrid Web API v3.
Uses the official "sendgrid" Python SDK. Falls back gracefully when the API key is not configured.

Error handling per §24.8:
- Retry once after 5 minutes on failure (handled by Celery task layer).
- Never retry more than once per digest per channel.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog

from govnotify.config import get_settings
from govnotify.digests.templates import render_email_html, render_plain_text, render_subject
from govnotify.delivery.base import AbstractDeliveryChannel
from govnotify.models.delivery import DeliveryResult
from govnotify.models.notification import UserDigest
from govnotify.utils.time import get_utc_now
from govnotify.models.user import DeliveryChannel, UserProfile

logger = structlog.get_logger(__name__)


class EmailChannel(AbstractDeliveryChannel):
    """Send digest emails via SendGrid Web API v3."""

    @property
    def channel_type(self) -> DeliveryChannel:
        return DeliveryChannel.EMAIL

    async def send(
        self, user: UserProfile, digest: UserDigest
    ) -> DeliveryResult:
        """Send a styled HTML email with plain-text fallback."""
        if not user.email:
            return DeliveryResult(
                digest_id=digest.id,
                user_id=user.id,
                success=False,
                channel=DeliveryChannel.EMAIL,
                error_message="User has no email address",
            )

        settings = get_settings()
        if not settings.sendgrid_api_key:
            return DeliveryResult(
                digest_id=digest.id,
                user_id=user.id,
                channel=DeliveryChannel.EMAIL,
                success=False,
                error_message="SendGrid API key not configured",
            )

        language = user.preferences.language if user.preferences else "en"
        html_content = render_email_html(digest, language=language)
        plain_content = render_plain_text(digest, language=language)
        subject = render_subject(digest.date, language=language)

        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import (
                Content,
                Email,
                Header,
                Mail,
                MimeType,
                To,
            )

            sg = SendGridAPIClient(api_key=settings.sendgrid_api_key)
            message = Mail()
            message.from_email = Email(settings.sendgrid_from_email, "GovNotify")
            message.to = [To(user.email, user.name or "")]
            message.subject = subject
            message.add_content(Content(MimeType.html, html_content))
            message.add_content(Content(MimeType.text, plain_content))

            # One-click unsubscribe header and personalized link
            unsubscribe_url = f"https://govnotify.in/api/v1/users/unsubscribe?email={user.email}"
            message.add_header(Header("List-Unsubscribe", f"<{unsubscribe_url}>"))

            response = sg.send(message)
            success = 200 <= response.status_code < 300
            external_id = (
                response.headers.get("X-Message-Id", "") if success else None
            )

            logger.info(
                "email_sent",
                user_id=user.id,
                status_code=response.status_code,
                success=success,
            )

            return DeliveryResult(
                digest_id=digest.id,
                user_id=user.id,
                channel=DeliveryChannel.EMAIL,
                success=success,
                delivered_at=get_utc_now() if success else None,
                external_id=external_id,
                error_message=None if success else f"SendGrid HTTP {response.status_code}",
            )

        except Exception as e:
            logger.error(
                "email_send_failed",
                user_id=user.id,
                error=str(e),
            )
            return DeliveryResult(
                digest_id=digest.id,
                user_id=user.id,
                channel=DeliveryChannel.EMAIL,
                success=False,
                error_message=str(e),
            )

    async def health_check(self) -> bool:
        """Check if SendGrid API key is configured."""
        settings = get_settings()
        return bool(settings.sendgrid_api_key)
