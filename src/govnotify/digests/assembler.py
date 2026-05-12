"""
User digest assembler - Phase 2 of digest generation.
Combines pre-generated CategoryDigests into per-user UserDigest objects.
Zero additional LLM calls - pure data assembly.

Flow (7:00 AM IST, after category digests are generated):
1. Fetch all users with daily digest preference
2. For each user: get subscribed categories + fetch CategoryDigest from cache/DB
3. Assemble UserDigest with category sections in user's preference order
4. Apply language preference (Hindi summary if user.preferences.language == "hi")
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional, Sequence

import structlog

from govnotify.constants import NoticeCategory
from govnotify.models.notification import CategoryDigest, UserDigest
from govnotify.models.user import DeliveryChannel, UserPreferences, UserProfile
from govnotify.utils.time import get_utc_now

logger = structlog.get_logger(__name__)


class UserDigestAssembler:
    """
    Assembles per-user digests from pre-generated category digests.
    This is a pure combiner - no LLM calls, no DB writes.
    Just selects and orders CategoryDigests based on user preferences.
    """

    def assemble(
        self,
        user: UserProfile,
        category_digests: dict[NoticeCategory, CategoryDigest],
        date_str: str,
        channel: DeliveryChannel | None = None,
    ) -> UserDigest:
        """
        Assemble a UserDigest for a single user.
        Args:
            user: The user profile with preferences.
            category_digests: All pre-generated CategoryDigests keyed by category.
            date_str: Date string (YYYY-MM-DD).
            channel: Delivery channel; defaults to user's first preference.
        Returns:
            A fully assembled UserDigest.
        """
        prefs = user.preferences
        delivery_channel = channel or (
            prefs.delivery_channels[0]
            if prefs.delivery_channels
            else DeliveryChannel.WEB
        )

        # Get user's subscribed categories (or all if none specified)
        subscribed = prefs.categories if prefs.categories else list(NoticeCategory)
        subscribed_sources = set(prefs.sources) if prefs.sources else None
        subscribed_audiences = set(prefs.audiences) if prefs.audiences else None
        high_impact_only = prefs.high_impact_only

        # Gather category sections in subscription order
        sections: list[CategoryDigest] = []
        total_items = 0
        for cat in subscribed:
            digest = category_digests.get(cat)
            if digest is None:
                # Create an empty digest if category wasn't generated
                digest = CategoryDigest(
                    id=str(uuid.uuid4()),
                    category=cat,
                    date=date_str,
                    items=[],
                    summary_text="",
                    summary_hindi="",
                    item_count=0,
                    has_updates=False,
                    generated_at=get_utc_now(),
                )
            else:
                # Apply filters: source, audience, impact
                filtered_items = digest.items
                
                if subscribed_sources:
                    filtered_items = [
                        item for item in filtered_items
                        if item.source_id in subscribed_sources
                    ]
                
                if subscribed_audiences:
                    filtered_items = [
                        item for item in filtered_items
                        if any(aud in subscribed_audiences for aud in item.affected_audience)
                    ]
                
                if high_impact_only:
                    filtered_items = [
                        item for item in filtered_items
                        if item.impact_tier in ["Critical", "High"]
                    ]

                if filtered_items:
                    # Rebuild summaries for filtered items
                    summaries = []
                    summaries_hindi = []
                    for item in filtered_items:
                        en, hi = self._extract_one_liners(item.summary)
                        if en:
                            summaries.append(f"• {en}")
                        else:
                            summaries.append(f"• {item.title}")
                        
                        if hi:
                            summaries_hindi.append(f"• {hi}")
                        else:
                            summaries_hindi.append(f"• {item.title}")
                        
                    digest = CategoryDigest(
                        id=digest.id,
                        category=digest.category,
                        date=digest.date,
                        items=filtered_items,
                        summary_text="\n".join(summaries),
                        summary_hindi="\n".join(summaries_hindi),
                        item_count=len(filtered_items),
                        has_updates=True,
                        generated_at=digest.generated_at,
                    )
                else:
                    digest = CategoryDigest(
                        id=str(uuid.uuid4()),
                        category=cat,
                        date=date_str,
                        items=[],
                        summary_text="",
                        summary_hindi="",
                        item_count=0,
                        has_updates=False,
                        generated_at=get_utc_now(),
                    )

            if digest.has_updates:
                sections.append(digest)
                total_items += digest.item_count

        # Cap total items per user preference
        max_items = prefs.max_items_per_digest
        if total_items > max_items:
            sections = self._trim_sections(sections, max_items)
            total_items = sum(s.item_count for s in sections)

        user_digest = UserDigest(
            id=str(uuid.uuid4()),
            user_id=user.id,
            category_sections=sections,
            generated_at=get_utc_now(),
            date=date_str,
            total_items=total_items,
            delivery_channel=delivery_channel,
        )

        logger.info(
            "user_digest_assembled",
            user_id=user.id,
            date=date_str,
            categories=len(sections),
            total_items=total_items,
            channel=delivery_channel.value,
        )
        return user_digest

    def assemble_batch(
        self,
        users: Sequence[UserProfile],
        category_digests: dict[NoticeCategory, CategoryDigest],
        date_str: str,
    ) -> list[UserDigest]:
        """
        Assemble UserDigests for a batch of users.
        Args:
            users: List of user profiles.
            category_digests: All pre-generated CategoryDigests.
            date_str: Date string (YYYY-MM-DD).
        Returns:
            List of UserDigests, one per user per delivery channel.
        """
        results: list[UserDigest] = []
        for user in users:
            if not user.is_active:
                continue
            # Generate one digest per delivery channel the user wants
            channels = user.preferences.delivery_channels or [DeliveryChannel.WEB]
            for channel in channels:
                digest = self.assemble(user, category_digests, date_str, channel)
                results.append(digest)
        return results

    @staticmethod
    def _trim_sections(
        sections: list[CategoryDigest], max_items: int
    ) -> list[CategoryDigest]:
        """
        Trim category sections to fit within max_items total.
        Keeps items from earlier (higher-priority) categories first.
        Completely omits sections that don't fit.
        """
        trimmed: list[CategoryDigest] = []
        remaining = max_items

        for section in sections:
            if remaining <= 0:
                break

            if section.item_count <= remaining:
                trimmed.append(section)
                remaining -= section.item_count
            else:
                # Partial: take only 'remaining' items
                partial = CategoryDigest(
                    id=section.id,
                    category=section.category,
                    date=section.date,
                    items=section.items[:remaining],
                    summary_text=section.summary_text,
                    summary_hindi=section.summary_hindi,
                    item_count=remaining,
                    has_updates=True,
                    generated_at=section.generated_at,
                )
                trimmed.append(partial)
                remaining = 0

        return trimmed

    @staticmethod
    def _extract_one_liners(summary_json: str) -> tuple[str, str]:
        """Extract 'quick_take' and 'quick_take_hindi' from a per-document summary JSON."""
        if not summary_json:
            return "", ""
        try:
            data = json.loads(summary_json)
            en = data.get("quick_take", "")
            hi = data.get("quick_take_hindi", "")
            return en, hi
        except json.JSONDecodeError:
            # Fallback for old non-JSON summaries
            import re
            match = re.search(r"Quick Take:\s*([\s\S]+?)(?=Key Details & Deadlines:|$)", summary_json, re.IGNORECASE)
            if match:
                return match.group(1).strip(), ""
            lines = [l.strip() for l in summary_json.split("\n") if l.strip()]
            return (lines[0] if lines else ""), ""
