"""
Source registry with plugin pattern.
Provides a central registry for discovering and instantiating data sources.
Sources register themselves via the @register decorator or explicit registration.
"""
import structlog

from govnotify.sources.base import AbstractSource

logger = structlog.get_logger(__name__)


class SourceRegistry:
    """
    Central registry for all data sources.
    Usage:
        # Register via decorator
        @SourceRegistry.register
        class PIBSource(AbstractSource): ...

        # Or register explicitly
        SourceRegistry.add(PIBSource())

        # Retrieve
        source = SourceRegistry.get("pib_press_releases")

        # List all
        for s in SourceRegistry.all():
            logger.debug("source", source_id=s.source_id)
    """
    _sources: dict[str, AbstractSource] = {}

    @classmethod
    def register(cls, source_cls: type[AbstractSource]) -> type[AbstractSource]:
        """Class decorator: instantiate and register a source class."""
        instance = source_cls()
        cls._sources[instance.source_id] = instance
        logger.info("source_registered", source_id=instance.source_id)
        return source_cls

    @classmethod
    def add(cls, source: AbstractSource) -> None:
        """Register a source instance directly."""
        cls._sources[source.source_id] = source
        logger.info("source_registered", source_id=source.source_id)

    @classmethod
    def get(cls, source_id: str) -> AbstractSource:
        """Look up a registered source by ID."""
        if source_id not in cls._sources:
            available = list(cls._sources.keys())
            raise KeyError(
                f"Source {source_id} not registered. Available: {available}"
            )
        return cls._sources[source_id]

    @classmethod
    def all(cls) -> list[AbstractSource]:
        """Return all registered sources."""
        return list(cls._sources.values())

    @classmethod
    def list_ids(cls) -> list[str]:
        """Return all registered source IDs."""
        return list(cls._sources.keys())

    @classmethod
    def clear(cls) -> None:
        """Remove all registered sources (primarily for testing)."""
        cls._sources.clear()

    @classmethod
    def remove(cls, source_id: str) -> None:
        """Remove a specific source from the registry."""
        cls._sources.pop(source_id, None)
