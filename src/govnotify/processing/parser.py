"""
Text extraction and cleaning from HTML, PDF, and plain text.
Primary libraries:
- HTML: trafilatura (Markdown extraction) with BeautifulSoup4 fallback
- PDF: PaddleOCR (High-accuracy OCR) with PyMuPDF and pdfplumber fallback
- Text detection: basic content-type routing
"""
from __future__ import annotations

import io
import os
import re
import tempfile
import threading
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# Constants for PDF processing optimization
MAX_FRONT_PAGES = 5
MAX_BACK_PAGES = 5
MAX_TOTAL_PAGES = MAX_FRONT_PAGES + MAX_BACK_PAGES


class TextParser:
    """Extract and clean text (Markdown) from various content types."""

    # Static singleton for the PaddleOCR engine to avoid re-initialization
    _paddle_ocr = None
    _paddle_ocr_pid = None
    _paddle_lock = threading.Lock()

    @classmethod
    def _get_paddle_ocr(cls):
        """
        Get or initialize the PaddleOCR engine.
        Ensures initialization happens only in the current process after fork.
        """
        # Global kill switch
        if os.environ.get("DISABLE_PADDLEOCR", "False").lower() == "true":
            return None

        # Safety check: if we previously failed or segfaulted in this process, don't try again
        if hasattr(cls, "_paddle_failed_pid") and cls._paddle_failed_pid == os.getpid():
            return None

        current_pid = os.getpid()
        if cls._paddle_ocr is None or cls._paddle_ocr_pid != current_pid:
            with cls._paddle_lock:
                # Double check inside lock
                if cls._paddle_ocr is None or cls._paddle_ocr_pid != current_pid:
                    try:
                        # Force stability flags before import/init
                        os.environ["FLAGS_enable_pir_api"] = "0"
                        os.environ["FLAGS_use_mkldnn"] = "0"
                        os.environ["OMP_NUM_THREADS"] = "1"
                        
                        from paddleocr import PaddleOCR
                        # Configuration matching the working CLI and verified stable in direct tests
                        use_mkldnn = os.environ.get("PADDLE_USE_MKLDNN", "False").lower() == "true"
                        
                        logger.info("initializing_paddleocr_engine", pid=current_pid, mkldnn=use_mkldnn)
                        cls._paddle_ocr = PaddleOCR(
                            ocr_version='PP-OCRv4',
                            use_doc_orientation_classify=False,
                            use_doc_unwarping=False,
                            use_textline_orientation=False,
                            lang='en',  # Reverted to English
                            enable_mkldnn=use_mkldnn,
                            # --- Accuracy Optimizations for Complex Docs ---
                            det_limit_side_len=1056,     # Increased for better accuracy on dense/complex docs
                            det_db_thresh=0.3,
                            det_db_box_thresh=0.6,       # Slightly higher to reduce noise in complex layouts
                            rec_batch_num=6,
                            use_angle_cls=True,          # Essential for scanned docs that might be tilted
                            show_log=False
                        )
                        cls._paddle_ocr_pid = current_pid
                        logger.info("paddleocr_engine_initialized", pid=current_pid)
                    except (Exception, ImportError) as exc:
                        logger.error("paddleocr_initialization_failed", error=str(exc))
                        cls._paddle_failed_pid = current_pid
                        return None
        return cls._paddle_ocr

    def is_complex_pdf(self, pdf_bytes: bytes) -> bool:
        """
        Identify if a PDF is 'complex' (scanned, stamped, or heavily layouted).
        A PDF is complex if:
        1. It's scanned (little to no extractable text).
        2. It contains many images relative to its page count (likely stamps/charts).
        3. Simple text extraction yields messy results (low density).
        """
        try:
            import fitz
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            total_pages = len(doc)
            if total_pages == 0:
                return False

            scanned_pages = 0
            # Check up to 10 pages for better robustness against mixed-type documents
            check_pages = min(total_pages, 10)
            
            for i in range(check_pages):
                page = doc[i]
                text = page.get_text().strip()
                images = page.get_images()
                
                # If a page has very little text but has images, it's likely scanned or stamped
                if len(text) < 100 and images:
                    scanned_pages += 1
                # If page has absolutely no text, it's definitely scanned
                elif not text:
                    scanned_pages += 1
                # If page has many images (> 5), it's probably complex
                elif len(images) > 5:
                    scanned_pages += 1

            doc.close()
            # If more than 50% of checked pages look complex, mark whole PDF as complex
            return (scanned_pages / check_pages) >= 0.5
        except Exception as exc:
            logger.debug("pdf_complexity_check_failed", error=str(exc))
            # Fallback to complex to be safe if it's a valid PDF but analysis failed
            return True

    async def extract(self, content: str, content_type: str) -> str:
        """
        Extract clean text/markdown from raw content based on content type.
        Args:
            content: Raw content (HTML, PDF text, plain text).
            content_type: MIME type (text/html, application/pdf, text/plain).
        Returns:
            Cleaned, normalized Markdown or plain text.
        """
        if "html" in content_type or "xml" in content_type:
            return self._extract_html(content)
        elif "pdf" in content_type:
            return self._extract_pdf_text(content)
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

    def _extract_pdf_text(self, content: str) -> str:
        """
        Extract text from PDF content string.
        Note: For actual PDF bytes, use extract_pdf_from_bytes().
        """
        return self._clean_text(content)

    async def extract_pdf_from_bytes(self, pdf_bytes: bytes) -> str:
        """
        Extract high-fidelity text from PDF bytes.
        Identifies complex docs and uses PaddleOCR for them.
        For simple digital docs, uses PyMuPDF for speed.
        Args:
            pdf_bytes: Raw PDF file bytes.
        Returns:
            Extracted text.
        """
        is_complex = self.is_complex_pdf(pdf_bytes)
        
        # 1. Primary for complex: PaddleOCR
        if is_complex:
            if os.environ.get("DISABLE_PADDLEOCR", "False").lower() == "true":
                logger.info("paddleocr_disabled_by_env_skipping_ocr")
            else:
                logger.info("complex_pdf_detected_using_ocr")
                text = await self._paddleocr_extract(pdf_bytes)
                if text and len(text) > 100:
                    return self._clean_text(text)

        # 2. Fallback or primary for simple: PyMuPDF (Fast native text)
        text = self._pymupdf_extract(pdf_bytes)
        if text and len(text) > 50:
            return self._clean_text(text)
            
        # 3. Final Fallback: pdfplumber
        text = self._pdfplumber_extract(pdf_bytes)
        return self._clean_text(text)

    def _get_pages_to_extract(self, total_pages: int) -> list[int]:
        """
        Get indices of pages to extract (first N and last M).
        Args:
            total_pages: Total number of pages in PDF.
        Returns:
            List of 0-based page indices.
        """
        if total_pages <= MAX_TOTAL_PAGES:
            return list(range(total_pages))
        
        # Take first 5
        front = list(range(MAX_FRONT_PAGES))
        # Take last 5
        back = list(range(total_pages - MAX_BACK_PAGES, total_pages))
        
        # Return unique sorted indices just in case of overlap
        return sorted(list(set(front + back)))

    async def _paddleocr_extract(self, pdf_bytes: bytes) -> str:
        """
        Extract text from PDF bytes using PaddleOCR.
        Uses the classic ocr() method with stable configuration.
        """
        import asyncio
        import fitz
        
        # Check if PaddleOCR is explicitly disabled or known to be unstable in this env
        if os.environ.get("DISABLE_PADDLEOCR", "False").lower() == "true":
            logger.info("paddleocr_disabled_by_env_using_fallback")
            return ""

        ocr = self._get_paddle_ocr()
        if not ocr:
            return ""

        tmp_path = None
        try:
            # Check page count and subset if necessary
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            total_pages = len(doc)
            
            if total_pages > MAX_TOTAL_PAGES:
                logger.info("pdf_too_large_subsetting_for_ocr", total_pages=total_pages, target_pages=MAX_TOTAL_PAGES)
                pages_to_keep = self._get_pages_to_extract(total_pages)
                
                new_doc = fitz.open()
                for p in pages_to_keep:
                    new_doc.insert_pdf(doc, from_page=p, to_page=p)
                
                subset_bytes = new_doc.write()
                new_doc.close()
                doc.close()
                
                # Write subset to temp file
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(subset_bytes)
                    tmp_path = tmp.name
            else:
                doc.close()
                # Use original bytes
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(pdf_bytes)
                    tmp_path = tmp.name

            try:
                # The ocr() method handles PDF page iteration internally
                # Wrap in thread to avoid blocking event loop
                result = await asyncio.to_thread(ocr.ocr, tmp_path)
                
                if not result:
                    return ""
                
                full_text = []
                for item in result:
                    # Handle paddlex OCRResult objects
                    if hasattr(item, "get") and "rec_texts" in item:
                        texts = item.get("rec_texts", [])
                        if texts:
                            full_text.append("\n".join(texts))
                    # Handle traditional paddleocr list format: [[box, [text, score]], ...]
                    elif isinstance(item, list):
                        page_text = "\n".join([line[1][0] for line in item if isinstance(line, list) and len(line) > 1])
                        if page_text:
                            full_text.append(page_text)
                
                return "\n\n".join(full_text)
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
        except Exception as exc:
            logger.debug("paddleocr_extract_failed", error=str(exc))
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
            return ""

    def _pdfplumber_extract(self, pdf_bytes: bytes) -> str:
        """Extract text using pdfplumber."""
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                total_pages = len(pdf.pages)
                pages_to_extract = self._get_pages_to_extract(total_pages)
                
                if total_pages > MAX_TOTAL_PAGES:
                    logger.debug("pdfplumber_subsetting", total=total_pages, count=len(pages_to_extract))

                text_pages = []
                for idx in pages_to_extract:
                    page = pdf.pages[idx]
                    page_text = page.extract_text()
                    if page_text:
                        text_pages.append(page_text)
                return "\n\n".join(text_pages)
        except Exception as exc:
            logger.debug("pdfplumber_extract_failed", error=str(exc))
            return ""

    def _pymupdf_extract(self, pdf_bytes: bytes) -> str:
        """Extract text using PyMuPDF (Fitz)."""
        try:
            import fitz  # PyMuPDF
            # Set TESSDATA_PREFIX for fitz OCR if not set
            if "TESSDATA_PREFIX" not in os.environ:
                tess_prefix = os.environ.get("TESSDATA_PREFIX_FALLBACK", "/usr/share/tesseract-ocr/5/tessdata")
                os.environ["TESSDATA_PREFIX"] = tess_prefix
                logger.debug("setting_tessdata_prefix_for_fitz", path=tess_prefix)

            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            total_pages = len(doc)
            pages_to_extract = self._get_pages_to_extract(total_pages)
            
            if total_pages > MAX_TOTAL_PAGES:
                logger.debug("pymupdf_subsetting", total=total_pages, count=len(pages_to_extract))

            text_pages = []
            for idx in pages_to_extract:
                page = doc[idx]
                text = page.get_text()
                # Fallback to OCR if page has no text but has images
                if len(text.strip()) < 50 and page.get_images() and hasattr(page, "get_textpage_ocr"):
                    try:
                        # Ensure we try to use OCR
                        tp = page.get_textpage_ocr(full=True)
                        text = tp.extractText()
                    except Exception as ocr_exc:
                        logger.debug("pymupdf_ocr_page_failed", page=page.number, error=str(ocr_exc))

                if text:
                    text_pages.append(text)
            doc.close()
            return "\n\n".join(text_pages)
        except Exception as exc:
            logger.debug("pymupdf_extract_failed", error=str(exc))
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
        Detect the language of the given text using lingua-py.
        Args:
            text: Text to analyze.
        Returns:
            ISO 639-1 language code (e.g. 'en', 'hi').
        """
        if not text or len(text) < 20:
            return "en"
        try:
            from lingua import Language, LanguageDetectorBuilder
            # Lazily initialize detector if not present
            if not hasattr(self, "_lang_detector"):
                self._lang_detector = (
                    LanguageDetectorBuilder.from_languages(Language.ENGLISH, Language.HINDI)
                    .build()
                )
            
            detected = self._lang_detector.detect_language_of(text)
            if detected == Language.HINDI:
                return "hi"
            return "en"
        except Exception:
            return "en"
