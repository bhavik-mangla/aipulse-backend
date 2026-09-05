"""
Text extraction and cleaning from HTML and plain text.

- HTML: trafilatura (Markdown extraction) with BeautifulSoup4 fallback
- Text detection: basic content-type routing

PDF and OCR handling was removed with the government portal sources, which
were the only things that produced PDFs.
"""
from __future__ import annotations

import re

import structlog

logger = structlog.get_logger(__name__)

# Constants for PDF processing optimization
MAX_FRONT_PAGES = 5
MAX_BACK_PAGES = 5
MAX_TOTAL_PAGES = MAX_FRONT_PAGES + MAX_BACK_PAGES


class TextParser:
    """Extract and clean text (Markdown) from various content types."""

    # Static singleton for the PaddleOCR engine to avoid re-initialization
    async def extract(self, content: str, content_type: str) -> str:
        """
        Extract clean text/markdown from raw content based on content type.
        Args:
            content: Raw content (HTML, PDF text, plain text).
            content_type: MIME type (text/html, text/markdown, text/plain).
        Returns:
            Cleaned, normalized Markdown or plain text.
        """
        if "html" in content_type or "xml" in content_type:
            return self._extract_html(content)
        else:
            return self._clean_text(content)

    def _extract_html(self, html: str) -> str:
        """
        Extract article text from HTML as Markdown using trafilatura, fallback to BS4.
        Args:
            html: Raw HTML string.
        Returns:
            Extracted Markdown/plain text.
        """
        if not html or len(html.strip()) < 10:
            return ""

        # Primary: trafilatura - best for article extraction to markdown
        text = self._trafilatura_extract(html)
        if text and len(text) > 50:
            return self._clean_text(text, preserve_markdown=True)

        # Fallback: BeautifulSoup4
        text = self._bs4_extract(html)
        return self._clean_text(text)

    def _trafilatura_extract(self, html: str) -> str:
        """Extract text using trafilatura."""
        try:
            import trafilatura
            result = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
                favor_recall=True,
                output_format="markdown",
            )
            return result or ""
        except Exception as exc:
            logger.debug("trafilatura_extract_failed", error=str(exc))
            return ""

    def _bs4_extract(self, html: str) -> str:
        """Extract text using BeautifulSoup4 (Fallback)."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            # Remove script, style, nav, footer, header elements
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            text = soup.get_text(separator="\n", strip=True)
            return text
        except Exception as exc:
            logger.debug("bs4_extract_failed", error=str(exc))
            return ""

    def _clean_text(self, text: str, preserve_markdown: bool = False) -> str:
        """
        Clean and normalize extracted text.
        Args:
            text: Raw extracted text.
            preserve_markdown: If True, avoid collapsing whitespace that breaks Markdown.
        Returns:
            Normalized text string.
        """
        if not text:
            return ""

        # Remove control characters except newlines and tabs
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        
        # Normalize various unicode spaces to regular space
        text = re.sub(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000]", " ", text)
        
        if not preserve_markdown:
            # Collapse multiple blank lines to double newline
            text = re.sub(r"\n{3,}", "\n\n", text)
            # Collapse multiple spaces (but not newlines) to single space
            text = re.sub(r"[^\S\n]+", " ", text)
        else:
            # For Markdown, we only collapse very excessive newlines
            text = re.sub(r"\n{5,}", "\n\n\n", text)
        
        # Strip leading/trailing whitespace per line
        lines = [line.strip() for line in text.split("\n")]
        text = "\n".join(lines)
        
        return text.strip()

    def detect_language(self, text: str) -> str:
        """
        Detect the language of a body of text as an ISO 639-1 code.

        Every source we carry publishes in English, so this almost always
        returns "en". It stays because the field is stored per document and a
        contributor adding a non-English outlet should not have to touch the
        pipeline to get it labelled correctly.
        """
        if not text or len(text) < 20:
            return "en"
        try:
            from lingua import Language, LanguageDetectorBuilder

            if not hasattr(self, "_lang_detector"):
                # A deliberately small candidate set: loading every language
                # costs seconds of startup per run for a field that is "en"
                # almost every time. Add a language here when adding a source
                # that publishes in it.
                self._lang_detector = (
                    LanguageDetectorBuilder.from_languages(
                        Language.ENGLISH,
                        Language.FRENCH,
                        Language.GERMAN,
                        Language.SPANISH,
                        Language.PORTUGUESE,
                    )
                    .with_low_accuracy_mode()
                    .build()
                )

            detected = self._lang_detector.detect_language_of(text)
            if detected is None:
                return "en"
            return detected.iso_code_639_1.name.lower()
        except Exception:
            # Detection is advisory; never fail ingestion over it.
            return "en"
