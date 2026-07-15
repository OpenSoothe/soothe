"""Shared progress event emission for Soothe subagents."""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import logging

# Context variable for current step ID
_current_step_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_step_id", default=None
)

# Intake-only / outer bridges when LangGraph ``get_stream_writer`` is unavailable
# (e.g. long single-node browser_use runs). Sync callback; may schedule onto a loop.
_wire_bridge: contextvars.ContextVar[Callable[[dict[str, Any]], None] | None] = (
    contextvars.ContextVar("subagent_wire_bridge", default=None)
)

# Per-event-loop fallback for cases where ContextVar propagation is lost across
# tasks/callback boundaries while still running on the same loop.
_loop_wire_bridge: dict[int, Callable[[dict[str, Any]], None]] = {}
_loop_wire_bridge_lock = threading.Lock()

# Constants for formatting
_MAX_FIELD_LEN = 50


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


def set_wire_bridge(callback: Callable[[dict[str, Any]], None] | None) -> contextvars.Token:
    """Install a sync sink for wire/progress events (intake-only stream bridge)."""
    token = _wire_bridge.set(callback)
    if callback is not None:
        try:
            import asyncio

            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            with _loop_wire_bridge_lock:
                _loop_wire_bridge[id(loop)] = callback
    return token


def reset_wire_bridge(token: contextvars.Token) -> None:
    """Restore the previous wire bridge callback."""
    try:
        import asyncio

        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    previous_callback = _wire_bridge.get()
    loop_id = id(loop) if loop is not None else None
    if loop_id is not None and previous_callback is not None:
        with _loop_wire_bridge_lock:
            if _loop_wire_bridge.get(loop_id) is previous_callback:
                _loop_wire_bridge.pop(loop_id, None)

    _wire_bridge.reset(token)

    # Nested set/reset support: re-install the now-current callback if present.
    if loop_id is not None:
        current_callback = _wire_bridge.get()
        with _loop_wire_bridge_lock:
            if current_callback is None:
                _loop_wire_bridge.pop(loop_id, None)
            else:
                _loop_wire_bridge[loop_id] = current_callback


def get_wire_bridge() -> Callable[[dict[str, Any]], None] | None:
    """Return the active wire bridge sink, if any."""
    callback = _wire_bridge.get()
    if callback is not None:
        return callback

    try:
        import asyncio

        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None

    with _loop_wire_bridge_lock:
        return _loop_wire_bridge.get(id(loop))


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
    short_type = (
        event_type.replace("soothe.", "") if event_type.startswith("soothe.") else event_type
    )

    # Key fields to extract (in priority order)
    key_fields = [
        "tool",
        "tool_name",
        "command",
        "url",
        "action_preview",
        "exit_code",
        "duration_ms",
        "error",
        "timeout",
        "pid",
        "session_id",
        "success",
    ]

    parts = [short_type]

    for field in key_fields:
        if field in event:
            val = event[field]
            if val is None or val == "":
                continue
            # Format duration nicely
            if field == "duration_ms":
                parts.append(f"duration={val}ms")
            # Truncate long strings
            elif isinstance(val, str) and len(val) > _MAX_FIELD_LEN:
                parts.append(f"{field}={val[: _MAX_FIELD_LEN - 3]}...")
            else:
                parts.append(f"{field}={val}")

    return " ".join(parts)


def emit_progress(event: dict[str, Any], logger: logging.Logger) -> None:
    """Emit a progress event via wire bridge or LangGraph stream writer.

    Always logs to file first for backend audit trail, then attempts stream emission.
    This is the canonical way for Soothe subagent graph nodes to surface
    ``soothe.*`` custom events to the TUI / headless renderer.

    Automatically injects step_id from context if available and not already present.

    When an intake-only wire bridge is installed, events go only through that sink
    (avoiding duplicate astream ``custom`` delivery).

    Args:
        event: Event dict with at minimum a ``type`` key.
        logger: Caller's logger instance for logging.
    """
    # Always log to file first for audit trail (compact format)
    logger.debug(_format_event_compact(event))

    # Inject step_id if available in context
    step_id = get_step_id()
    if step_id and "step_id" not in event:
        event = {**event, "step_id": step_id}

    bridge = get_wire_bridge()
    if bridge is not None:
        try:
            bridge(event)
        except Exception:
            logger.debug("Wire bridge sink failed", exc_info=True)
        return

    # LangGraph custom stream (parented task / when no outer bridge).
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        if writer:
            writer(event)
    except (ImportError, RuntimeError, KeyError):
        pass
