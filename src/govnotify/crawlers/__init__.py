"""
Crawler implementations.
"""
from govnotify.crawlers.base import AbstractCrawler, CrawlResult
from govnotify.crawlers.robust_news_crawler import RobustNewsCrawler

__all__ = [
    "AbstractCrawler",
    "CrawlResult",
    "RobustNewsCrawler",
]
