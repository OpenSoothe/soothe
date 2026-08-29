"""Extract daemon vision-preflight blocks for execute-step context."""

from __future__ import annotations

import re

from soothe.config.constants import (
    VISION_BRIEF_IMAGE_FACTS_MAX_CHARS,
    VISION_CONTEXT_MAX_CHARS,
)
from soothe.utils.text import truncate_text

# Must match soothe_daemon.services.image_understanding.enrich_user_text_with_vision.
VISION_SUMMARY_HEADER = "--- Vision summary ---"

_VISION_BLOCK_RE = re.compile(
    rf"{re.escape(VISION_SUMMARY_HEADER)}\n(?P<body>.*?)\n---\s*(?:\n|$)",
    re.DOTALL,
)

_VISION_INSTRUCTION_LINES: tuple[str, ...] = (
    "- EXECUTION TASK is authoritative scope; VISION CONTEXT is background only",
    "- Use VISION CONTEXT facts (text, labels, layout) instead of inventing image content",
    "- Do not expand work to cover the entire original user request",
)


def extract_vision_summary(
    text: str,
    *,
    max_chars: int = VISION_CONTEXT_MAX_CHARS,
) -> str | None:
    """Return the vision summary body from enriched goal text, or None.

    Args:
        text: User / goal text that may contain a vision preflight block.
        max_chars: Hard cap on returned body length.

    Returns:
        Stripped summary body, or `None` when the delimiter is absent / empty.
    """
    match = _VISION_BLOCK_RE.search(text or "")
    if match is None:
        return None
    body = truncate_text(match.group("body"), limit=max_chars)
    return body or None


def merge_vision_instructions(instructions: str | None) -> str:
    """Append vision scope-guard lines to an existing INSTRUCTIONS body."""
    base = (instructions or "").strip()
    extra = "\n".join(_VISION_INSTRUCTION_LINES)
    if not base:
        return extra
    return f"{base}\n{extra}"


def format_image_facts_for_brief(
    vision_summary: str,
    *,
    max_chars: int = VISION_BRIEF_IMAGE_FACTS_MAX_CHARS,
) -> str:
    """Compact `Image facts: …` suffix for synthesized step `full_description`."""
    body = truncate_text(vision_summary, limit=max_chars)
    if not body:
        return ""
    return f"Image facts: {body}"


__all__ = [
    "VISION_BRIEF_IMAGE_FACTS_MAX_CHARS",
    "VISION_CONTEXT_MAX_CHARS",
    "VISION_SUMMARY_HEADER",
    "extract_vision_summary",
    "format_image_facts_for_brief",
    "merge_vision_instructions",
]
