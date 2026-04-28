"""Shared types and helpers for SootheRunner mixins."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.config import SootheConfig

StreamChunk = tuple[tuple[str, ...], str, Any]
"""Deepagents-canonical stream chunk: ``(namespace, mode, data)``."""

_MIN_MEMORY_STORAGE_LENGTH = 50

_logger = logging.getLogger(__name__)


def _custom(data: dict[str, Any]) -> StreamChunk:
    """Build a soothe protocol custom event chunk."""
    return ((), "custom", data)


def _wrap_streaming_output(
    chunk: StreamChunk,
    event_type: str,
    *,
    config: SootheConfig | None = None,
    namespace: tuple[str, ...] = (),
) -> StreamChunk | None:
    """Wrap streaming AI text chunks as custom output events (RFC-614).

    Architecture Pattern:
    - Extracts AI text from LangGraph messages-mode chunks
    - Wraps as custom events: ((), "custom", {"type": event_type, ...})
    - Custom events bypass IG-119 filtering (mode="custom")
    - Config-driven: returns None if streaming disabled

    Reuses proven pattern from goal_completion_stream logic.

    Args:
        chunk: Raw stream chunk from LangGraph astream (namespace, mode, data).
        event_type: Custom event type following RFC-403 naming convention.
        config: SootheConfig to check streaming enabled flag.
        namespace: Namespace tuple for concurrent stream isolation.

    Returns:
        Custom event chunk if streaming enabled and has text, None otherwise.
    """
    # Config check: Early return if streaming disabled (minimal overhead)
    if config and not config.output_streaming.enabled:
        return None

    # Extract AI text from messages-mode chunks
    from langchain_core.messages import AIMessage, AIMessageChunk

    from soothe.cognition.agent_loop.utils.stream_normalize import (
        extract_text_from_message_content,
        iter_messages_for_act_aggregation,
    )

    # chunk is (namespace, mode, data) from LangGraph astream
    for msg in iter_messages_for_act_aggregation(chunk):
        if isinstance(msg, (AIMessage, AIMessageChunk)):
            text = extract_text_from_message_content(msg.content)
            if text:  # Allow whitespace chunks for boundary preservation
                # Stream as custom output event (bypasses IG-119 filter)
                return _custom(
                    {
                        "type": event_type,
                        "content": text,
                        "is_chunk": isinstance(msg, AIMessageChunk),
                        "namespace": list(namespace),  # Preserve namespace context
                    }
                )

    return None


def _validate_goal(goal: str | None, user_input: str) -> str:
    """Ensure goal is never empty or just punctuation.

    Args:
        goal: The plan goal from planner.
        user_input: Original user input as fallback.

    Returns:
        Validated goal string.
    """
    if not goal or goal.strip() in {":", ""}:
        _logger.warning("Empty or invalid goal detected, using user input")
        return user_input or "Unnamed goal"
    return goal.strip()
