"""In-flight plan reuse helpers (IG-671 structural keep + shared keep PlanResult).

Deterministic gates only — no keyword/content judgment on user text.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from soothe.sloop.state.schemas import PlanResult

if TYPE_CHECKING:
    from soothe.sloop.state.schemas import LoopState

logger = logging.getLogger(__name__)

_STUCK_ACTION_REPEAT_THRESHOLD = 3
_STUCK_ERROR_STEP_THRESHOLD = 3

_Progress = Literal["none", "low", "medium", "high", "complete"]
_Status = Literal["continue", "replan", "done"]

KEEP_NEXT_ACTION = "I'll continue with the remaining steps in the current plan."


def detect_stuck_loop(state: LoopState) -> str | None:
    """Detect repeated actions or consecutive step failures (IG-454)."""
    if len(state.action_history) >= _STUCK_ACTION_REPEAT_THRESHOLD:
        recent_actions = state.get_recent_actions(_STUCK_ACTION_REPEAT_THRESHOLD)
        if len(recent_actions) == _STUCK_ACTION_REPEAT_THRESHOLD:
            first_action = recent_actions[0]
            if all(action == first_action for action in recent_actions):
                return (
                    f"Repeated identical action {first_action[:50]} "
                    f"{_STUCK_ACTION_REPEAT_THRESHOLD} times"
                )

    if len(state.step_results) >= _STUCK_ERROR_STEP_THRESHOLD:
        recent_results = state.step_results[-_STUCK_ERROR_STEP_THRESHOLD:]
        if all(not r.success for r in recent_results):
            previews = [(r.error or "unknown")[:50] for r in recent_results[:2]]
            return f"Consecutive step failures: {', '.join(previews)}"

    return None


def remaining_plan_step_count(state: LoopState) -> int:
    """Count unfinished steps on the in-flight decision."""
    if state.current_decision is None:
        return 0
    return len(state.current_decision.steps) - len(state.dependency_completion_ids())


def _progress_from_state(state: LoopState) -> _Progress:
    digest = getattr(state, "prior_progress", None)
    if digest is not None:
        hint = getattr(digest, "derived_progress_hint", None)
        if hint in ("none", "low", "medium", "high", "complete"):
            return hint  # type: ignore[return-value]
    return "medium"


def structural_keep_block_reason(
    state: LoopState,
    *,
    enabled: bool,
    max_streak: int,
) -> str | None:
    """Return a reason string when structural keep must not run, else None."""
    if not enabled:
        return "disabled"
    if state.iteration <= 0:
        return "iter0"
    if not state.has_remaining_steps():
        return "no_remaining_steps"
    if state.current_decision is None:
        return "no_current_decision"
    if not state.step_results:
        return "no_step_results"
    if not state.step_results[-1].success:
        return "last_step_failed"
    if state.last_wave_hit_subagent_cap:
        return "subagent_cap"
    if state.last_wave_hit_tool_budget:
        return "tool_budget"
    stuck = detect_stuck_loop(state)
    if stuck:
        return f"stuck:{stuck[:80]}"
    streak = int(getattr(state, "structural_keep_streak", 0) or 0)
    if max_streak > 0 and streak >= max_streak:
        return f"streak_cap:{streak}>={max_streak}"
    return None


def build_keep_plan_result(
    state: LoopState,
    *,
    status: _Status = "continue",
    goal_progress: _Progress | None = None,
    require_goal_completion: bool = False,
) -> PlanResult:
    """Build a ``plan_action=keep`` PlanResult for assess / structural / generate reuse."""
    return PlanResult(
        status=status,
        goal_progress=goal_progress if goal_progress is not None else _progress_from_state(state),
        assessment_reasoning="",
        plan_reasoning="",
        plan_action="keep",
        decision=None,
        next_action=KEEP_NEXT_ACTION,
        require_goal_completion=require_goal_completion,
        full_output=None,
    )


def note_structural_keep(state: LoopState) -> int:
    """Increment and return the structural-keep streak."""
    streak = int(getattr(state, "structural_keep_streak", 0) or 0) + 1
    state.structural_keep_streak = streak
    logger.info(
        "[Plan] structural keep (%d step(s) remain, streak=%d)",
        remaining_plan_step_count(state),
        streak,
    )
    return streak


def reset_structural_keep_streak(state: LoopState) -> None:
    """Clear streak when a full plan-phase assess path runs."""
    if getattr(state, "structural_keep_streak", 0):
        state.structural_keep_streak = 0


__all__ = [
    "KEEP_NEXT_ACTION",
    "build_keep_plan_result",
    "detect_stuck_loop",
    "note_structural_keep",
    "remaining_plan_step_count",
    "reset_structural_keep_streak",
    "structural_keep_block_reason",
]
