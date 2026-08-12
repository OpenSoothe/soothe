"""Compact id formatting for CLI and TUI status lines."""

from __future__ import annotations


def abbreviate_compact_id(
    value: str,
    *,
    head: int = 8,
    tail: int = 4,
    max_len: int = 14,
    empty: str = "",
) -> str:
    """Render a UUID-like id as ``prefix...suffix`` for compact UI surfaces.

    Strips surrounding brackets and hyphens before measuring length. Values that
    already contain ``...`` are returned unchanged (after hyphen stripping).

    Args:
        value: Raw id (loop id, etc.).
        head: Prefix length when abbreviating.
        tail: Suffix length when abbreviating.
        max_len: Keep the compact form intact when at most this many characters.
        empty: Returned when ``value`` is blank after stripping.

    Returns:
        Compact display string such as ``019f17e6...6543``.
    """
    raw = str(value or "").strip().strip("[]")
    if not raw:
        return empty
    compact = raw.replace("-", "")
    if "..." in compact:
        return compact
    if len(compact) <= max_len:
        return compact
    return f"{compact[:head]}...{compact[-tail:]}"


def compact_id_suffix(value: str, *, length: int = 4) -> str:
    """Render the trailing characters of a UUID-like id for tight UI surfaces.

    Args:
        value: Raw id (loop id, etc.).
        length: Number of trailing characters to keep.

    Returns:
        Short display string such as ``8d26``, or empty when ``value`` is blank.
    """
    raw = str(value or "").strip().strip("[]").replace("-", "")
    if not raw:
        return ""
    return raw[-length:] if length > 0 else ""
