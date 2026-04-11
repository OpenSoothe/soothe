"""Unified text preview utility for consistent truncation across the codebase.

Provides char-based, line-based, and full-output preview modes with configurable
markers.  Replace all hard-coded ``text[:N]`` slicing, ``%.Ns`` printf-style
formatting, and ad-hoc truncation functions with calls to this module.

Usage:
    >>> from soothe.utils.text_preview import preview, preview_first, log_preview

    # Char-based (most common for logging)
    >>> preview_first("A very long string", chars=10)
    'A very lo[...8 chars abbr...]'

    # First + last chars
    >>> preview("Hello world!", mode="chars", first=5, last=3)
    'Hello[...4 chars abbr...]d!'

    # Line-based
    >>> preview("Line1\\nLine2\\nLine3\\nLine4", mode="lines", first=1, last=1)
    'Line1\\n[...2 lines abbr...]\\nLine4'

    # Full output (no truncation)
    >>> preview("Any text", mode="full")
    'Any text'

    # Logger-optimized shorthand
    >>> log_preview("Debug output", chars=5)
    'Debug...'
"""

from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
# Default constants
# ---------------------------------------------------------------------------

DEFAULT_PREVIEW_CHARS: int = 200
"""Default character limit for char-based previews."""

DEFAULT_PREVIEW_LINES: int = 5
"""Default line limit for line-based previews."""

DEFAULT_MARKER_TEMPLATE: str = "[...{count} {unit} abbr...]"
"""Template for auto-generated truncation markers.

Available variables: ``{count}`` (number of omitted units) and ``{unit}``
(``"chars"`` or ``"lines"``).
"""

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ELLIPSIS = "..."


def _build_marker(count: int, unit: str, marker: str | None) -> str:
    """Return the truncation marker string.

    Args:
        count: Number of omitted chars/lines.
        unit: ``"chars"`` or ``"lines"``.
        marker: Custom marker.  ``None`` uses the default template.

    Returns:
        Marker string.
    """
    if marker is not None:
        return marker
    return DEFAULT_MARKER_TEMPLATE.format(count=count, unit=unit)


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def preview(
    text: str,
    *,
    mode: Literal["chars", "lines", "full"] = "chars",
    first: int | None = None,
    last: int | None = None,
    marker: str | None = None,
) -> str:
    """Generate a preview of text with configurable truncation.

    Args:
        text: Input text to preview.
        mode: Preview mode:
            - ``"chars"``: Character-based truncation (default).
            - ``"lines"``: Line-based truncation.
            - ``"full"``: No truncation (return as-is).
        first: First N chars/lines to include.  Defaults to 200 (chars) or
            5 (lines).
        last: Last N chars/lines to include.  When ``None``, only the
            *first* portion is shown.  When set, both *first* and *last*
            are shown with a marker in between.
        marker: Custom truncation marker.  ``None`` uses the default
            ``"[...N chars/lines abbr...]"``.  Set to ``""`` to suppress.

    Returns:
        Previewed text with optional truncation marker.

    Examples:
        >>> preview("Hello world", mode="chars", first=5)
        'Hello[...6 chars abbr...]'

        >>> preview("Line1\\nLine2\\nLine3\\nLine4", mode="lines", first=1, last=1)
        'Line1\\n[...2 lines abbr...]\\nLine4'

        >>> preview("Any text", mode="full")
        'Any text'
    """
    if mode == "full" or not text:
        return text

    if mode == "chars":
        return _preview_chars(text, first=first, last=last, marker=marker)

    # mode == "lines"
    return _preview_lines(text, first=first, last=last, marker=marker)


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


def preview_first(text: str, chars: int = DEFAULT_PREVIEW_CHARS) -> str:
    """Preview the first N characters.

    This is the most common pattern for logging and display.

    Args:
        text: Input text.
        chars: Maximum number of characters to include.

    Returns:
        Previewed text with default marker if truncated.
    """
    return preview(text, mode="chars", first=chars)


def preview_lines(
    text: str,
    first: int = DEFAULT_PREVIEW_LINES,
    last: int = 0,
) -> str:
    """Preview the first N lines and optionally the last M lines.

    Args:
        text: Input text.
        first: Number of leading lines.
        last: Number of trailing lines.  ``0`` means no trailing lines.

    Returns:
        Previewed text with default marker if truncated.
    """
    return preview(text, mode="lines", first=first, last=last if last > 0 else None)


def preview_full(text: str) -> str:
    """Return text with no truncation.

    Use this for explicit clarity when a code path conditionally switches
    between preview modes.
    """
    return preview(text, mode="full")


def log_preview(text: str, chars: int = DEFAULT_PREVIEW_CHARS) -> str:
    """Logger-optimized preview with a minimal ``"..."`` marker.

    Intended for ``logger.debug()`` and ``logger.info()`` calls where the
    default ``[...N chars abbr...]`` marker is too verbose.

    Args:
        text: Input text.
        chars: Maximum number of characters.

    Returns:
        Previewed text with ``"..."`` marker if truncated.

    Examples:
        >>> log_preview("Debug output here", chars=5)
        'Debug...'
    """
    return preview(text, mode="chars", first=chars, marker=_ELLIPSIS)


# ---------------------------------------------------------------------------
# Internal implementations
# ---------------------------------------------------------------------------


def _preview_chars(
    text: str,
    *,
    first: int | None,
    last: int | None,
    marker: str | None,
) -> str:
    """Char-based preview implementation."""
    first_n = first if first is not None else DEFAULT_PREVIEW_CHARS
    last_n = last if last is not None else 0

    total = len(text)

    # No truncation needed
    if total <= first_n:
        return text

    # Only first portion requested
    if last_n <= 0:
        omitted = total - first_n
        m = _build_marker(omitted, "chars", marker)
        return text[:first_n] + m

    # First + last: check overlap
    if first_n + last_n >= total:
        return text

    omitted = total - first_n - last_n
    m = _build_marker(omitted, "chars", marker)
    return text[:first_n] + m + text[total - last_n :]


def _preview_lines(
    text: str,
    *,
    first: int | None,
    last: int | None,
    marker: str | None,
) -> str:
    """Line-based preview implementation."""
    first_n = first if first is not None else DEFAULT_PREVIEW_LINES
    last_n = last if last is not None else 0

    # Split preserving line endings for faithful reconstruction
    lines = text.splitlines(keepends=True)
    total = len(lines)

    # No truncation needed
    if total <= first_n:
        return text

    # Only first portion requested
    if last_n <= 0:
        omitted = total - first_n
        m = _build_marker(omitted, "lines", marker)
        return "".join(lines[:first_n]) + m

    # First + last: check overlap
    if first_n + last_n >= total:
        return text

    omitted = total - first_n - last_n
    m = _build_marker(omitted, "lines", marker)
    return "".join(lines[:first_n]) + m + "".join(lines[total - last_n :])
