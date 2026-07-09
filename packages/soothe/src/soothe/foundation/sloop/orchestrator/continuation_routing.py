"""Continuation turn routing helpers (RFC-226, RFC-630 coordination)."""

from __future__ import annotations

from soothe.foundation.sloop.utils.continue_keyword import is_continue_keyword


def continuation_forced_plan_generate_assessment():
    """Synthetic assessment when intake complexity forbids bootstrap."""
    from soothe.foundation.sloop.state.schemas import StatusAssessment

    return StatusAssessment(
        status="continue",
        goal_progress="none",
        assessment_reasoning="",
        require_goal_completion=False,
    )


def bootstrap_terminal_after_execute(
    *,
    raw_user_goal: str,
    multi_phase: bool | None = None,
) -> bool:
    """Whether a bootstrap plan should skip iter=1 replan after execute.

    Chat-like and ``continue`` keyword goals remain terminal. Pass 2 ``multi_phase``
    allows replan after the first execute wave.
    """
    if is_continue_keyword(raw_user_goal):
        return True
    if multi_phase:
        return False
    return True


__all__ = [
    "bootstrap_terminal_after_execute",
    "continuation_forced_plan_generate_assessment",
]
