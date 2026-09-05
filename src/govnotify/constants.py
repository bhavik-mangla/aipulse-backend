"""
Centralized constants.
Ensures consistency across ingestion, processing, API, and frontend.
"""
import datetime
from datetime import timezone
from enum import Enum


class NewsCategory(str, Enum):
    """Topic categories for general news."""
    WORLD = "world"
    BUSINESS = "business"
    POLITICS = "politics"
    TECHNOLOGY = "technology"
    SCIENCE = "science"
    HEALTH = "health"
    SPORTS = "sports"
    ENTERTAINMENT = "entertainment"
    ENVIRONMENT = "environment"
    EDUCATION = "education"
    OTHER = "other"


# The taxonomy used to be government-notice shaped (jobs, schemes, gazette,
# tax, local_governance and so on). Documents ingested under it are still in
# the database, so map the old values onto the closest news category when one
# is read back. Anything unmapped falls through to OTHER.
LEGACY_CATEGORY_MAP = {
    "jobs": NewsCategory.BUSINESS,
    "schemes": NewsCategory.POLITICS,
    "tax": NewsCategory.BUSINESS,
    "finance": NewsCategory.BUSINESS,
    "agriculture": NewsCategory.BUSINESS,
    "infrastructure": NewsCategory.BUSINESS,
    "legal": NewsCategory.POLITICS,
    "gazette": NewsCategory.POLITICS,
    "defense": NewsCategory.POLITICS,
    "local_governance": NewsCategory.POLITICS,
    "social_welfare": NewsCategory.POLITICS,
    "women_child": NewsCategory.POLITICS,
    "education": NewsCategory.EDUCATION,
    "health": NewsCategory.HEALTH,
    "technology": NewsCategory.TECHNOLOGY,
    "environment": NewsCategory.ENVIRONMENT,
    "other": NewsCategory.OTHER,
}


def parse_category(value: str | None) -> NewsCategory:
    """
    Read a stored category, tolerating values from the old taxonomy.

    Never raises: an unrecognised value becomes OTHER rather than failing the
    request, because historical rows predate this enum.
    """
    if not value:
        return NewsCategory.OTHER
    try:
        return NewsCategory(value)
    except ValueError:
        return LEGACY_CATEGORY_MAP.get(value, NewsCategory.OTHER)


# Backwards-compatible alias: plenty of modules still import NoticeCategory.
NoticeCategory = NewsCategory


class Country(str, Enum):
    """
    Feed scopes a reader can choose between.

    WORLD is not a country: it is international coverage from global outlets,
    and it is the sensible default for a reader whose own country is not yet
    supported.
    """
    WORLD = "world"
    INDIA = "in"
    UNITED_STATES = "us"


COUNTRIES = [
    {"code": Country.WORLD.value, "name": "World", "flag": "\U0001F30D", "language": "en"},
    {"code": Country.INDIA.value, "name": "India", "flag": "\U0001F1EE\U0001F1F3", "language": "en"},
    {"code": Country.UNITED_STATES.value, "name": "United States", "flag": "\U0001F1FA\U0001F1F8", "language": "en"},
]

DEFAULT_COUNTRY = Country.WORLD.value

def is_valid_country(code: str | None) -> bool:
    return bool(code) and code in {c["code"] for c in COUNTRIES}


# How prominent a story is. Kept as four tiers so existing rows stay valid,
# but scored on news significance rather than regulatory impact.
IMPACT_TIERS = [
    "Critical",
    "High",
    "Medium",
    "Low",
]

# Localised category names.
#
# Summaries and UI strings are English-only for now. Hindi translation was
# removed and preserved on the archive/hindi-localisation branch: it doubled
# LLM output tokens for every article, and doing translation properly means
# handling several languages rather than special-casing one.
#
# To add a language, add its code here and to the app's I18N table. Nothing
# else in the pipeline is language-specific.
CATEGORY_NAMES = {
    "en": {
        "world": "World",
        "business": "Business",
        "politics": "Politics",
        "technology": "Technology",
        "science": "Science",
        "health": "Health",
        "sports": "Sports",
        "entertainment": "Entertainment",
        "environment": "Environment",
        "education": "Education",
        "other": "Other",
    },
}

SUPPORTED_LANGUAGES = list(CATEGORY_NAMES)
DEFAULT_LANGUAGE = "en"

CATEGORY_EMOJIS = {
    "world": "\U0001F30D",
    "business": "\U0001F4C8",
    "politics": "\U0001F3DB",
    "technology": "\U0001F4BB",
    "science": "\U0001F52C",
    "health": "\U0001F3E5",
    "sports": "\U000026BD",
    "entertainment": "\U0001F3AC",
    "environment": "\U0001F331",
    "education": "\U0001F393",
    "other": "\U0001F517",
}

# Human-readable names for sources. Source ids are <slug>_<country>.
SOURCE_NAMES = {
    # World
    "bbc_world": "BBC News",
    "france24_world": "France 24",
    "dw_world": "DW",
    # India
    "thehindu_in": "The Hindu",
    "indianexpress_in": "Indian Express",
    "et_top_stories": "Economic Times",
    "mint_top_stories": "Mint",
    "bs_top_stories": "Business Standard",
    # United States
    "npr_us": "NPR",
    "csmonitor_us": "The Christian Science Monitor",
    "cbs_us": "CBS News",
    "abc_us": "ABC News",
}


def get_source_name(source_id: str) -> str:
    """Get human-readable name for a source ID."""
    return SOURCE_NAMES.get(source_id, source_id.replace("_", " ").title())


# A collection of modern browser user-agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

DEFAULT_USER_AGENT = USER_AGENTS[0]

# Global filter to hide old/inconsistent data from before official launch
HIDE_BEFORE_DATETIME = datetime.datetime(2026, 4, 28, 0, 0, 0, tzinfo=timezone.utc)
