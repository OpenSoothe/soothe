"""Shared helpers and constants for message widgets."""

from __future__ import annotations

import logging
import os
import re
import weakref
from time import monotonic
from typing import Any

from soothe_cli.display import theme

logger = logging.getLogger(__name__)

# TUI refresh throttling - minimum interval between widget refreshes
_DEFAULT_TUI_REFRESH_INTERVAL_MS = 800
"""Default minimum interval between TUI refreshes in milliseconds."""

_global_refresh_interval_ms: int | None = None


def _get_tui_refresh_interval_ms() -> int:
    """Get the TUI refresh interval from environment or default.

    Returns:
    Minimum interval between refreshes in milliseconds.
    """
    global _global_refresh_interval_ms
    if _global_refresh_interval_ms is not None:
        return _global_refresh_interval_ms
    from soothe_cli._env_vars import TUI_REFRESH_INTERVAL_MS

    env_val = os.environ.get(TUI_REFRESH_INTERVAL_MS)
    if env_val:
        try:
            parsed = int(env_val.strip())
            if parsed >= 50:  # Minimum 50ms to prevent UI lockup
                _global_refresh_interval_ms = parsed
                return parsed
        except ValueError:
            pass
    _global_refresh_interval_ms = _DEFAULT_TUI_REFRESH_INTERVAL_MS
    return _DEFAULT_TUI_REFRESH_INTERVAL_MS


def _should_refresh_now(last_refresh_time: float | None) -> bool:
    """Check if enough time has passed since last refresh for throttling.

    Args:
    last_refresh_time: Monotonic time of last refresh, or None if never refreshed.

    Returns:
    True if refresh should proceed, False if throttled.
    """
    if last_refresh_time is None:
        return True
    interval_secs = _get_tui_refresh_interval_ms() / 1000.0
    return (monotonic() - last_refresh_time) >= interval_secs


_RUNNING_SPINNER_INTERVAL_SECONDS = 0.2
"""Spinner/status animation cadence for running cards."""

# Deferred tool-list refresh (turn-level coalescing + global repaint budget).
_DEFERRED_TOOL_REFRESH_WIDGETS: weakref.WeakSet[Any] = weakref.WeakSet()
_global_tools_list_refresh_at: float = 0.0


def reset_turn_tool_refresh_state() -> None:
    """Clear deferred refresh registry at the start of a new agent turn."""
    global _global_tools_list_refresh_at
    _global_tools_list_refresh_at = 0.0
    _DEFERRED_TOOL_REFRESH_WIDGETS.clear()


def request_deferred_tools_refresh(widget: Any) -> None:
    """Queue a card for batched tool-list repaint."""
    _DEFERRED_TOOL_REFRESH_WIDGETS.add(widget)


def flush_deferred_tools_refreshes(*, force: bool = False) -> None:
    """Repaint queued tool cards (global budget unless `force`)."""
    global _global_tools_list_refresh_at
    pending = list(_DEFERRED_TOOL_REFRESH_WIDGETS)
    if not pending:
        return
    now = monotonic()
    if not force:
        interval = _get_tui_refresh_interval_ms() / 1000.0
        if now - _global_tools_list_refresh_at < interval:
            return
    _global_tools_list_refresh_at = now
    _DEFERRED_TOOL_REFRESH_WIDGETS.clear()
    for widget in pending:
        flush_fn = getattr(widget, "_flush_deferred_tools_refresh", None)
        if callable(flush_fn):
            flush_fn()


def _is_widget_animation_visible(widget: object) -> bool:
    """Return whether a widget is currently visible on screen.

    This is used to skip animation work for off-screen cards.
    """
    try:
        if not getattr(widget, "is_attached", False):
            return False
        if not getattr(widget, "visible", True):
            return False
        is_on_screen = getattr(widget, "is_on_screen", True)
        if callable(is_on_screen):
            return bool(is_on_screen())
        return bool(is_on_screen)
    except Exception:
        return False


def _mode_color(mode: str | None, widget_or_app: object | None = None) -> str:
    """Return the hex color string for a mode, falling back to primary.

    Args:
    mode: Mode name (e.g. `'shell'`, `'command'`) or `None`.
    widget_or_app: Textual widget or `App` for theme-aware lookup.

    Returns:
    Color string from the active theme's `ThemeColors`.
    """
    colors = theme.get_theme_colors(widget_or_app)
    if not mode:
        return colors.primary
    if mode == "shell":
        return colors.mode_bash
    if mode == "command":
        return colors.mode_command
    logger.warning("Missing color for mode '%s'; falling back to primary.", mode)
    return colors.primary


_SUCCESS_EXIT_RE = re.compile(r"\n?\[Command succeeded with exit code 0\]\s*$")
"""Strip the SDK's `[Command succeeded with exit code 0]` trailer from tool output."""


def _strip_success_exit_line(text: str) -> str:
    """Remove the `[Command succeeded with exit code 0]` trailer.

    Non-zero exit codes are left intact (they come through `set_error`).

    Args:
    text: Raw tool output string.

    Returns:
    Text with the success exit-code trailer removed, if present.
    """
    return _SUCCESS_EXIT_RE.sub("", text)
