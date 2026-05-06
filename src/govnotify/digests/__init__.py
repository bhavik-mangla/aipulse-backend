"""
GovNotify digest generation and delivery formatting.
Exports:
- CategoryDigestGenerator: generates one CategoryDigest per category/day
- UserDigestAssembler: combines CategoryDigests into per-user UserDigests
- render_plain_text, render_telegram, render_email_html: template renderers
"""
from govnotify.digests.assembler import UserDigestAssembler
from govnotify.digests.category_digest import CategoryDigestGenerator
from govnotify.digests.templates import (
    render_email_html,
    render_plain_text,
    render_telegram,
)

__all__ = [
    "CategoryDigestGenerator",
    "UserDigestAssembler",
    "render_email_html",
    "render_plain_text",
    "render_telegram",
]
