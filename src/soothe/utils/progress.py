"""Shared progress event emission for Soothe subagents."""

from __future__ import annotations

import logging
from typing import Any


def emit_progress(event: dict[str, Any], logger: logging.Logger) -> None:
    """Emit a progress event via the LangGraph stream writer with logging fallback.

    This is the canonical way for Soothe subagent graph nodes to surface
    ``soothe.*`` custom events to the TUI / headless renderer.

    Args:
        event: Event dict with at minimum a ``type`` key.
        logger: Caller's logger instance for fallback logging.
    """
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        if writer:
            writer(event)
    except (ImportError, RuntimeError):
        pass
    logger.info("Progress: %s", event)
