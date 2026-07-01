"""Filters for user-facing loop cognition reason cards."""

from __future__ import annotations

_BOOTSTRAP_PLAN_REASONING: frozenset[str] = frozenset(
    {
        "Single execute wave from prior loop context and current goal.",
        "Single execute wave grounded on prior goal completion report.",
        "Loop-continuation bootstrap: initial planner call skipped.",
    }
)


def is_displayable_assessment_reasoning(text: str) -> bool:
    """True when assess text is real LLM output (not fresh-loop routing placeholders)."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    if stripped.startswith("Fresh-loop bypass:"):
        return False
    if stripped.startswith("Continue keyword:"):
        return False
    if stripped.startswith("Loop-continuation bootstrap:"):
        return False
    return True


def is_displayable_plan_reasoning(text: str) -> bool:
    """True when plan_reasoning is user-facing LLM output (not bootstrap placeholders)."""
    stripped = (text or "").strip()
    return bool(stripped) and stripped not in _BOOTSTRAP_PLAN_REASONING


def should_emit_loop_reason_event(
    *,
    assessment_reasoning: str,
    plan_reasoning: str,
) -> bool:
    """Whether to forward a loop reason event to clients.

    Assess cards use ``assessment_reasoning``; plan-generate cards use ``plan_reasoning``.
    """
    return bool(
        is_displayable_assessment_reasoning(assessment_reasoning)
        or is_displayable_plan_reasoning(plan_reasoning)
    )
