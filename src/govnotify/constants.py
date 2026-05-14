"""
Centralized constants for GovNotify.
Ensures consistency across ingestion, processing, API, and frontend.
"""
import datetime
from enum import Enum
from datetime import timezone


class NoticeCategory(str, Enum):
    """Categories for government notices."""
    JOBS = "jobs"
    SCHEMES = "schemes"
    TAX = "tax"
    AGRICULTURE = "agriculture"
    EDUCATION = "education"
    HEALTH = "health"
    LEGAL = "legal"
    GAZETTE = "gazette"
    FINANCE = "finance"
    INFRASTRUCTURE = "infrastructure"
    ENVIRONMENT = "environment"
    DEFENSE = "defense"
    TECHNOLOGY = "technology"
    LOCAL_GOVERNANCE = "local_governance"
    WOMEN_CHILD = "women_child"
    SOCIAL_WELFARE = "social_welfare"
    OTHER = "other"


# Master list of Audiences (used by LLM and Frontend)
AUDIENCES = [
    "Retail Investors",
    "Farmers",
    "MSMEs",
    "Students",
    "Corporate Legal",
    "Tax Professionals",
    "Chartered Accountants",
    "Bankers",
    "Insurance Professionals",
    "Insolvency Professionals",
    "Fintech Entities",
    "Healthcare Providers",
    "Exporters",
    "Tech Professionals"
]

# Master list of Impact Tiers
IMPACT_TIERS = [
    "Critical",
    "High",
    "Medium",
    "Low"
]

# Hindi translations for Categories
CATEGORY_NAMES_HI = {
    "jobs": "नौकरियां",
    "schemes": "योजनाएं",
    "tax": "कर (Tax)",
    "agriculture": "कृषि",
    "education": "शिक्षा",
    "health": "स्वास्थ्य",
    "legal": "कानूनी",
    "gazette": "राजपत्र (Gazette)",
    "finance": "वित्त",
    "infrastructure": "बुनियादी ढांचा",
    "environment": "पर्यावरण",
    "defense": "रक्षा",
    "local_governance": "स्थानीय शासन",
    "technology": "प्रौद्योगिकी",
    "women_child": "महिला एवं बाल",
    "social_welfare": "समाज कल्याण",
    "other": "अन्य",
}

# Category Emojis
CATEGORY_EMOJIS = {
    "jobs": "💼",
    "schemes": "📜",
    "tax": "💰",
    "agriculture": "🌾",
    "education": "🎓",
    "health": "🏥",
    "legal": "⚖️",
    "gazette": "🗞️",
    "finance": "🏦",
    "infrastructure": "🏗️",
    "environment": "🌱",
    "defense": "🛡️",
    "local_governance": "🏘️",
    "technology": "💻",
    "women_child": "👩‍👧",
    "social_welfare": "🤝",
    "other": "🔗",
}

# Category Descriptions
CATEGORY_DESCRIPTIONS = {
    "jobs": "Government job notifications, UPSC, SSC, state PSC recruitment",
    "schemes": "Government schemes, subsidies, yojanas for citizens",
    "tax": "Tax policy changes, GST updates, Income Tax notifications",
    "agriculture": "Agricultural policy, MSP, crop insurance, farming subsidies",
    "education": "Education policy, scholarships, university notices, exam schedules",
    "health": "Health advisories, insurance, AYUSH, medical regulations",
    "legal": "Court orders, legal amendments, regulatory changes",
    "gazette": "Official Gazette publications, ordinances, statutory rules",
    "finance": "Banking regulations, RBI circulars, financial market updates",
    "infrastructure": "Roads, railways, smart cities, housing schemes",
    "environment": "Environmental clearances, pollution control, climate policy",
    "defense": "Defence procurement, military recruitment, veteran affairs",
    "local_governance": "Municipal, panchayat, and state-level governance notices",
    "technology": "IT policy, digital India initiatives, cybersecurity directives",
    "women_child": "Women and child development schemes, ICDS, maternity benefits",
    "social_welfare": "Other government notifications and circulars",
    "other": "Other government notifications and circulars",
}

# Human-readable names for sources
SOURCE_NAMES = {
    "et_top_stories": "Economic Times",
    "mint_top_stories": "Mint",
    "bs_top_stories": "Business Standard",
    "sebi_news": "SEBI",
    "rbi_press_releases": "RBI Press Releases",
    "rbi_circulars": "RBI Circulars",
    "pib_press_releases": "PIB",
    "income_tax": "Income Tax Department",
    "mha_updates": "Ministry of Home Affairs",
    "meity_updates": "MeitY",
    "irdai_updates": "IRDAI",
    "ibbi_updates": "IBBI",
    "mca_updates": "MCA",
    "egazette_central": "e-Gazette Central",
}


def get_source_name(source_id: str) -> str:
    """Get human-readable name for a source ID."""
    return SOURCE_NAMES.get(source_id, source_id.replace("_", " ").title())

# I18N Strings for UI/Emails
I18N = {
    "en": {
        "digest_title": "GovNotify Daily Digest",
        "digest_header": "GovNotify News Flash",
        "updates": "updates",
        "update": "update",
        "no_updates": "No new government updates today. We'll keep watching!",
        "no_updates_portal": "No updates today.",
        "source": "Source",
        "view_official": "View Official Source",
        "unsubscribe_msg": "You're receiving this because you subscribed to GovNotify.",
        "manage_prefs": "Manage Preferences",
        "unsubscribe": "Unsubscribe",
        "hq_address": "GovNotify HQ, Sector 44, Gurgaon, Haryana, India",
    },
    "hi": {
        "digest_title": "GovNotify दैनिक समाचार सारांश",
        "digest_header": "GovNotify न्यूज़ फ़्लैश",
        "updates": "अपडेट",
        "update": "अपडेट",
        "no_updates": "आज कोई नया सरकारी अपडेट नहीं है। हम नज़र बनाए रखेंगे!",
        "no_updates_portal": "आज कोई अपडेट नहीं है।",
        "source": "स्रोत",
        "view_official": "आधिकारिक स्रोत देखें",
        "unsubscribe_msg": "आपको यह प्राप्त हो रहा है क्योंकि आपने GovNotify की सदस्यता ली है।",
        "manage_prefs": "प्राथमिकताएं प्रबंधित करें",
        "unsubscribe": "सदस्यता समाप्त करें",
        "hq_address": "GovNotify मुख्यालय, सेक्टर 44, गुड़गांव, हरियाणा, भारत",
    }
}

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
