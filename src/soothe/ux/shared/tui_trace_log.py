"""Structured INFO logs for TUI debugging when ``SootheConfig.tui_debug`` is true.

Enable via ``SOOTHE_TUI_DEBUG=true`` or ``tui_debug: true`` in config. Logs use logger
``soothe.ux.tui.trace`` so you can filter with ``SOOTHE_LOG_LEVEL=INFO`` and grep for
``tui_trace``.
"""

from __future__ import annotations

import logging
from typing import Any

_logger = logging.getLogger("soothe.ux.tui.trace")

_PREVIEW_CHARS = 180


def _fmt_field(key: str, value: Any) -> str:
    if isinstance(value, str) and len(value) > _PREVIEW_CHARS:
        value = value[:_PREVIEW_CHARS] + "..."
    return f"{key}={value!r}"


def log_tui_trace(*, tui_debug: bool, event: str, **fields: Any) -> None:
    """Emit a single INFO log line when TUI debug mode is enabled.

    Args:
        tui_debug: Whether tracing is enabled (from config).
        event: Short event name (e.g. ``renderer.assistant_text``).
        fields: Key/value pairs appended as ``key='value'`` (strings truncated).
    """
    if not tui_debug:
        return
    if fields:
        tail = " ".join(_fmt_field(k, v) for k, v in fields.items())
        _logger.info("tui_trace | %s | %s", event, tail)
    else:
        _logger.info("tui_trace | %s", event)
