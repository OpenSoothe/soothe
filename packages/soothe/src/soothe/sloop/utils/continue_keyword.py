"""Detect single-word loop-continuation and interrupt-resume user signals."""

from __future__ import annotations

# Single-token lines that force loop-continuation semantics on an *idle* loop
# (RFC-225 overlay): start a new goal that continues prior work via ledger.
_CONTINUE_KEYWORDS = frozenset({"continue", "resume", "proceed"})

# Single-token lines that resume an *interrupted* in-flight goal in place
# (same StrangeLoop goal + CE step DAG). Includes ``retry`` (loop 9e20 / IG-684).
_INTERRUPT_RESUME_KEYWORDS = frozenset({"continue", "resume", "proceed", "retry"})


def is_continue_keyword(text: str | None) -> bool:
    """Return True when *text* is a lone continuation keyword (case-insensitive).

    Only exact single-word submissions match — ``"continue cleaning"`` does not.
    Used for idle-loop new-goal bootstrap. Prefer
    :func:`is_interrupt_resume_keyword` when recovering a running interrupted goal.
    """
    return _is_single_keyword(text, _CONTINUE_KEYWORDS)


def is_interrupt_resume_keyword(text: str | None) -> bool:
    """Return True when *text* is a lone interrupt-resume keyword.

    Matches ``continue`` / ``resume`` / ``proceed`` / ``retry``. Used when a
    checkpoint still has an incomplete goal so the turn reuses the CE goal and
    step DAG instead of creating a blank plan titled ``retry``.
    """
    return _is_single_keyword(text, _INTERRUPT_RESUME_KEYWORDS)


def _is_single_keyword(text: str | None, keywords: frozenset[str]) -> bool:
    if not text:
        return False
    normalized = text.strip().lower()
    if not normalized:
        return False
    parts = normalized.split()
    return len(parts) == 1 and parts[0] in keywords


__all__ = ["is_continue_keyword", "is_interrupt_resume_keyword"]
