"""Unified registry for user-visible output events.

This module provides a single source of truth for event types that produce
user-visible assistant text. Both CLI and TUI query this registry to determine
which events to display and how to extract their content.

Architecture rationale (IG-254):
- Adding new query types (quiz, trivia, etc.) previously required modifications
  in THREE places: CLI EventProcessor, TUI Adapter, and SDK constants
- This registry centralizes extraction logic so new output events only need
  ONE registration → both CLI and TUI automatically work

Usage:
    from soothe_sdk.ux.output_events import is_output_event, extract_output_text

    # CLI/TUI check if event should be displayed as assistant text
    if is_output_event(event_type):
        text = extract_output_text(event_type, data)
        if text:
            display_assistant_text(text)

Extensibility:
    Plugins can register custom output events:
    from soothe_sdk.ux.output_events import register_output_event

    register_output_event(
        "soothe.plugin.custom.response",
        lambda data: data.get("answer", ""),
    )
"""

from __future__ import annotations

from collections.abc import Callable

from soothe_sdk.ux import strip_internal_tags

# Registry: event_type → extraction function
# Each extractor takes event data dict and returns user-visible text or None
_OUTPUT_EVENT_REGISTRY: dict[str, Callable[[dict], str | None]] = {}


def _register_builtin_output_events() -> None:
    """Register core Soothe output events on module load."""
    # Chitchat responses (IG-226 unified classifier)
    register_output_event(
        "soothe.output.chitchat.responded",
        lambda data: strip_internal_tags(data.get("content", "")),
    )

    # Quiz responses (IG-250, IG-254)
    register_output_event(
        "soothe.output.quiz.responded",
        lambda data: strip_internal_tags(data.get("content", "")),
    )

    # Execution streaming (RFC-614)
    register_output_event(
        "soothe.output.execution.streaming",
        # Preserve raw chunk boundaries for proper concatenation.
        lambda data: data.get("content", ""),
    )

    # Synthesis streaming removed in IG-273; superseded by
    # ``soothe.output.goal_completion.streaming`` below.

    # Goal completion streaming (IG-273)
    register_output_event(
        "soothe.output.goal_completion.streaming",
        # Preserve raw chunk boundaries for proper concatenation.
        lambda data: data.get("content", ""),
    )

    # Goal completion final output (hard cutover)
    register_output_event(
        "soothe.output.goal_completion.responded",
        lambda data: data.get("content", ""),
    )

    # Tool response streaming (RFC-614, experimental)
    register_output_event(
        "soothe.output.tool_response.streaming",
        lambda data: data.get("content", ""),
    )

    # Autonomous mode goal completion (RFC-300, IG-273)
    register_output_event(
        "soothe.output.autonomous.goal_completion.reported",
        lambda data: strip_internal_tags(data.get("content", data.get("summary", ""))),
    )


def register_output_event(
    event_type: str,
    extractor: Callable[[dict], str | None],
) -> None:
    """Register an output event type with its content extraction function.

    Args:
        event_type: Full event type string (e.g., "soothe.output.quiz.responded").
        extractor: Function that extracts user-visible text from event data.
            Takes dict, returns str or None. None suppresses display.

    Note:
        This registry is global. For plugin isolation, use unique event_type
        prefixes (e.g., "soothe.plugin.my_plugin.response").
    """
    _OUTPUT_EVENT_REGISTRY[event_type] = extractor


def is_output_event(event_type: str) -> bool:
    """Check if event type is a user-visible output event.

    Args:
        event_type: Full event type string.

    Returns:
        True if event should be displayed as assistant text in CLI/TUI.
    """
    return event_type in _OUTPUT_EVENT_REGISTRY


def extract_output_text(event_type: str, data: dict) -> str | None:
    """Extract user-visible text from an output event.

    Args:
        event_type: Full event type string.
        data: Event payload dictionary.

    Returns:
        User-visible text to display, or None if:
        - Event type is not registered
        - Extractor returns None (suppressed)
        - Content is empty after stripping internal tags
    """
    extractor = _OUTPUT_EVENT_REGISTRY.get(event_type)
    if extractor is None:
        return None

    try:
        text = extractor(data)
        if text is None:
            return None

        # Ensure non-empty after stripping
        return text if text.strip() else None
    except Exception:
        # Extractor errors should not crash CLI/TUI
        # Log and return None (suppress display)
        import logging

        logger = logging.getLogger(__name__)
        logger.debug(
            "Output event extractor failed for %s: %s",
            event_type,
            data,
            exc_info=True,
        )
        return None


# Register built-in events on module import
_register_builtin_output_events()


__all__ = [
    "register_output_event",
    "is_output_event",
    "extract_output_text",
]
