"""Structural loop-continuation controls (RFC-225, RFC-630).

Continuation is derived from *this loop's* checkpoint plus an explicit control
phrase, not from social classification alone. A control phrase without goal
records on this loop keeps the intake social result.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from soothe.sloop.utils.continue_keyword import is_interrupt_resume_keyword

if TYPE_CHECKING:
    from soothe.sloop.state.execution_checkpoint import GoalIndexEntry

# Phrases that request loop resume rather than social chitchat (match anywhere in text).
_LOOP_CONTINUATION_PHRASE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcontinue\s+(?:this|the|current)\s+loop\b", re.IGNORECASE),
    re.compile(r"\bresume\s+(?:this|the|current)\s+loop\b", re.IGNORECASE),
    re.compile(r"\bproceed\s+(?:with\s+)?(?:this|the|current)\s+loop\b", re.IGNORECASE),
    re.compile(r"\bcontinue\s+this\s+loop\s+to\s+finish\b", re.IGNORECASE),
    re.compile(r"\bretry\s+(?:this|the|current)\s+(?:goal|loop|task)\b", re.IGNORECASE),
)


def is_loop_continuation_phrase(text: str | None) -> bool:
    """Return True when *text* is an explicit loop-resume phrase.

    Single-word keywords are handled by :func:`is_interrupt_resume_keyword`.
    """
    normalized = (text or "").strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _LOOP_CONTINUATION_PHRASE_PATTERNS)


def is_loop_control_signal(text: str | None) -> bool:
    """Return True when *text* is a deterministic loop-control signal."""
    return is_interrupt_resume_keyword(text) or is_loop_continuation_phrase(text)


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


def has_resumable_interrupted_goal(checkpoint: Any | None) -> bool:
    """Return True when the checkpoint holds an incomplete goal worth resuming.

    Covers ``status=running`` mid-flight recovery and the post-cancel case where
    loop metadata was marked ``idle`` while the StrangeLoop goal index entry is
    still ``running`` (interrupt touch). Also covers the ``interrupted`` goal
    index status written by ``mark_goal_interrupted`` on a user cancel, so that
    a retry/continue/resume re-activates that goal in place rather than
    starting a fresh goal.
    """
    if checkpoint is None:
        return False
    goal = _active_goal_record(checkpoint)
    if goal is None:
        return False
    status = getattr(goal, "status", None)
    return status in ("running", "cancelled", "interrupted")


def has_intra_loop_checkpoint_to_continue(checkpoint: Any | None) -> bool:
    """Return True when *this* loop's checkpoint holds work to resume or continue.

    Resume recovery is loop-scoped: an empty or missing ``goal_history`` (for
    example after a social-only first turn) is not a continuation target.
    Any prior goal record on this loop — incomplete or completed — is.
    """
    if checkpoint is None:
        return False
    history = getattr(checkpoint, "goal_history", None) or []
    return len(history) > 0


def should_bypass_chitchat_fast_path(
    checkpoint: Any | None,
    user_text: str | None,
) -> bool:
    """Return True when the chitchat fast-path must not short-circuit intake.

    Loop-control phrases bypass chitchat routing only when this loop's checkpoint
    has intra-loop work to continue. Otherwise keep the intake classify result
    (typically social). Other social messages on a running loop still use the
    chitchat path; the chitchat goal is finalized afterward via
    :func:`chitchat_may_finalize_checkpoint`.
    """
    return is_loop_control_signal(user_text) and has_intra_loop_checkpoint_to_continue(checkpoint)


def chitchat_may_finalize_checkpoint(checkpoint: Any | None) -> bool:
    """Return True when chitchat is allowed to finalize the active goal.

    Chitchat on a running loop must not mark goals completed — *except* when the
    active goal is the chitchat goal itself. The chitchat fast-path skips the
    FINALIZE station, so a fresh chitchat goal is left ``running`` on the
    checkpoint with ``duration_ms == 0`` (no EXECUTE/RECORD_PROGRESS ran). Such
    a goal is safe to finalize here.

    An in-flight *task* goal — one that already executed at least one wave — has
    ``duration_ms > 0`` (incremented only by ``record_iteration``, post-EXECUTE,
    a station the chitchat fast-path never reaches) and must NOT be finalized by
    chitchat; the normal graph FINALIZE owns its completion.
    """
    if checkpoint is None:
        return False
    status = getattr(checkpoint, "status", None)
    if status == "idle":
        # Goal already completed through the normal graph, or no goal to mutate.
        return not has_active_running_goal(checkpoint)
    if status == "running":
        goal = _active_goal_record(checkpoint)
        if goal is None:
            return False
        # Fresh chitchat goal (duration_ms == 0): safe to finalize. In-flight
        # task goal (duration_ms > 0): leave for the normal graph FINALIZE.
        return getattr(goal, "duration_ms", 0) == 0
    return False


__all__ = [
    "chitchat_may_finalize_checkpoint",
    "has_active_running_goal",
    "has_intra_loop_checkpoint_to_continue",
    "has_resumable_interrupted_goal",
    "is_loop_continuation_phrase",
    "is_loop_control_signal",
    "should_bypass_chitchat_fast_path",
]
