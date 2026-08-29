"""Text truncation helpers (L2)."""

from __future__ import annotations

__all__ = ["truncate_text"]


def truncate_text(
    text: str,
    *,
    limit: int,
    marker: str = "…",
    strip: bool = True,
    reserve_marker: bool = True,
) -> str:
    """Truncate *text* to at most *limit* characters, appending *marker*.

    Args:
        text: Input text to truncate.
        limit: Maximum output length (including marker when *reserve_marker*).
        marker: Ellipsis appended when text exceeds the limit.
        strip: When True, strip whitespace before measuring.
        reserve_marker: When True, reserve space for *marker* within *limit*
            (clip to ``limit - len(marker)``). When False, clip to *limit*
            and append *marker* beyond it.
    """
    s = text.strip() if strip else text
    if limit <= 0 or len(s) <= limit:
        return s
    if reserve_marker:
        clip = limit - len(marker)
        if clip <= 0:
            return marker
        return s[:clip].rstrip() + marker
    return s[:limit] + marker
