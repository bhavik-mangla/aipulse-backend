"""
Utility functions for data sources.
Includes shared date parsers, header builders, and common text processing.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

import random
from govnotify.constants import USER_AGENTS, DEFAULT_USER_AGENT

def get_standard_headers(user_agent: str | None = None) -> dict[str, str]:
    """Return a dictionary of standard headers for web scraping."""
    ua = user_agent or random.choice(USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }

from govnotify.utils.time import parse_indian_date

def clean_text(text: str) -> str:
    """Basic text cleanup: remove multiple whitespace, trim."""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()
