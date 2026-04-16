"""Plugin-side progress emission (IG-175: Community plugin SDK decoupling).

Provides a lightweight emit_progress function for plugin authors that works
both standalone (logging only) and when running inside the daemon's LangGraph
context (with stream writer callback).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

# Optional stream writer callback - set by the daemon at runtime
_STREAM_WRITER: Callable[[dict[str, Any]], None] | None = None


def set_stream_writer(writer: Callable[[dict[str, Any]], None] | None) -> None:
    """Set the stream writer callback (called by daemon at runtime).

    When running inside a LangGraph graph node, the daemon patches this
    callback with LangGraph's get_stream_writer() to emit custom events
    to the TUI.

    Args:
        writer: Callback function that accepts event dicts, or None to disable.
    """
    global _STREAM_WRITER
    _STREAM_WRITER = writer


def emit_progress(event: dict[str, Any] | Any, logger: logging.Logger | None = None) -> None:
    """Emit a progress event from a plugin subagent node.

    This function provides a stable API for plugin authors to emit
    custom events. It works in two modes:

    1. **Standalone mode** (when running outside the daemon): Only logs
       the event if a logger is provided.

    2. **Daemon mode** (when running inside a LangGraph context): Both
       logs and calls the stream writer callback to send the event to
       the TUI/CLI.

    Plugin authors use this in their subagent graph nodes:

    ```python
    from soothe_sdk import emit_progress
    import logging

    logger = logging.getLogger(__name__)


    def my_graph_node(state):
        # ... do work ...
        emit_progress(
            {
                "type": "soothe.plugin.myplugin.progress",
                "message": "Processing...",
            },
            logger=logger,
        )
        return updated_state
    ```

    Args:
        event: The event dict or object to emit. If a Pydantic model,
               its `.to_dict()` will be called if available.
        logger: Optional logger to log the event. If None, only stream writer is called.
    """
    # Convert Pydantic model to dict if needed
    if isinstance(event, dict):
        event_dict = event
    elif hasattr(event, "to_dict"):
        event_dict = event.to_dict()
    elif hasattr(event, "model_dump"):
        event_dict = event.model_dump()
    else:
        event_dict = {"data": str(event)}

    # Always log if logger provided
    if logger is not None:
        logger.info(f"[emit_progress] {event_dict.get('type', 'unknown')}: {event_dict}")

    # Call stream writer if available (set by daemon at runtime)
    if _STREAM_WRITER is not None:
        try:
            _STREAM_WRITER(event_dict)
        except Exception as e:
            # Stream writer errors should not break the graph node
            if logger is not None:
                logger.warning(f"emit_progress stream writer error: {e}")
