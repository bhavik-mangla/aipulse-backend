"""
Category digest generation - V2 core intelligence.
For each NoticeCategory, groups today's processed documents and assembles a consolidated summary from their existing AI summaries.
Zero LLM calls during this phase.

Flow (Phase 1 - runs at 6:30 AM IST daily):
For each category:
1. Query PG for the last 24h of processed docs matching this category
2. If none -> CategoryDigest(has_updates=False)
3. Else -> build NotificationItems, assemble combined summary
4. Cache in Redis (48h TTL), upsert into PG category_digests table
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional, Sequence

import structlog

from govnotify.config import get_settings
from govnotify.constants import NoticeCategory, get_source_name
from govnotify.models.document import ProcessedDocument
from govnotify.models.notification import CategoryDigest, NotificationItem
from govnotify.utils.time import get_utc_now

logger = structlog.get_logger(__name__)


# Max documents per category digest to keep LLM context manageable
MAX_ITEMS_PER_DIGEST = 20


class CategoryDigestGenerator:
    """
    Generates a CategoryDigest for a given category and date.
    This class is stateless and can be reused across categories/dates.
    All I/O (DB, Redis, LLM) is async.
    """

    def __init__(
        self,
        generate_hindi: bool = False,
        llm_model: str = "gemini/gemma-4-31b-it",

    ) -> None:
        self._settings = get_settings()
        self._llm_model = llm_model
        # Hindi is now generated at document level during ingestion
        self.generate_hindi = True 

    # Public API

    async def generate(
        self,
        category: NoticeCategory,
        date_str: str,
        documents: Sequence[ProcessedDocument],
    ) -> CategoryDigest:
        """
        Generate a CategoryDigest from a list of processed documents.
        Args:
            category: The category to generate a digest for.
            date_str: Date string in YYYY-MM-DD format.
            documents: Pre-filtered documents for this category and date.
        Returns:
            A fully populated CategoryDigest.
        """
        digest_id = str(uuid.uuid4())

        # Filter to this category & cap at MAX_ITEMS_PER_DIGEST
        matching = [
            d for d in documents
            if category in d.categories or d.primary_category == category
        ][:MAX_ITEMS_PER_DIGEST]

        if not matching:
            logger.info(
                "no_documents_for_category",
                category=category.value,
                date=date_str,
            )
            return CategoryDigest(
                id=digest_id,
                category=category,
                date=date_str,
                items=[],
                summary_text="",
                summary_hindi="",
                item_count=0,
                has_updates=False,
                generated_at=get_utc_now(),
                model_used=self._llm_model,
                llm_cost_usd=0.0,
            )

        # Build notification items
        items = [self._doc_to_item(doc, category) for doc in matching]

        # Generate combined summaries from per-item summaries
        summary_text, summary_hindi = await self._generate_combined_summary(items)

        digest = CategoryDigest(
            id=digest_id,
            category=category,
            date=date_str,
            items=items,
            summary_text=summary_text,
            summary_hindi=summary_hindi,
            item_count=len(items),
            has_updates=True,
            generated_at=get_utc_now(),
            model_used=self._llm_model,
            llm_cost_usd=0.0,
        )

        logger.info(
            "category_digest_generated",
            category=category.value,
            date=date_str,
            item_count=len(items),
        )
        return digest

    async def generate_all(
        self,
        date_str: str,
        documents: Sequence[ProcessedDocument],
    ) -> list[CategoryDigest]:
        """
        Generate digests for ALL categories for a given date.
        """
        digests: list[CategoryDigest] = []
        for category in NoticeCategory:
            digest = await self.generate(category, date_str, documents)
            digests.append(digest)
        return digests

    # Private helpers

    @staticmethod
    def _doc_to_item(
        doc: ProcessedDocument, category: NoticeCategory
    ) -> NotificationItem:
        """Convert a ProcessedDocument to a NotificationItem."""
        return NotificationItem(
            document_id=doc.id,
            title=doc.title,
            summary=doc.summary or (
                doc.clean_text[:300] if doc.clean_text else ""),
            category=category,
            source_id=doc.source_id,
            source_name=get_source_name(doc.source_id),
            source_url=doc.source_url,
            regions=doc.regions,
            departments=doc.departments,
            impact_tier=doc.impact_tier,
            affected_audience=doc.affected_audience,
            ingested_at=doc.ingested_at,
            relevance_score=doc.confidence_score,
        )

    async def _generate_combined_summary(
        self,
        items: list[NotificationItem],
    ) -> tuple[str, str]:
        """
        Build a combined summary from individual item summaries.
        Uses the "Quick Take" from each document.
        """
        if not items:
            return "", ""

        summaries = []
        summaries_hindi = []
        for item in items:
            en, hi = self._extract_one_liners(item.summary)
            if en:
                summaries.append(f"• {en}")
            else:
                summaries.append(f"• {item.title}")
            
            if hi:
                summaries_hindi.append(f"• {hi}")
            else:
                summaries_hindi.append(f"• {item.title}")
        
        return "\n".join(summaries), "\n".join(summaries_hindi)

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
