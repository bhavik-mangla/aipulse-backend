"""
Document enrichment - classification, NER, and metadata extraction.
Uses LLM (via litellm) for per-document structured summarization.
Uses rule-based heuristics for classification.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

import structlog

from govnotify.config import get_settings
from govnotify.constants import NoticeCategory, AUDIENCES, IMPACT_TIERS

logger = structlog.get_logger(__name__)

# List of valid categories for the LLM
CATEGORIES_LIST = ", ".join([c.value for c in NoticeCategory])

# List of valid audiences to match frontend
AUDIENCES_LIST = ", ".join(AUDIENCES)

# List of valid impact tiers
IMPACT_TIERS_LIST = ", ".join(IMPACT_TIERS)

SUMMARY_PROMPT = """
You are a government notice summarizer for Indian citizens.
Extract a concise, high-signal summary and metadata from the document.
Generate both English and Hindi versions in the same response.

Valid Categories: {categories}
Valid Audiences: {audiences}
Valid Impact Tiers: {impact_tiers}

Guidelines:
- Tone: Professional, easy for humans to read quickly, and all-inclusive of critical facts.
- Style: Concise but comprehensive.
- Hindi version: Natural, professional translation of the summary elements.
- Impact Tier: Categorize as one of: {impact_tiers}.
- Affected Audience: Identify specific groups from the 'Valid Audiences' list above. You can select multiple.
- Primary Category: Select the MOST relevant category from the 'Valid Categories' list above.
- STRICTLY FACTUAL: Only include info explicitly present. Do NOT hallucinate.

Input text:
{text}

Respond with ONLY valid JSON:
{{
  "quick_take": "A 1-3 line summary in English.",
  "quick_take_hindi": "हिंदी में 1-3 पंक्तियों का सारांश।",
  "key_details": [
    "Important facts or requirements in English"
  ],
  "key_details_hindi": [
    "हिंदी में महत्वपूर्ण तथ्य या आवश्यकताएं"
  ],
  "impact_tier": "Critical/High/Medium/Low",
  "affected_audience": ["Group 1", "Group 2"],
  "primary_category": "category_name",
  "action_required": "Specific action needed or 'None'"
}}
"""


class EnrichmentResult:
    """Result of document enrichment."""

    def __init__(self) -> None:
        self.categories: list[NoticeCategory] = []
        self.primary_category: NoticeCategory = NoticeCategory.OTHER
        self.notification_number: str | None = None
        self.department: str = ""
        self.regions: list[str] = ["national"]
        self.entities: dict[str, list[str]] = {
            "persons": [],
            "organizations": [],
            "dates": [],
            "amounts": [],
            "schemes": [],
        }
        self.summary: str = ""  # Will store English JSON string or full JSON
        self.summary_hindi: str = "" # Will store Hindi summary text
        self.impact_tier: str = "Medium"
        self.affected_audience: list[str] = []
        self.confidence_score: float = 0.0


class Enricher:
    """Enrich documents with classification, entities, and summaries."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def enrich(self, clean_text: str, title: str = "") -> EnrichmentResult:
        """
        Classify, extract entities, and summarize a document.
        Uses rule-based classification and LLM-based structured summarization.
        Args:
            clean_text: Cleaned document text.
            title: Document title for additional context.
        Returns:
            EnrichmentResult with all extracted metadata.
        """
        combined_text = f"{title}\n\n{clean_text}" if title else clean_text
        # Increase limit to capture most documents fully while staying within safety bounds
        truncated = combined_text[:50000]

        # Use rule-based classification as a baseline
        result = self._rule_based_classify(clean_text, title)
        result.confidence_score = 0.5

        # Generate Summary if enabled
        if self._settings.enable_llm:
            summary_data = await self._llm_summarize(truncated)
            if summary_data:
                # Store full JSON in summary, but also extract Hindi and metadata for dedicated fields
                result.summary = json.dumps(summary_data)
                result.summary_hindi = summary_data.get("quick_take_hindi", "")
                result.impact_tier = summary_data.get("impact_tier", "Medium")
                result.affected_audience = summary_data.get("affected_audience", [])
                
                # Override rule-based primary category if LLM provided a valid one
                llm_cat = summary_data.get("primary_category", "").lower()
                try:
                    if llm_cat:
                        result.primary_category = NoticeCategory(llm_cat)
                        if result.primary_category not in result.categories:
                            result.categories.append(result.primary_category)
                except ValueError:
                    logger.warning("invalid_llm_category", category=llm_cat)
        
        if not result.summary:
            # Fallback: extractive summary as JSON
            fallback_take = self._extractive_summary(clean_text)
            result.summary = json.dumps({
                "quick_take": fallback_take,
                "quick_take_hindi": "",
                "key_details": [],
                "key_details_hindi": [],
                "impact_tier": "Medium",
                "affected_audience": [],
                "primary_category": result.primary_category.value,
                "action_required": "None"
            })

        return result

    async def _llm_summarize(self, text: str) -> dict | None:
        """
        Generate a structured summary using LLM.
        Args:
            text: Truncated document text.
        Returns:
            Dictionary of summary data, or None if LLM unavailable.
        """
        try:
            from govnotify.processing.llm_router import get_completion
            prompt = SUMMARY_PROMPT.format(
                categories=CATEGORIES_LIST,
                audiences=AUDIENCES_LIST,
                impact_tiers=IMPACT_TIERS_LIST,
                text=text
            )
            content = await get_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=600,
            )
            
            if not content:
                return None
            
            # Clean markdown JSON blocks if present
            if content.startswith("```"):
                content = re.sub(r"```[a-z]*\n", "", content)
                content = re.sub(r"\n```", "", content)
                
            # Validate JSON
            data = json.loads(content)
            if "quick_take" in data and "key_details" in data:
                return data
            return None
        except Exception as exc:
            logger.warning("llm_summarize_failed", error=str(exc))
            return None

    def _rule_based_classify(
        self, text: str, title: str = ""
    ) -> EnrichmentResult:
        """
        Fallback: rule-based classification using keyword matching.
        Args:
            text: Document text.
            title: Document title.
        Returns:
            EnrichmentResult with best-effort classification.
        """
        result = EnrichmentResult()
        combined = f"{title} {text}".lower()

        # Keyword-to-category mapping
        keyword_map: dict[NoticeCategory, list[str]] = {
            NoticeCategory.JOBS: [
                "recruitment", "vacancy", "appointment", "upsc", "ssc",
                "staff selection", "exam", "selection list", "interview",
            ],
            NoticeCategory.SCHEMES: [
                "scheme", "yojana", "programme", "program", "subsidy",
                "benefit", "welfare", "pm-kisan", "pmay", "pmfby",
            ],
            NoticeCategory.TAX: [
                "tax", "cbdt", "cbic", "customs", "income tax", "gst",
                "excise", "taxation", "tax notification",
            ],
            NoticeCategory.AGRICULTURE: [
                "agriculture", "crop", "farmer", "msp", "irrigation", "fertilizer", "seeds", "mandi",
            ],
            NoticeCategory.EDUCATION: [
                "education", "university", "admission", "examination", "ugc", "nta",
                "scholarship", "school", "college",
            ],
            NoticeCategory.HEALTH: [
                "health", "hospital", "medical", "ayush", "vaccine", "disease",
                "pharmaceutical", "drug",
            ],
            NoticeCategory.LEGAL: [
                "law", "act", "bill", "amendment", "ordinance", "regulation",
                "court", "judicial", "tribunal",
            ],
            NoticeCategory.GAZETTE: [
                "gazette", "extraordinary", "official gazette", "notification no", "s.o.", "g.s.r.",
            ],
            NoticeCategory.FINANCE: [
                "rbi", "reserve bank", "interest rate", "monetary policy", "finance", "sebi", "mutual fund",
            ],
            NoticeCategory.INFRASTRUCTURE: [
                "infrastructure", "bridge", "construction", "smart city", "housing", "road",
                "highway", "railway", "metro",
            ],
            NoticeCategory.DEFENSE: [
                "military", "defense", "defence", "cantonment", "army", "navy", "air force",
            ],
            NoticeCategory.ENVIRONMENT: [
                "environment", "environmental clearance", "pollution", "forest", "wildlife",
                "climate", "green tribunal",
            ],
            NoticeCategory.TECHNOLOGY: [
                "technology", "it policy", "cybersecurity", "digital india", "software",
                "semiconductor", "electronics", "telecom", "5g", "ai",
            ],
            NoticeCategory.WOMEN_CHILD: [
                "women", "child", "maternity", "girl child", "anganwadi", "icds",
                "poshan", "safety of women",
            ],
            NoticeCategory.SOCIAL_WELFARE: [
                "welfare", "pension", "disability", "divyangjan", "tribal", "sc/st",
                "minority", "social justice", "empowerment",
            ],
            NoticeCategory.LOCAL_GOVERNANCE: [
                "municipal", "panchayat", "local body", "urban local", "smart city",
                "cleanliness survey", "swachh bharat",
            ],
        }

        matched_categories = []
        for category, keywords in keyword_map.items():
            if any(kw in combined for kw in keywords):
                matched_categories.append(category)

        if matched_categories:
            result.categories = matched_categories
            result.primary_category = matched_categories[0]
        else:
            result.categories = [NoticeCategory.OTHER]
            result.primary_category = NoticeCategory.OTHER

        return result

    def _extractive_summary(self, text: str) -> str:
        """Simple extractive summary: first 2 sentences."""
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        summary = " ".join(sentences[:2])
        if len(summary) > 200:
            summary = summary[:197] + "..."
        return summary
