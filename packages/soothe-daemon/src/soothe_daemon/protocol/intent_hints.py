"""``intent_hint`` validation for daemon ``loop_input`` non-agent turns."""

from __future__ import annotations

from typing import Final

TEXT_COMPLETION: Final = "text_completion"
IMAGE_TO_TEXT: Final = "image_to_text"
OCR: Final = "ocr"
EMBED: Final = "embed"

# Canonical daemon-side shortcuts (bypass the agent graph).
DAEMON_INTENT_HINTS: frozenset[str] = frozenset({TEXT_COMPLETION, IMAGE_TO_TEXT, OCR, EMBED})
STRUCTURED_OUTPUT_HINTS: frozenset[str] = frozenset({TEXT_COMPLETION, IMAGE_TO_TEXT})

# Legacy wire values rejected with migration messages (never pass through).
REMOVED_INTENT_HINTS: dict[str, str] = {
    "direct_llm": (
        "intent_hint direct_llm is removed; "
        "use text_completion (text-only) or image_to_text (with attachments)"
    ),
    "quiz": ("intent_hint quiz is removed; omit intent_hint and let intake classify the turn"),
    "direct_model": (
        "intent_hint direct_model is removed; use text_completion, image_to_text, ocr, or embed"
    ),
}


def is_daemon_intent_hint(hint: str | None) -> bool:
    """Return True when ``hint`` selects a daemon-side intent-hint turn."""
    return bool(hint and hint in DAEMON_INTENT_HINTS)


def validate_and_normalize_intent_hint(
    hint: str | None,
    *,
    prompt_text: str | None,
    has_attachments: bool,
    has_response_schema: bool,
) -> tuple[str | None, str | None]:
    """Validate ``loop_input`` intent hint.

    Args:
        hint: Normalized lowercase hint from the wire message.
        prompt_text: Coerced user text, or ``None`` when empty.
        has_attachments: Whether normalized image attachments are present.
        has_response_schema: Whether the client supplied ``response_schema``.

    Returns:
        ``(normalized_hint, error_message)``. On success ``error_message`` is ``None``.
        When ``hint`` is unset, returns ``(None, None)`` if content is present, else an error.
    """
    if not hint:
        if prompt_text is None:
            return None, "loop_id and non-empty content (string or object with text) required"
        return None, None

    if hint in REMOVED_INTENT_HINTS:
        return None, REMOVED_INTENT_HINTS[hint]

    if hint not in DAEMON_INTENT_HINTS:
        if prompt_text is None:
            return None, "loop_id and non-empty content (string or object with text) required"
        return hint, None

    if hint == TEXT_COMPLETION:
        if prompt_text is None:
            return None, "intent_hint text_completion requires non-empty content"
        if has_attachments:
            return (
                None,
                "intent_hint text_completion does not accept attachments; use image_to_text",
            )
    elif hint == IMAGE_TO_TEXT:
        if not has_attachments:
            return None, "intent_hint image_to_text requires non-empty attachments"
    elif hint == OCR:
        if not has_attachments:
            return None, "intent_hint ocr requires non-empty attachments"
    elif hint == EMBED:
        if prompt_text is None:
            return None, "intent_hint embed requires non-empty content"
        if has_attachments:
            return None, "intent_hint embed does not accept attachments"

    if has_response_schema and hint not in STRUCTURED_OUTPUT_HINTS:
        return (
            None,
            "response_schema is only supported with intent_hint text_completion or image_to_text",
        )

    return hint, None
