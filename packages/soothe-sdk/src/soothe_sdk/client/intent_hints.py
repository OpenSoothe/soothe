"""``loop_input.intent_hint`` constants and client-side validation."""

from __future__ import annotations

from typing import Final

TEXT_COMPLETION: Final = "text_completion"
IMAGE_TO_TEXT: Final = "image_to_text"
OCR: Final = "ocr"
EMBED: Final = "embed"

REMOVED_INTENT_HINTS: frozenset[str] = frozenset({"direct_llm", "quiz"})

_REMOVED_INTENT_HINT_MESSAGES: dict[str, str] = {
    "direct_llm": (
        "intent_hint direct_llm is removed; "
        "use text_completion (text-only) or image_to_text (with attachments)"
    ),
    "quiz": "intent_hint quiz is removed; omit intent_hint and let intake classify the turn",
}


def validate_loop_input_intent_hint(hint: str) -> str | None:
    """Return an error message when ``hint`` is a removed legacy value.

    Direct model hints and agent-path pass-through values (e.g.
    ``resume_clarification``, ``skill:foo``) are allowed.
    """
    key = hint.strip().lower()
    return _REMOVED_INTENT_HINT_MESSAGES.get(key)
