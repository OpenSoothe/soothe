"""Continuation turn routing helpers (RFC-226, RFC-630 coordination)."""

from __future__ import annotations

import re

from soothe.foundation.sloop.state.schemas import StatusAssessment

_MULTI_STEP_PATTERN = re.compile(
    r"(?:\band then\b|\bthen\b.{0,40}\b(?:run|start|execute|build|deploy|test)\b|"
    r"\d+\.\s|\bfirst\b.+\bsecond\b|;\s*\w)",
    re.IGNORECASE,
)


def goal_has_explicit_multi_step_markers(goal: str) -> bool:
    """True when raw goal text implies multiple ordered execution phases."""
    from soothe.foundation.sloop.utils.continue_keyword import is_continue_keyword

    text = (goal or "").strip()
    if not text or is_continue_keyword(text):
        return False
    return bool(_MULTI_STEP_PATTERN.search(text))


def continuation_forced_plan_generate_assessment() -> StatusAssessment:
    """Synthetic assessment when intake complexity forbids bootstrap."""
    return StatusAssessment(
        status="continue",
        goal_progress="none",
        assessment_reasoning="",
        require_goal_completion=False,
    )


def bootstrap_terminal_after_execute(
    *,
    raw_user_goal: str,
    goal_description: str | None,
) -> bool:
    """Whether a bootstrap plan should skip iter=1 replan after execute.

    Chat-like and ``continue`` keyword goals remain terminal. Tool-heavy goals
    with refined intent descriptions or explicit multi-step markers allow replan.
    """
    from soothe.foundation.sloop.utils.continue_keyword import is_continue_keyword

    if is_continue_keyword(raw_user_goal):
        return True
    desc = (goal_description or "").strip()
    raw = raw_user_goal.strip()
    if desc and desc != raw:
        return False
    if goal_has_explicit_multi_step_markers(raw):
        return False
    return True


__all__ = [
    "bootstrap_terminal_after_execute",
    "continuation_forced_plan_generate_assessment",
    "goal_has_explicit_multi_step_markers",
]
