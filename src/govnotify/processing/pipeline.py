"""
Processing pipeline orchestrator.
Chains all processing steps in order:
RawDocument -> Dedup -> Parse -> Enrich -> Chunk -> Embed -> Store
Each step is independently testable; the pipeline composes them.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import structlog

from govnotify.config import get_settings
from govnotify.constants import DEFAULT_COUNTRY
from govnotify.models.document import ProcessedDocument
from govnotify.models.source import RawDocument
from govnotify.processing.dedup import DeduplicationEngine
from govnotify.processing.enricher import Enricher
from govnotify.processing.image_resolver import ImageResolver
from govnotify.processing.parser import TextParser

logger = structlog.get_logger(__name__)


def _parse_published_at(value) -> datetime | None:
    """Accept the ISO string the crawler stores, tolerating anything odd."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


class PipelineResult:
    """Result of processing a single document through the pipeline."""

    def __init__(self) -> None:
        self.document: ProcessedDocument | None = None
        self.is_duplicate: bool = False
        self.skipped: bool = False
        self.duplicate_of: str | None = None
        self.skip_reason: str = ""
        self.error: str | None = None


class ProcessingPipeline:
    """
    Orchestrates the full document processing pipeline.
    Usage:
        pipeline = ProcessingPipeline()
        result = await pipeline.process(raw_doc)
        if not result.skipped and not result.error:
            # result.document is the ProcessedDocument
            await store(result)
    """

    def __init__(
        self,
        dedup: DeduplicationEngine | None = None,
        parser: TextParser | None = None,
        enricher: Enricher | None = None,
        image_resolver: ImageResolver | None = None,
        enable_llm: bool | None = None,
    ) -> None:
        settings = get_settings()
        self.dedup = dedup or DeduplicationEngine()
        self.parser = parser or TextParser()
        self.enricher = enricher or Enricher()
        self.image_resolver = image_resolver or ImageResolver()
        self.enable_llm = enable_llm if enable_llm is not None else settings.enable_llm

    async def check_duplicate(self, doc: RawDocument, session=None) -> tuple[bool, str | None]:
        """
        Check if a document is a duplicate without running the full pipeline.
        Useful for pre-fetch dedup in crawlers.
        """
        return await self.dedup.is_duplicate(doc, session=session)

    async def process(self, raw_doc: RawDocument, session=None) -> PipelineResult:
        """
        Process a single RawDocument through the full pipeline.
        Steps:
        1. Dedup check (exact hash + MinHash)
        2. Parse / extract text
        3. Enrich (classify, NER, summarize)
        4. Resolve Image
        5. Build ProcessedDocument
        Args:
            raw_doc: Raw document from a source.
            session: Optional AsyncSession for DB dedup.
        Returns:
            PipelineResult with the processed document.
        """
        result = PipelineResult()
        try:
            # Step 1: Dedup check
            is_dup, dup_id = await self.dedup.is_duplicate(raw_doc, session=session)
            if is_dup:
                result.is_duplicate = True
                result.duplicate_of = dup_id
                result.skipped = True
                result.skip_reason = f"Duplicate of {dup_id}"
                logger.info(
                    "pipeline_skip_duplicate",
                    source_id=raw_doc.source_id,
                    content_hash=raw_doc.content_hash[:16],
                    duplicate_of=dup_id,
                )
                return result

            # Step 2: Parse / extract text
            clean_text = await self.parser.extract(
                raw_doc.raw_content, raw_doc.content_type
            )
            if not clean_text or len(clean_text) < 30:
                result.skipped = True
                result.skip_reason = "Insufficient text after extraction"
                logger.info(
                    "pipeline_skip_no_text",
                    title=raw_doc.title[:60],
                    source_id=raw_doc.source_id,
                    text_len=len(clean_text),
                )
                return result

            # Step 3: Enrich (classify, NER, summarize)
            # Detect language
            language = self.parser.detect_language(clean_text)
            
            country = raw_doc.metadata.get("country") or DEFAULT_COUNTRY

            if self.enable_llm:
                enrichment = await self.enricher.enrich(
                    clean_text, raw_doc.title, country=country
                )
            else:
                # Basic rule-based enrichment if LLM disabled
                enrichment = self.enricher.classify(clean_text, raw_doc.title)
                enrichment.summary = ""  # No summary without LLM
                enrichment.confidence_score = 0.5

            # Generate document ID
            doc_id = str(uuid.uuid4())

            # Step 4: Resolve Image
            image_url = await self.image_resolver.resolve_image(
                raw_doc, enrichment.image_search_query
            )

            # Step 5: Register in the dedup indices and keep the SimHash, so
            # near-duplicate detection survives into later runs.
            simhash = self.dedup.register(
                doc_id, raw_doc.content_hash, raw_doc.raw_content, raw_doc.title
            )

            # Step 6: Build ProcessedDocument
            processed = ProcessedDocument(
                id=doc_id,
                source_id=raw_doc.source_id,
                # Use portal_url from metadata if available, else fallback to source listing URL
                source_url=raw_doc.metadata.get("portal_url", raw_doc.source_url),
                fetch_url=raw_doc.fetch_url,
                title=raw_doc.title,
                clean_text=clean_text,
                summary=enrichment.summary,
                summary_hindi=enrichment.summary_hindi,
                image_url=image_url,
                image_search_query=enrichment.image_search_query,
                categories=enrichment.categories,
                regions=enrichment.regions,
                primary_category=enrichment.primary_category,
                departments=[enrichment.department] if enrichment.department else [],
                impact_tier=enrichment.impact_tier,
                entities=enrichment.entities,
                country=country,
                ingested_at=raw_doc.fetched_at,
                published_at=_parse_published_at(raw_doc.metadata.get("published_at")),
                notification_number=enrichment.notification_number,
                language=language,
                content_hash=raw_doc.content_hash,
                simhash=simhash,
                is_duplicate=False,
                confidence_score=enrichment.confidence_score,
            )

            result.document = processed

            logger.info(
                "pipeline_complete",
                doc_id=doc_id,
                title=raw_doc.title[:60],
                source_id=raw_doc.source_id,
                confidence=enrichment.confidence_score,
                categories=[c.value for c in enrichment.categories],
            )


        except Exception as exc:
            result.error = str(exc)
            logger.exception(
                "pipeline_error",
                source_id=raw_doc.source_id,
                title=raw_doc.title[:60],
                error=str(exc),
            )

        return result

    async def process_batch(
        self, raw_docs: list[RawDocument], session=None
    ) -> list[PipelineResult]:
        """
        Process a batch of RawDocuments.
        Args:
            raw_docs: List of raw documents.
            session: Optional AsyncSession.
        Returns:
            List of PipelineResult, one per document.
        """
        results: list[PipelineResult] = []
        new_count = 0
        dup_count = 0

        for doc in raw_docs:
            result = await self.process(doc, session=session)
            results.append(result)
            if result.is_duplicate:
                dup_count += 1
            elif not result.skipped and not result.error:
                new_count += 1

        logger.info(
            "pipeline_batch_complete",
            total=len(raw_docs),
            new=new_count,
            duplicates=dup_count,
            skipped=len(raw_docs) - new_count - dup_count,
        )
        return results
