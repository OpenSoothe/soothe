"""``intent_hint`` validation for daemon ``loop_input`` direct model turns."""

from __future__ import annotations

from typing import Final

TEXT_COMPLETION: Final = "text_completion"
IMAGE_TO_TEXT: Final = "image_to_text"
OCR: Final = "ocr"
EMBED: Final = "embed"

DAEMON_DIRECT_HINTS: frozenset[str] = frozenset({TEXT_COMPLETION, IMAGE_TO_TEXT, OCR, EMBED})
STRUCTURED_OUTPUT_HINTS: frozenset[str] = frozenset({TEXT_COMPLETION, IMAGE_TO_TEXT})

_REMOVED_DIRECT_LLM_MSG: Final = (
    "intent_hint direct_llm is removed; "
    "use text_completion (text-only) or image_to_text (with attachments)"
)


def is_daemon_direct_hint(hint: str | None) -> bool:
    """Return True when ``hint`` selects a daemon-side direct model turn."""
    return bool(hint and hint in DAEMON_DIRECT_HINTS)


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

    if hint == "direct_llm":
        return None, _REMOVED_DIRECT_LLM_MSG

    if hint not in DAEMON_DIRECT_HINTS:
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
