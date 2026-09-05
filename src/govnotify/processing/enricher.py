"""
Article enrichment - summarization and topic classification.
Uses an LLM for the structured summary, with rule-based keyword classification
as a baseline and as the fallback when the LLM is unavailable.
"""
from __future__ import annotations

import json
import re

import structlog

from govnotify.config import get_settings
from govnotify.constants import IMPACT_TIERS, NewsCategory

logger = structlog.get_logger(__name__)

# List of valid categories for the LLM
CATEGORIES_LIST = ", ".join([c.value for c in NewsCategory])

# List of valid impact tiers
IMPACT_TIERS_LIST = ", ".join(IMPACT_TIERS)

# How much article text to send to the LLM.
#
# This was 50,000 characters, roughly 12,500 tokens per article, which
# dominated inference cost and latency. News articles put their substance in
# the opening paragraphs, so 8,000 characters covers the full body of all but
# the longest features while cutting the per-article token bill by about 84%.
MAX_LLM_INPUT_CHARS = 8000

# Attempts to coax valid JSON out of the model. The router underneath applies
# its own retries and fallback chain, so keeping this low avoids multiplying
# one failure into a long series of calls.
MAX_SUMMARY_ATTEMPTS = 2

SUMMARY_PROMPT = """
You are a news editor writing the summary card a reader sees before deciding
whether to open the full story.

Valid Categories: {categories}
Valid Impact Tiers: {impact_tiers}

Guidelines:
- Quick take: 1-2 sentences that carry the actual news, not a teaser. A reader
  who reads only this should already know what happened.
- Key details: 2-4 short bullets adding specifics the quick take left out -
  numbers, names, dates, what changes and for whom. Do not repeat the quick
  take.
- Lead with what happened, not with who reported it.
- Impact Tier: how significant this story is to a general reader.
  Critical = major breaking news of wide consequence.
  High = important national or international development.
  Medium = ordinary newsworthy story.
  Low = routine, niche or soft news.
- Primary Category: the single best fit from the Valid Categories list.
- Image Search Query: 1-3 words naming a concrete entity in the story - a
  person, company, place or organisation. Prefer something with recognisable
  news imagery. Avoid abstract concepts, which return generic stock photos.
- STRICTLY FACTUAL: only what is explicitly in the text. Never infer or invent
  figures, quotes or outcomes.
- No editorialising and no opinion of your own.
- Use only values from the provided lists for Category and Impact Tier.

Input text:
{text}

Respond with ONLY valid JSON:
{{
  "quick_take": "A 1-2 sentence summary of what happened.",
  "key_details": [
    "Specific fact or figure the quick take did not cover"
  ],
  "impact_tier": "Critical/High/Medium/Low",
  "primary_category": "category_name",
  "image_search_query": "concrete entity from the story"
}}
"""


def build_prompt(text: str) -> str:
    """Render the summary prompt for an article."""
    return SUMMARY_PROMPT.format(
        categories=CATEGORIES_LIST,
        impact_tiers=IMPACT_TIERS_LIST,
        text=text,
    )


class EnrichmentResult:
    """Result of document enrichment."""

    def __init__(self) -> None:
        self.categories: list[NewsCategory] = []
        self.primary_category: NewsCategory = NewsCategory.OTHER
        self.notification_number: str | None = None
        self.department: str = ""
        self.regions: list[str] = []
        self.entities: dict[str, list[str]] = {
            "persons": [],
            "organizations": [],
            "dates": [],
            "amounts": [],
            "schemes": [],
        }
        self.summary: str = ""  # JSON string holding the structured summary
        self.image_search_query: str = ""
        self.impact_tier: str = "Medium"
        self.confidence_score: float = 0.0


class Enricher:
    """Enrich documents with classification, entities, and summaries."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def enrich(self, clean_text: str, title: str = "") -> EnrichmentResult:
        """
        Summarize and classify an article.

        Args:
            clean_text: Cleaned article text.
            title: Headline, for additional context.
        Returns:
            EnrichmentResult with the summary and metadata.
        """
        combined_text = f"{title}\n\n{clean_text}" if title else clean_text
        truncated = combined_text[:MAX_LLM_INPUT_CHARS]

        # Use rule-based classification as a baseline
        result = self._rule_based_classify(clean_text, title)
        result.confidence_score = 0.5

        # Generate Summary if enabled
        if self._settings.enable_llm:
            summary_data = await self._llm_summarize(truncated)
            if summary_data:
                # Store the structured summary as JSON, and lift the fields
                # the feed and image resolver read directly.
                result.summary = json.dumps(summary_data)
                result.image_search_query = summary_data.get("image_search_query", "")

                impact = summary_data.get("impact_tier", "Medium")
                result.impact_tier = impact if impact in IMPACT_TIERS else "Medium"

                # Override rule-based primary category if LLM provided a valid one
                llm_cat = str(summary_data.get("primary_category", "")).lower()
                try:
                    if llm_cat:
                        result.primary_category = NewsCategory(llm_cat)
                        if result.primary_category not in result.categories:
                            result.categories.append(result.primary_category)
                except ValueError:
                    logger.warning("invalid_llm_category", category=llm_cat)
        
        if not result.summary:
            # Fallback: extractive summary as JSON
            fallback_take = self._extractive_summary(clean_text)
            result.summary = json.dumps({
                "quick_take": fallback_take,
                "key_details": [],
                "impact_tier": "Medium",
                "primary_category": result.primary_category.value,
            })

        return result

    async def _llm_summarize(self, text: str) -> dict | None:
        """
        Generate a structured summary using the LLM.

        Args:
            text: Truncated article text.
        Returns:
            Dictionary of summary data, or None if the LLM was unavailable.
        """
        from govnotify.processing.llm_router import get_completion

        prompt = build_prompt(text)

        # Retry loop for robust extraction
        for attempt in range(MAX_SUMMARY_ATTEMPTS):
            try:
                content = await get_completion(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2 if attempt == 0 else 0.3,
                    max_tokens=1500 + (attempt * 500),  # Increase tokens on retry
                    json_mode=True,
                )
                
                if not content:
                    logger.warning("llm_summarize_empty_response", attempt=attempt+1)
                    continue
                
                json_str = self._extract_json(content)
                if not json_str:
                    logger.warning("llm_json_extraction_failed", attempt=attempt+1, content_preview=content[:100])
                    continue

                # Validate JSON
                data = json.loads(json_str)
                if "quick_take" in data and "key_details" in data:
                    if attempt > 0:
                        logger.info("llm_summarize_success_after_retry", attempt=attempt+1)
                    return data
                
                logger.warning("llm_response_missing_keys", keys=list(data.keys()), attempt=attempt+1)
            except Exception as exc:
                logger.warning("llm_summarize_attempt_failed", attempt=attempt+1, error=str(exc))
                if attempt == MAX_SUMMARY_ATTEMPTS - 1:
                    break
        
        return None

    def _extract_json(self, content: str) -> str | None:
        """
        Extract the first balanced JSON object from a string.
        Industry standard approach: handles markdown blocks and nested structures.
        """
        # 1. Try markdown block first (most common LLM format)
        markdown_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if markdown_match:
            return markdown_match.group(1).strip()

        # 2. Brace counting for robustness
        content = content.strip()
        start_idx = content.find("{")
        if start_idx == -1:
            return None

        brace_count = 0
        in_string = False
        escape = False

        for i in range(start_idx, len(content)):
            char = content[i]

            if escape:
                escape = False
                continue

            if char == "\\":
                escape = True
                continue

            if char == '"':
                in_string = not in_string
                continue

            if not in_string:
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        return content[start_idx : i + 1]

        return None

    def classify(self, text: str, title: str = "") -> EnrichmentResult:
        """Rule-based classification, used as a baseline and as the LLM-off path."""
        return self._rule_based_classify(text, title)

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

        # Keyword-to-category mapping.
        #
        # This replaces a map built entirely from Indian government vocabulary
        # (yojana, UPSC, CBDT, gazette numbering) that classified almost
        # nothing correctly once the feed became general world news. Keywords
        # are deliberately international; the LLM does the real work and this
        # is the baseline and the LLM-off fallback.
        keyword_map: dict[NewsCategory, list[str]] = {
            NewsCategory.WORLD: [
                "united nations", "diplomatic", "foreign ministry", "border",
                "treaty", "refugee", "ceasefire", "war", "invasion", "embassy",
                "sanctions", "summit", "nato",
            ],
            NewsCategory.BUSINESS: [
                "earnings", "revenue", "profit", "quarterly", "shares", "stock",
                "market", "economy", "inflation", "trade", "investment",
                "merger", "acquisition", "startup", "ipo", "central bank",
                "interest rate", "tariff", "layoffs",
            ],
            NewsCategory.POLITICS: [
                "election", "parliament", "congress", "senate", "minister",
                "president", "prime minister", "vote", "campaign", "policy",
                "legislation", "bill", "court", "ruling", "supreme court",
                "governor", "referendum",
            ],
            NewsCategory.TECHNOLOGY: [
                "artificial intelligence", " ai ", "software", "chip",
                "semiconductor", "smartphone", "cybersecurity", "data breach",
                "app", "platform", "algorithm", "cloud", "robotics", "quantum",
            ],
            NewsCategory.SCIENCE: [
                "researchers", "study found", "scientists", "nasa", "space",
                "telescope", "satellite", "physics", "genome", "discovery",
                "experiment", "spacecraft",
            ],
            NewsCategory.HEALTH: [
                "health", "hospital", "disease", "vaccine", "virus", "patients",
                "medical", "outbreak", "drug", "clinical trial", "cancer",
                "mental health", "who",
            ],
            NewsCategory.SPORTS: [
                "match", "tournament", "championship", "league", "cup", "olympic",
                "cricket", "football", "soccer", "tennis", "basketball",
                "medal", "coach", "striker", "innings",
            ],
            NewsCategory.ENTERTAINMENT: [
                "film", "movie", "album", "actor", "actress", "box office",
                "series", "streaming", "concert", "festival", "celebrity",
                "director", "netflix",
            ],
            NewsCategory.ENVIRONMENT: [
                "climate", "emissions", "wildfire", "flood", "drought",
                "pollution", "renewable", "biodiversity", "conservation",
                "earthquake", "hurricane", "cyclone", "wildlife",
            ],
            NewsCategory.EDUCATION: [
                "school", "university", "student", "exam", "curriculum",
                "teacher", "tuition", "scholarship", "campus", "admission",
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
            result.categories = [NewsCategory.OTHER]
            result.primary_category = NewsCategory.OTHER

        return result

    def _extractive_summary(self, text: str) -> str:
        """Simple extractive summary: first 2 sentences."""
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        summary = " ".join(sentences[:2])
        if len(summary) > 200:
            summary = summary[:197] + "..."
        return summary
