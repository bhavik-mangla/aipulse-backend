"""
Crawler implementations for fetching content from various source types.
"""
from govnotify.crawlers.base import AbstractCrawler, CrawlResult
from govnotify.crawlers.rss_crawler import RSSCrawler

# Crawl4AICrawler is imported lazily to avoid heavy dependency at import time.
# Use: from govnotify.crawlers.crawl4ai_crawler import Crawl4AICrawler

__all__ = [
    "AbstractCrawler",
    "CrawlResult",
    "RSSCrawler",
]
