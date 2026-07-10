"""Human-readable duration strings for CLI and TUI (no Textual imports)."""

from __future__ import annotations


def format_duration(seconds: float) -> str:
    """Format a completed duration in seconds into a human-readable string.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like ``5s``, ``2.3s``, ``5m 12s``, or ``1h 23m 4s``.
        For live running timers that tick in whole seconds, use
        :func:`format_running_elapsed` instead.
    """
    rounded = round(seconds, 1)
    if rounded < 60:  # noqa: PLR2004
        if rounded % 1 == 0:
            return f"{int(rounded)}s"
        return f"{rounded:.1f}s"
    minutes, secs = divmod(int(rounded), 60)
    if minutes < 60:  # noqa: PLR2004
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {secs}s"


def format_running_elapsed(seconds: float) -> str:
    """Format a live running timer using whole-second ticks (e.g. ``20s``, ``1m 5s``)."""
    return format_duration(float(max(0, int(seconds))))


def format_duration_ms(milliseconds: int) -> str:
    """Format a wall-clock duration in milliseconds for status lines and cards.

    Values under one second stay in milliseconds for precision; longer durations
    reuse :func:`format_duration` (seconds, minutes, hours).

    Args:
        milliseconds: Elapsed time in milliseconds (negative values are treated as 0).

    Returns:
        Strings such as ``\"0ms\"``, ``\"240ms\"``, ``\"1.5s\"``, or ``\"2m 15s\"``.
    """
    ms = max(0, int(milliseconds))
    if ms < 1000:  # noqa: PLR2004
        return f"{ms}ms"
    return format_duration(ms / 1000.0)
