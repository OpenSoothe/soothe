"""Host-side text preview helpers for context and planner logging."""

from __future__ import annotations

from soothe_nano.utils.text_preview import log_preview, preview, preview_first

_ATTACHMENT_BODY_MARKERS: tuple[str, ...] = ("--- Triarch attachments (extracted content) ---",)
DEFAULT_GOAL_LOG_CHARS: int = 1200


def goal_description_for_log(
    description: str,
    *,
    max_chars: int = DEFAULT_GOAL_LOG_CHARS,
) -> str:
    """Return a log-safe goal description without extracted attachment bodies."""
    text = description or ""
    if not text:
        return ""

    cut: int | None = None
    for marker in _ATTACHMENT_BODY_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            cut = idx if cut is None else min(cut, idx)

    if cut is not None:
        text = text[:cut].rstrip()
        if not text:
            return ""

    return log_preview(text, chars=max_chars)


def create_output_summary(
    content: str,
    first_chars: int = 300,
    last_chars: int = 200,
) -> dict[str, str]:
    """Create truncated output summary for planner evidence payloads."""
    if not content:
        return {"first": "", "last": ""}

    total_len = len(content)
    if total_len <= first_chars + last_chars:
        return {"first": content, "last": ""}

    first_section = content[:first_chars]
    last_section = content[total_len - last_chars :]
    last_space_in_first = first_section.rfind(" ")
    if last_space_in_first > first_chars * 0.8:
        first_section = first_section[:last_space_in_first]

    return {"first": first_section.strip(), "last": last_section.strip()}


__all__ = [
    "create_output_summary",
    "goal_description_for_log",
    "log_preview",
    "preview",
    "preview_first",
]
