"""
GovNotify custom exception hierarchy.
All domain-level exceptions inherit from "GovNotifyError".
Never catch bare "Exception" in production code - use the appropriate subclass from this module instead.
"""
from __future__ import annotations


class GovNotifyError(Exception):
    """Base exception for the entire GovNotify application."""

    def __init__(self, message: str = "", cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


# --- Source / Ingestion ---

class SourceError(GovNotifyError):
    """Base for all source-related errors."""
    pass


class SourceFetchError(SourceError):
    """A source failed to fetch data (network, auth, scrape error)."""

    def __init__(
        self,
        source_id: str,
        message: str = "",
        cause: Exception | None = None,
    ):
        self.source_id = source_id
        self.message = message
        full_msg = f"[{source_id}] {message}" if message else f"Fetch failed for {source_id}"
        super().__init__(full_msg, cause=cause)


class SourceParseError(SourceError):
    """Could not parse the response from a source."""

    def __init__(
        self,
        source_id: str,
        message: str = "",
        cause: Exception | None = None,
    ):
        self.source_id = source_id
        super().__init__(message or f"Parse error for {source_id}", cause=cause)


class SourceHealthError(SourceError):
    """A source's health check reports degraded status."""

    def __init__(self, source_id: str, consecutive_failures: int = 0):
        self.source_id = source_id
        self.consecutive_failures = consecutive_failures
        super().__init__(
            f"Source {source_id} degraded after {consecutive_failures} failures"
        )


# --- Processing Pipeline ---

class ProcessingError(GovNotifyError):
    """Base for processing pipeline errors."""
    pass


class ParsingError(ProcessingError):
    """HTML / PDF / content parsing failure."""
    pass


class EmbeddingError(ProcessingError):
    """Embedding generation failed (LLM provider error)."""
    pass


class EnrichmentError(ProcessingError):
    """Category / metadata enrichment failed."""
    pass


class ChunkingError(ProcessingError):
    """Document chunking failure."""
    pass


class DeduplicationError(ProcessingError):
    """Deduplication check failed (storage error, not a duplicate)."""
    pass


# --- Storage ---

class StorageError(GovNotifyError):
    """Base for storage-layer errors."""
    pass


class DatabaseError(StorageError):
    """PostgreSQL / SQL error."""
    pass


class VectorStoreError(StorageError):
    """Qdrant interaction failed."""
    pass


class CacheError(StorageError):
    """Redis read/write error."""
    pass


# --- Delivery ---

class DeliveryError(GovNotifyError):
    """Base for delivery channel errors."""

    def __init__(
        self,
        channel_id: str,
        message: str = "",
        *,
        permanent: bool = False,
        cause: Exception | None = None,
    ):
        self.channel_id = channel_id
        self.permanent = permanent
        super().__init__(
            message or f"Delivery failed on {channel_id}", cause=cause
        )


class EmailDeliveryError(DeliveryError):
    """Email sending failed."""

    def __init__(self, message: str = "", **kwargs):
        super().__init__(channel_id="email", message=message, **kwargs)


class TelegramDeliveryError(DeliveryError):
    """Telegram message sending failed."""

    def __init__(self, message: str = "", **kwargs):
        super().__init__(channel_id="telegram", message=message, **kwargs)


# --- Auth / API ---

class AuthError(GovNotifyError):
    """Authentication or authorization failure."""
    pass


class RateLimitExceeded(GovNotifyError):
    """Caller exceeded their per-user rate limit."""

    def __init__(self, user_id: str, limit: int, window_seconds: int = 60):
        self.user_id = user_id
        self.limit = limit
        self.window_seconds = window_seconds
        super().__init__(
            f"Rate limit exceeded: {limit} requests per {window_seconds}s"
        )


# --- Configuration ---

class ConfigError(GovNotifyError):
    """Missing or invalid configuration."""
    pass
