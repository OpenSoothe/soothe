"""Shared progress event emission for Soothe subagents."""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import logging

# Context variable for current step ID
_current_step_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_step_id", default=None)


def set_step_context(step_id: str | None) -> contextvars.Token:
    """Set the current step ID in context.

    Args:
        step_id: Step ID to set, or None to clear.

    Returns:
        Token for resetting context to previous value.
    """
    return _current_step_id.set(step_id)


def reset_step_context(token: contextvars.Token) -> None:
    """Reset step context to previous value.

    Args:
        token: Token returned by set_step_context().
    """
    _current_step_id.reset(token)


def get_step_id() -> str | None:
    """Get current step ID from context.

    Returns:
        Current step ID or None if not in a step context.
    """
    return _current_step_id.get()


def _format_event_compact(event: dict[str, Any]) -> str:
    """Format event dict into a compact, readable string.

    Extracts key fields and formats them concisely:
    - Shortens event type (removes 'soothe.' prefix)
    - Shows important fields based on event type
    - Truncates long values

    Args:
        event: Event dictionary with at minimum a 'type' key.

    Returns:
        Compact string representation.
    """
    event_type = event.get("type", "unknown")
    # Shorten type: "soothe.tool.execution.command_started" -> "tool.execution.command_started"
    short_type = event_type.replace("soothe.", "") if event_type.startswith("soothe.") else event_type

    # Key fields to extract (in priority order)
    key_fields = ["tool", "command", "exit_code", "duration_ms", "error", "timeout", "pid", "session_id", "success"]

    parts = [short_type]

    for field in key_fields:
        if field in event:
            val = event[field]
            if val is None:
                continue
            # Format duration nicely
            if field == "duration_ms":
                parts.append(f"duration={val}ms")
            # Truncate long strings
            elif isinstance(val, str) and len(val) > 50:
                parts.append(f"{field}={val[:47]}...")
            else:
                parts.append(f"{field}={val}")

    return " ".join(parts)


def emit_progress(event: dict[str, Any], logger: logging.Logger) -> None:
    """Emit a progress event via the LangGraph stream writer with logging fallback.

    Always logs to file first for backend audit trail, then attempts stream emission.
    This is the canonical way for Soothe subagent graph nodes to surface
    ``soothe.*`` custom events to the TUI / headless renderer.

    Automatically injects step_id from context if available and not already present.

    Args:
        event: Event dict with at minimum a ``type`` key.
        logger: Caller's logger instance for logging.
    """
    # Always log to file first for audit trail (compact format)
    logger.info(_format_event_compact(event))

    # Inject step_id if available in context
    step_id = get_step_id()
    if step_id and "step_id" not in event:
        event = {**event, "step_id": step_id}

    # Also emit to stream if available (for TUI/headless rendering)
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        if writer:
            writer(event)
    except (ImportError, RuntimeError, KeyError):
        pass
