"""Detect single-word loop-continuation user signals."""

from __future__ import annotations

# Single-token lines that force loop-continuation semantics (RFC-225 overlay).
_CONTINUE_KEYWORDS = frozenset({"continue", "resume", "proceed"})


def is_continue_keyword(text: str | None) -> bool:
    """Return True when *text* is a lone continuation keyword (case-insensitive).

    Only exact single-word submissions match — ``"continue cleaning"`` does not.
    """
    if not text:
        return False
    normalized = text.strip().lower()
    if not normalized:
        return False
    parts = normalized.split()
    return len(parts) == 1 and parts[0] in _CONTINUE_KEYWORDS


__all__ = ["is_continue_keyword"]
