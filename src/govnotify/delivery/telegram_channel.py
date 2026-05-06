"""
Telegram delivery channel via python-telegram-bot.
Sends Markdown-formatted digest messages to users via Telegram Bot API.

Error handling per §24.8:
- If bot is blocked or chat not found -> mark Telegram channel as inactive.
- Don't retry - users can always access digest via web.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog

from govnotify.config import get_settings
from govnotify.delivery.base import AbstractDeliveryChannel
from govnotify.digests.templates import render_telegram
from govnotify.models.delivery import DeliveryResult
from govnotify.models.notification import UserDigest
from govnotify.models.user import DeliveryChannel, UserProfile
from govnotify.utils.time import get_utc_now

logger = structlog.get_logger(__name__)

# Telegram message limit is 4096 characters
TELEGRAM_MAX_MESSAGE_LENGTH = 4096


class TelegramChannel(AbstractDeliveryChannel):
    """Send digest messages via Telegram Bot API."""

    @property
    def channel_type(self) -> DeliveryChannel:
        return DeliveryChannel.TELEGRAM

    async def send(
        self, user: UserProfile, digest: UserDigest
    ) -> DeliveryResult:
        """Send a Telegram message with the digest content."""
        chat_id = user.telegram_chat_id
        if not chat_id:
            return DeliveryResult(
                digest_id=digest.id,
                user_id=user.id,
                channel=DeliveryChannel.TELEGRAM,
                success=False,
                error_message="User has no telegram_chat_id",
            )

        settings = get_settings()
        if not settings.telegram_bot_token:
            return DeliveryResult(
                digest_id=digest.id,
                user_id=user.id,
                channel=DeliveryChannel.TELEGRAM,
                success=False,
                error_message="Telegram bot token not configured",
            )

        language = user.preferences.language if user.preferences else "en"
        text = render_telegram(digest, language=language)

        try:
            from telegram import Bot
            from telegram.constants import ParseMode

            bot = Bot(token=settings.telegram_bot_token)
            
            # Split long messages if needed
            messages = _split_message(text, TELEGRAM_MAX_MESSAGE_LENGTH)
            message_ids: list[int] = []
            
            for msg in messages:
                try:
                    sent = await bot.send_message(
                        chat_id=chat_id,
                        text=msg,
                        disable_web_page_preview=True,
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    message_ids.append(sent.message_id)
                except Exception:
                    # Fall back to plain text if Markdown fails
                    sent = await bot.send_message(
                        chat_id=chat_id,
                        text=msg,
                        disable_web_page_preview=True,
                    )
                    message_ids.append(sent.message_id)

            external_id = ",".join(str(mid) for mid in message_ids)
            logger.info(
                "telegram_sent",
                chat_id=chat_id,
                user_id=user.id,
                message_count=len(messages),
            )

            return DeliveryResult(
                digest_id=digest.id,
                user_id=user.id,
                channel=DeliveryChannel.TELEGRAM,
                success=True,
                delivered_at=get_utc_now(),
                external_id=external_id,
            )

        except Exception as e:
            error_str = str(e)
            logger.error(
                "telegram_send_failed",
                user_id=user.id,
                chat_id=chat_id,
                error=error_str,
            )
            
            # Detect blocked/not-found errors per §24.8
            is_permanent = any(
                keyword in error_str.lower()
                for keyword in [
                    "blocked",
                    "not found",
                    "chat not found",
                    "bot was kicked",
                    "deactivated",
                    "forbidden",
                ]
            )

            return DeliveryResult(
                digest_id=digest.id,
                user_id=user.id,
                channel=DeliveryChannel.TELEGRAM,
                success=False,
                error_message=f"PERMANENT: {error_str}" if is_permanent else error_str,
            )

    async def health_check(self) -> bool:
        """Check if the Telegram bot token is valid by calling getMe."""
        settings = get_settings()
        if not settings.telegram_bot_token:
            return False
        try:
            from telegram import Bot
            bot = Bot(token=settings.telegram_bot_token)
            me = await bot.get_me()
            return me is not None
        except Exception:
            return False


def _split_message(text: str, max_length: int) -> list[str]:
    """
    Split a long message into chunks that fit Telegram's limit.
    Splits on double newlines (paragraph boundaries) first, then single newlines, preserving readability.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    current = ""

    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= max_length:
            current = candidate
        else:
            if current:
                chunks.append(current)
            
            # If single paragraph exceeds limit, split on newlines
            if len(paragraph) > max_length:
                for line in paragraph.split("\n"):
                    if len(current) + len(line) + 1 <= max_length:
                        current = f"{current}\n{line}" if current else line
                    else:
                        if current:
                            chunks.append(current)
                        if len(line) > max_length:
                            # Hard split if even a single line is too long
                            current = line[:max_length]
                            chunks.append(current)
                            current = "" # Reset or handle remaining
                        else:
                            current = line
            else:
                current = paragraph

    if current:
        chunks.append(current)
        
    return chunks if chunks else [text[:max_length]]
