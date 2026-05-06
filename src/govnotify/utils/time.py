"""
Centralized time utilities for the GovNotify project.
All internal storage and processing should use UTC.
"""
from datetime import datetime, timezone
from typing import Optional
import re

def get_utc_now() -> datetime:
    """Return the current time in UTC with timezone info."""
    return datetime.now(timezone.utc)

def get_today_str() -> str:
    """Return today's date in YYYY-MM-DD format (UTC)."""
    return get_utc_now().strftime("%Y-%m-%d")

def ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime object has UTC timezone info."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def format_iso(dt: datetime) -> str:
    """Format a datetime as an ISO 8601 string."""
    return dt.isoformat()

def parse_iso(dt_str: str) -> datetime:
    """Parse an ISO 8601 string into a datetime object, ensuring UTC."""
    dt = datetime.fromisoformat(dt_str)
    return ensure_utc(dt)

def parse_indian_date(date_str: str) -> Optional[datetime]:
    """
    Attempt to parse common Indian date formats found on government portals.
    Supports:
    - DD-MM-YYYY
    - DD/MM/YYYY
    - DD Month YYYY (e.g., 12 Jan 2024)
    - Month DD, YYYY (e.g., January 12, 2024)
    Returns UTC datetime.
    """
    if not date_str:
        return None
    
    date_str = date_str.strip()
    
    # Try common formats
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            # Handle ordinal suffixes (1st, 2nd, 3rd, 4th...) by removing them before parsing
            clean_date = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_str)
            dt = datetime.strptime(clean_date, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
            
    # Try regex-based extraction if direct parsing fails
    # Match: Jan 12, 2024 or 12 Jan 2024
    match = re.search(r"(\d{1,2})?\s*([A-Za-z]{3,9})\s+(\d{1,2})?,?\s+(\d{4})", date_str)
    if match:
        day = match.group(1) or match.group(3) or "01"
        month = match.group(2)
        year = match.group(4)
        for fmt in ("%d %B %Y", "%d %b %Y"):
            try:
                dt = datetime.strptime(f"{day} {month} {year}", fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

    return None
