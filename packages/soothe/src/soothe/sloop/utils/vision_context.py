"""Extract daemon vision-preflight blocks for execute-step context (IG-674).

Daemon ``enrich_user_text_with_vision`` appends a delimited summary::

    --- Vision summary ---
    ...
    ---

StrangeLoop execute envelopes use that body as subordinate ``VISION CONTEXT``
without re-injecting the full parent GOAL (over-execution risk).
"""

from __future__ import annotations

import re

# Must match soothe_daemon.services.image_understanding.enrich_user_text_with_vision.
VISION_SUMMARY_HEADER = "--- Vision summary ---"
VISION_CONTEXT_MAX_CHARS = 4000
VISION_BRIEF_IMAGE_FACTS_MAX_CHARS = 800

_VISION_BLOCK_RE = re.compile(
    rf"{re.escape(VISION_SUMMARY_HEADER)}\n(?P<body>.*?)\n---\s*(?:\n|$)",
    re.DOTALL,
)

_VISION_INSTRUCTION_LINES: tuple[str, ...] = (
    "- EXECUTION TASK is authoritative scope; VISION CONTEXT is background only",
    "- Use VISION CONTEXT facts (text, labels, layout) instead of inventing image content",
    "- Do not expand work to cover the entire original user request",
)


def _truncate(text: str, *, max_chars: int) -> str:
    cleaned = (text or "").strip()
    if max_chars <= 0 or len(cleaned) <= max_chars:
        return cleaned
    if max_chars <= 1:
        return "…"
    return cleaned[: max_chars - 1].rstrip() + "…"


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
        Stripped summary body, or ``None`` when the delimiter is absent / empty.
    """
    match = _VISION_BLOCK_RE.search(text or "")
    if match is None:
        return None
    body = _truncate(match.group("body"), max_chars=max_chars)
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
    """Compact ``Image facts: …`` suffix for synthesized step ``full_description``."""
    body = _truncate(vision_summary, max_chars=max_chars)
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
