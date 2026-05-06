"""
Document processing pipeline components.
Provides deduplication, parsing, enrichment, chunking, embedding, and the orchestrating pipeline that chains them together.
"""
from govnotify.processing.chunker import Chunker
from govnotify.processing.dedup import DeduplicationEngine
from govnotify.processing.embedder import Embedder
from govnotify.processing.enricher import Enricher
from govnotify.processing.parser import TextParser
from govnotify.processing.pipeline import PipelineResult, ProcessingPipeline

__all__ = [
    "Chunker",
    "DeduplicationEngine",
    "Embedder",
    "Enricher",
    "TextParser",
    "PipelineResult",
    "ProcessingPipeline",
]
