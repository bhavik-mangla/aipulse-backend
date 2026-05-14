"""
Source-based digest generation.
Groups processed documents by source and generates a daily SourceDigest.
"""
from __future__ import annotations

import uuid
import json
from datetime import datetime
from typing import Sequence

import structlog

from govnotify.models.document import ProcessedDocument
from govnotify.models.notification import SourceDigest, NotificationItem
from govnotify.utils.time import get_utc_now
from govnotify.constants import get_source_name

logger = structlog.get_logger(__name__)

class SourceDigestGenerator:
    """Generates SourceDigests from processed documents."""

    async def generate(
        self,
        source_id: str,
        source_name: str,
        date_str: str,
        documents: Sequence[ProcessedDocument],
    ) -> SourceDigest:
        """
        Generate a SourceDigest for a specific source.
        Args:
            source_id: The source identifier.
            source_name: Human readable name of the source.
            date_str: YYYY-MM-DD format date.
            documents: List of documents already filtered for this source and date.
        """
        digest_id = str(uuid.uuid4())
        
        if not documents:
            return SourceDigest(
                id=digest_id,
                source_id=source_id,
                source_name=source_name,
                date=date_str,
                items=[],
                summary_text="No new updates from this portal today.",
                summary_hindi="आज इस पोर्टल से कोई नया अपडेट नहीं है।",
                item_count=0,
                has_updates=False,
                generated_at=get_utc_now()
            )

        # Convert documents to NotificationItems
        items = [self._doc_to_item(doc) for doc in documents]

        # Generate consolidated source-level summaries
        # Highlight Critical/High impact items
        summary_lines = []
        summary_lines_hindi = []
        for item in items:
            prefix = "🚨 " if item.impact_tier in ["Critical", "High"] else "• "
            try:
                data = json.loads(item.summary)
                take = data.get('quick_take', item.title)
                take_hi = data.get('quick_take_hindi', item.title)
                
                summary_lines.append(f"{prefix}{take}")
                summary_lines_hindi.append(f"{prefix}{take_hi}")
            except:
                summary_lines.append(f"{prefix}{item.title}")
                summary_lines_hindi.append(f"{prefix}{item.title}")
        
        consolidated_summary = "\n".join(summary_lines)
        consolidated_summary_hindi = "\n".join(summary_lines_hindi)

        return SourceDigest(
            id=digest_id,
            source_id=source_id,
            source_name=source_name,
            date=date_str,
            items=items,
            summary_text=consolidated_summary,
            summary_hindi=consolidated_summary_hindi,
            item_count=len(items),
            has_updates=True,
            generated_at=get_utc_now()
        )

    @staticmethod
    def _doc_to_item(doc: ProcessedDocument) -> NotificationItem:
        """Map ProcessedDocument to NotificationItem."""
        return NotificationItem(
            document_id=doc.id,
            title=doc.title,
            summary=doc.summary,
            category=doc.primary_category,
            source_id=doc.source_id,
            source_name=get_source_name(doc.source_id),
            source_url=doc.source_url,
            ingested_at=doc.ingested_at,
            regions=doc.regions,
            departments=doc.departments,
            impact_tier=doc.impact_tier,
            affected_audience=doc.affected_audience,
            relevance_score=doc.confidence_score,
        )
