"""
Digest formatting templates for different delivery channels.
Three output formats:
1. Email HTML - full styled template with sections per category
2. Telegram Markdown - compact format with source links
3. Plain text - simple text for SMS / fallback

All templates include the required disclaimer:
"AI-generated summary - verify with official gazette."
"""
from __future__ import annotations

import re
from datetime import datetime
from html import escape
from typing import Optional, Any

from govnotify.models.notification import (
    CategoryDigest,
    NotificationItem,
    UserDigest,
    SourceDigest,
)
from govnotify.constants import (
    NoticeCategory,
    I18N,
    CATEGORY_NAMES_HI,
    CATEGORY_EMOJIS,
)

# Disclaimer (required by §19)
DISCLAIMER_EN = "AI-generated summary - verify with official gazette."
DISCLAIMER_HI = "AI-जनरेटेड सारांश - आधिकारिक राजपत्र के साथ सत्यापित करें।"


# --- Subject ---

def render_subject(
    date_str: str,
    language: str = "en"
) -> str:
    """Render a localized subject line."""
    t = I18N.get(language, I18N["en"])
    date_display = _format_date(date_str, language=language)
    return f"{t['digest_title']} - {date_display}"


# --- Plain Text ---

def render_plain_text(
    digest: UserDigest,
    language: str = "en"
) -> str:
    """Render a UserDigest as plain text."""
    lines: list[str] = []
    date_display = _format_date(digest.date, language=language)
    t = I18N.get(language, I18N["en"])
    
    lines.append(f"{t['digest_title']} - {date_display}")
    lines.append("=" * 30)
    lines.append("")
    
    # Render Source Sections (Primary)
    if digest.source_sections:
        for section in digest.source_sections:
            lines.append(_render_source_plain(section, language=language))
            lines.append("")

    # Render Category Sections (Fallback)
    if not digest.source_sections and digest.category_sections:
        for section in digest.category_sections:
            lines.append(_render_category_plain(section, language=language))
            lines.append("")
        
    if digest.total_items == 0:
        lines.append(t['no_updates'])
        lines.append("")
        
    lines.append("-" * 30)
    disclaimer = DISCLAIMER_HI if language == "hi" else DISCLAIMER_EN
    lines.append(disclaimer)
    lines.append(f"{t['unsubscribe']}: https://govnotify.in/settings")
    
    return "\n".join(lines)


def _render_source_plain(
    section: SourceDigest,
    language: str = "en",
) -> str:
    """Render a SourceDigest section as plain text."""
    lines: list[str] = []
    lines.append(f"[{section.source_name.upper()}]")
    lines.append("-" * 15)
    
    if not section.has_updates:
        t = I18N.get(language, I18N["en"])
        lines.append(t['no_updates_portal'])
        return "\n".join(lines)
        
    summary = (
        section.summary_hindi
        if language == "hi" and getattr(section, "summary_hindi", None)
        else section.summary_text
    )
    
    if summary:
        lines.append(summary)
        
    return "\n".join(lines)


def _render_category_plain(
    section: CategoryDigest,
    language: str = "en",
) -> str:
    """Render a single category section as plain text."""
    cat_name = _category_display_name(section.category.value, language=language)
    lines: list[str] = []
    lines.append(f"[{cat_name.upper()}]")
    lines.append("-" * 15)
    
    if not section.has_updates:
        lines.append(section.no_update_message)
        return "\n".join(lines)
        
    # Use LLM summary if available
    summary = (
        section.summary_hindi
        if language == "hi" and section.summary_hindi
        else section.summary_text
    )
    
    if summary:
        lines.append(summary)
    else:
        # Fallback: list items
        for item in section.items:
            regions = f" [{', '.join(item.regions)}]" if item.regions else ""
            lines.append(f"• {item.title}{regions}")
            if item.summary:
                lines.append(f"  {item.summary[:200]}...")
            lines.append(f"  {I18N.get(language, I18N['en'])['source']}: {item.source_name} | {item.source_url}")
            
    return "\n".join(lines)


# --- Telegram Markdown ---

def render_telegram(
    digest: UserDigest,
    language: str = "en",
) -> str:
    """
    Render a UserDigest as Telegram MarkdownV2-compatible text.
    """
    lines: list[str] = []
    date_display = _format_date(digest.date, language=language)
    t = I18N.get(language, I18N["en"])
    
    lines.append(f"📢 *{t['digest_title']}*")
    lines.append(f"📅 {date_display}")
    lines.append("")
    
    # Render Source Sections (Primary)
    if digest.source_sections:
        for section in digest.source_sections:
            lines.append(_render_source_telegram(section, language=language))
            lines.append("")

    # Render Category Sections (Fallback)
    if not digest.source_sections and digest.category_sections:
        for section in digest.category_sections:
            lines.append(_render_category_telegram(section, language=language))
            lines.append("")
        
    if digest.total_items == 0:
        lines.append(f"_{t['no_updates']}_")
        lines.append("")
        
    disclaimer = DISCLAIMER_HI if language == "hi" else DISCLAIMER_EN
    lines.append(f"_{disclaimer}_")
    
    return "\n".join(lines)


def _render_source_telegram(
    section: SourceDigest,
    language: str = "en",
) -> str:
    """Render a SourceDigest section for Telegram."""
    lines: list[str] = []
    lines.append(f"📍 *{section.source_name}*")
    
    if not section.has_updates:
        t = I18N.get(language, I18N["en"])
        lines.append(f"_{t['no_updates_portal']}_")
        return "\n".join(lines)
        
    summary = (
        section.summary_hindi
        if language == "hi" and getattr(section, "summary_hindi", None)
        else section.summary_text
    )
    
    if summary:
        # Truncate for Telegram message limits (4096 chars per message)
        truncated = summary[:1500]
        if len(summary) > 1500:
            truncated += "..."
        lines.append(truncated)
            
    return "\n".join(lines)


def _render_category_telegram(
    section: CategoryDigest,
    language: str = "en",
) -> str:
    """Render a single category section for Telegram."""
    lines: list[str] = []
    cat_name = _category_display_name(section.category.value, language=language)
    emoji = _category_emoji(section.category.value)
    
    lines.append(f"{emoji} *{cat_name}*")
    
    if not section.has_updates:
        lines.append(f"_{section.no_update_message}_")
        return "\n".join(lines)
        
    # Use summary if available
    summary = (
        section.summary_hindi
        if language == "hi" and section.summary_hindi
        else section.summary_text
    )
    
    if summary:
        # Truncate for Telegram message limits (4096 chars per message)
        truncated = summary[:1500]
        if len(summary) > 1500:
            truncated += "..."
        lines.append(truncated)
    else:
        # Limit items for Telegram
        for item in section.items[:5]:
            lines.append(f"• *{item.title}*")
            source_link = f"[{item.source_name}]({item.source_url})"
            lines.append(f"  {item.summary[:150] if item.summary else '?'} ({source_link})")
            
    return "\n".join(lines)


# --- Email HTML ---

EMAIL_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 680px; margin: 0 auto; padding: 20px; }
.header { background: linear-gradient(135deg, #1a365d, #2d5aae); color: white; padding: 24px; border-radius: 8px 8px 0 0; }
.header h1 { margin: 0; font-size: 22px; }
.header .date { color: #c3dafe; font-size: 14px; margin-top: 4px; }
.section { border: 1px solid #e2e8f0; border-top: none; margin: 0; padding: 20px; background: #fff; }
.section:last-of-type { border-radius: 0 0 8px 8px; }
.section-header { font-size: 18px; font-weight: 600; color: #1a365d; margin: 0 0 12px 0; padding-bottom: 8px; border-bottom: 2px solid #e2e8f0; }
.category-section { border: 1px solid #e2e8f0; border-top: none; margin: 0; padding: 20px; background: #fff; }
.category-header { font-size: 18px; font-weight: 600; color: #1a365d; margin: 0 0 12px 0; padding-bottom: 8px; border-bottom: 2px solid #e2e8f0; }
.category-emoji { margin-right: 8px; }
.summary-block { background: #ffffff; padding: 0; margin-bottom: 16px; font-size: 15px; color: #334155; }
.item-link-box { margin-top: 4px; font-size: 11px; }
.item-link { color: #94a3b8; text-decoration: none; }
.disclaimer { font-size: 11px; color: #94a3b8; margin-top: 24px; text-align: center; }
.footer { font-size: 11px; color: #94a3b8; margin-top: 24px; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 20px; }
.footer p { margin: 4px 0; }
"""

def render_email_html(
    digest: UserDigest,
    language: str = "en"
) -> str:
    """Render a UserDigest as a styled HTML email."""
    date_display = _format_date(digest.date, language=language)
    t = I18N.get(language, I18N["en"])
    sections_html = ""
    
    # Render Source Sections (Primary)
    if digest.source_sections:
        for section in digest.source_sections:
            sections_html += _render_source_html(section, language=language)
            
    # Render Category Sections (Fallback)
    if not sections_html and digest.category_sections:
        for section in digest.category_sections:
            sections_html += _render_category_html(section, language=language)
        
    if not sections_html:
        sections_html = (
            f'<div class="section">'
            f'<p class="no-updates">{escape(t["no_updates"])}</p>'
            f'</div>'
        )
        
    disclaimer = DISCLAIMER_HI if language == "hi" else DISCLAIMER_EN
    update_word = t["updates"] if digest.total_items != 1 else t["update"]
    
    return f"""<!DOCTYPE html>
<html lang="{language}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape(t['digest_title'])} - {escape(date_display)}</title>
    <style>{EMAIL_CSS}</style>
</head>
<body>
    <div class="header">
        <a href="https://govnotify.vercel.app" style="color: white; text-decoration: none;">
            <h1 style="margin:0;">{escape(t['digest_header'])}</h1>
        </a>
        <div class="date">{escape(date_display)} &bull; {digest.total_items} {update_word}</div>
    </div>
    <div style="padding: 0 10px;">
        {sections_html}
    </div>
    <div class="disclaimer">{escape(disclaimer)}</div>
    <div class="footer">
        <p>{escape(t['unsubscribe_msg'])}</p>
        <p><strong>GovNotify HQ</strong><br>{escape(t['hq_address'])}</p>
        <p>
            <a href="https://govnotify.vercel.app" style="color:#2d5aae; font-weight: bold; text-decoration: none;">Visit GovNotify</a> &bull;
            <a href="https://govnotify.vercel.app/settings" style="color:#2d5aae; text-decoration: none;">{escape(t['manage_prefs'])}</a> &bull; 
            <a href="https://govnotify.vercel.app/unsubscribe" style="color:#2d5aae; text-decoration: none;">{escape(t['unsubscribe'])}</a>
        </p>
    </div>
</body>
</html>"""


def _render_source_html(
    section: SourceDigest, 
    language: str = "en"
) -> str:
    """Render a SourceDigest section."""
    if not section.has_updates:
        return ""

    summary = (
        section.summary_hindi
        if language == "hi" and getattr(section, "summary_hindi", None)
        else section.summary_text
    )

    summary_html = ""
    if summary:
        summary_html = f'<div class="summary-block">{_text_to_html(summary)}</div>'

    return (
        f'<div class="section">'
        f'<h2 class="section-header">{escape(section.source_name)}</h2>'
        f'{summary_html}'
        f'</div>'
    )


def _render_category_html(
    section: CategoryDigest,
    language: str = "en",
) -> str:
    """Render a single category section as HTML."""
    cat_name = _category_display_name(section.category.value, language=language)
    emoji = _category_emoji(section.category.value)
    
    if not section.has_updates:
        return (
            f'<div class="category-section">'
            f'<h2 class="category-header"><span class="category-emoji">{emoji}</span>{escape(cat_name)}</h2>'
            f'<p class="no-updates">{escape(section.no_update_message)}</p>'
            f'</div>'
        )

    summary = (
        section.summary_hindi
        if language == "hi" and section.summary_hindi
        else section.summary_text
    )
    
    summary_html = ""
    if summary:
        summary_html = f'<div class="summary-block" style="margin-bottom:0;">{_text_to_html(summary)}</div>'

    return (
        f'<div class="category-section">'
        f'<h2 class="category-header">'
        f'<span class="category-emoji">{emoji}</span>{escape(cat_name)}</h2>'
        f'{summary_html}'
        f'</div>'
    )


# --- Helpers ---

def _category_emoji(category_value: str) -> str:
    return CATEGORY_EMOJIS.get(category_value, "•")


def _category_display_name(category_value: str, language: str = "en") -> str:
    """Convert enum value to display name, with Hindi translation if requested."""
    if language == "hi":
        return CATEGORY_NAMES_HI.get(category_value, category_value.replace("_", " ").title())
    return category_value.replace("_", " ").title()


def _format_date(date_str: str, language: str = "en") -> str:
    """Format "YYYY-MM-DD" into "April 6, 2026" or Hindi format."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if language == "hi":
            # Simplified Hindi date format
            months_hi = ["जनवरी", "फरवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
            return f"{dt.day} {months_hi[dt.month-1]}, {dt.year}"
        return dt.strftime("%B %d, %Y").replace(" 0", " ")
    except ValueError:
        return date_str


def _text_to_html(text: str) -> str:
    """Convert plain text with markdown-like formatting to clean HTML."""
    html = escape(text)
    
    # Headers: ### Title
    html = re.sub(
        r"^###\s*(.+?)$", 
        r'<h3 style="margin: 16px 0 8px 0; color: #1a365d; font-size: 16px;">\1</h3>', 
        html, 
        flags=re.MULTILINE
    )
    
    # Bold: **text**
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    
    # Convert bullet points into a clean <ul> list
    # 1. Identify blocks of bullet points
    lines = html.splitlines()
    in_list = False
    new_lines = []
    
    for line in lines:
        line = line.strip()
        if line.startswith('•') or line.startswith('-'):
            if not in_list:
                new_lines.append('<ul style="margin: 8px 0; padding-left: 20px; color: #334155;">')
                in_list = True
            content = line[1:].strip()
            new_lines.append(f'<li style="margin-bottom: 6px;">{content}</li>')
        else:
            if in_list:
                new_lines.append('</ul>')
                in_list = False
            if line:
                new_lines.append(f'<p style="margin: 8px 0;">{line}</p>')
                
    if in_list:
        new_lines.append('</ul>')
        
    return "\n".join(new_lines)
