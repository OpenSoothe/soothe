"""Filters for user-facing loop cognition reason cards."""

from __future__ import annotations

from soothe.sloop.orchestrator.continuation_routing import FRESH_LOOP_BYPASS_PREFIX


def is_displayable_assessment_reasoning(text: str) -> bool:
    """True when assess text is real LLM output (not fresh-loop routing placeholders)."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    if stripped.startswith(FRESH_LOOP_BYPASS_PREFIX):
        return False
    if stripped.startswith("Continue keyword:"):
        return False
    if stripped.startswith("Loop-continuation bootstrap:"):
        return False
    return True


def should_emit_loop_reason_event(*, assessment_reasoning: str) -> bool:
    """Whether to forward a loop reason event to clients.

    Plan-generate no longer emits user-facing plan reasoning; assess cards use
    ``assessment_reasoning`` only.
    """
    return is_displayable_assessment_reasoning(assessment_reasoning)
