"""Shared progress event emission for Soothe subagents."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import logging


def emit_progress(event: dict[str, Any], logger: logging.Logger) -> None:
    """Emit a progress event via the LangGraph stream writer with logging fallback.

    Always logs to file first for backend audit trail, then attempts stream emission.
    This is the canonical way for Soothe subagent graph nodes to surface
    ``soothe.*`` custom events to the TUI / headless renderer.

    Args:
        event: Event dict with at minimum a ``type`` key.
        logger: Caller's logger instance for logging.
    """
    # Always log to file first for audit trail
    logger.info("Progress: %s", event)

    # Also emit to stream if available (for TUI/headless rendering)
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        if writer:
            writer(event)
    except (ImportError, RuntimeError, KeyError):
        pass
