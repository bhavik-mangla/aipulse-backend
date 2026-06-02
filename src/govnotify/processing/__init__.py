"""
Document processing pipeline components.
Provides deduplication, parsing, enrichment, chunking, embedding, and the orchestrating pipeline that chains them together.
"""
from govnotify.processing.dedup import DeduplicationEngine
from govnotify.processing.enricher import Enricher
from govnotify.processing.parser import TextParser
from govnotify.processing.pipeline import PipelineResult, ProcessingPipeline

__all__ = [
    "DeduplicationEngine",
    "Enricher",
    "TextParser",
    "PipelineResult",
    "ProcessingPipeline",
]
