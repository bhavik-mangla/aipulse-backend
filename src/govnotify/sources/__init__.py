"""
Data source plugins.

Importing this package registers every configured source with the registry.
"""
from govnotify.sources.base import AbstractSource
from govnotify.sources.news_rss_source import NewsRSSSource
from govnotify.sources.registry import SourceRegistry

__all__ = [
    "AbstractSource",
    "SourceRegistry",
    "NewsRSSSource",
]
