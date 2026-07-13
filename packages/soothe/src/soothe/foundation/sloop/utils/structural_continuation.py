"""Structural loop-continuation controls (RFC-225, RFC-630, IG-558).

Continuation is derived from checkpoint state and explicit control phrases,
not from Pass 1 social classification. These helpers run before the pre-graph
social fast-path so bare ``continue`` and loop-resume phrases resume work
instead of closing the active goal via chitchat finalize.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from soothe.foundation.sloop.utils.continue_keyword import is_continue_keyword

if TYPE_CHECKING:
    from soothe.foundation.sloop.state.execution_checkpoint import GoalIndexEntry

# Phrases that request loop resume rather than social chitchat (match anywhere in text).
_LOOP_CONTINUATION_PHRASE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcontinue\s+(?:this|the|current)\s+loop\b", re.IGNORECASE),
    re.compile(r"\bresume\s+(?:this|the|current)\s+loop\b", re.IGNORECASE),
    re.compile(r"\bproceed\s+(?:with\s+)?(?:this|the|current)\s+loop\b", re.IGNORECASE),
    re.compile(r"\bcontinue\s+this\s+loop\s+to\s+finish\b", re.IGNORECASE),
)


def is_loop_continuation_phrase(text: str | None) -> bool:
    """Return True when *text* is an explicit loop-resume phrase.

    Single-word keywords are handled by :func:`is_continue_keyword`.
    """
    normalized = (text or "").strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _LOOP_CONTINUATION_PHRASE_PATTERNS)


def is_loop_control_signal(text: str | None) -> bool:
    """Return True when *text* is a deterministic loop-control signal."""
    return is_continue_keyword(text) or is_loop_continuation_phrase(text)


def _active_goal_record(checkpoint: Any) -> GoalIndexEntry | None:
    idx = getattr(checkpoint, "current_goal_index", -1)
    history = getattr(checkpoint, "goal_history", None) or []
    if not isinstance(idx, int) or idx < 0 or idx >= len(history):
        return None
    return history[idx]


def has_active_running_goal(checkpoint: Any | None) -> bool:
    """Return True when the checkpoint has a goal still marked running."""
    if checkpoint is None:
        return False
    goal = _active_goal_record(checkpoint)
    return goal is not None and getattr(goal, "status", None) == "running"


def should_bypass_pass1_social_fast_path(
    checkpoint: Any | None,
    user_text: str | None,
) -> bool:
    """Return True when Pass 1 social fast-path must not short-circuit intake.

    Only explicit loop-control phrases bypass social routing. Other social
    messages on a running loop still use the chitchat path, but chitchat
    finalize is blocked separately via :func:`chitchat_may_finalize_checkpoint`.
    """
    return is_loop_control_signal(user_text)


def chitchat_may_finalize_checkpoint(checkpoint: Any | None) -> bool:
    """Return True when chitchat is allowed to finalize the active goal.

    Chitchat on a running loop must not mark goals completed. Finalize only when
    the checkpoint is idle (goal already completed through the normal graph) or
    when there is no goal history to mutate.
    """
    if checkpoint is None:
        return False
    status = getattr(checkpoint, "status", None)
    if status != "idle":
        return False
    if has_active_running_goal(checkpoint):
        return False
    return True


__all__ = [
    "chitchat_may_finalize_checkpoint",
    "has_active_running_goal",
    "is_loop_continuation_phrase",
    "is_loop_control_signal",
    "should_bypass_pass1_social_fast_path",
]
