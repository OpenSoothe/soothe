"""Clarification origin constants (RFC-622, RFC-904).

Live origins: ``execute`` (step ``ask_user``), ``plan_mode_review``
(plan draft approve/reject gate), ``rail_pause`` (host gate),
``tool_approval`` (deepagents HITL tool-action approval gate).
"""

from __future__ import annotations

from typing import Final, Literal

from soothe.sloop.orchestrator.stations import EXECUTE, PLAN_REVIEW

# --- Live StrangeLoop / host origins ----------------------------------------

ORIGIN_EXECUTE: Final = EXECUTE
"""CoreAgent execute-step ``ask_user`` clarification."""

ORIGIN_PLAN_MODE_REVIEW: Final = "plan_mode_review"
"""Human review gate after plan-mode draft (approve / reject / refine)."""

ORIGIN_RAIL_PAUSE: Final = "rail_pause"
"""LoopRail ``pause_for_user`` human gate (IG-737); host-side Veritas only."""

ORIGIN_TOOL_APPROVAL: Final = "tool_approval"
"""Deepagents ``HumanInTheLoopMiddleware`` tool-action approval gate.

The executor captures ``action_requests`` interrupts here instead of
auto-approving them. The request resumes at ``EXECUTE`` (the step
containing the tool call)."""

ClarificationOrigin = Literal[
    "execute",
    "plan_mode_review",
    "rail_pause",
    "tool_approval",
]

CLARIFICATION_ORIGINS: frozenset[str] = frozenset(
    {
        ORIGIN_EXECUTE,
        ORIGIN_PLAN_MODE_REVIEW,
        ORIGIN_RAIL_PAUSE,
        ORIGIN_TOOL_APPROVAL,
    }
)

CLARIFICATION_ORIGIN_RESUME_NODE: dict[str, str] = {
    ORIGIN_PLAN_MODE_REVIEW: PLAN_REVIEW,
    ORIGIN_EXECUTE: EXECUTE,
    ORIGIN_TOOL_APPROVAL: EXECUTE,  # resume the step that issued the tool call
}

DEFAULT_FORCE_MANUAL_ORIGINS: tuple[str, ...] = (ORIGIN_PLAN_MODE_REVIEW,)
"""Origins that never use veritas auto-answer, even in auto mode.

``plan_mode_review`` — the plan approve/reject/refine gate is a human call.

``tool_approval`` is intentionally NOT in this list: in auto mode the
``tool_approval`` origin is resolved by the multi-stage pipeline (§9b) —
deterministic deny → safety → allow stages handle most tool actions without
an LLM. Veritas's security-approver prompt (see
``build_veritas_system_prompt_for_origin``) handles the ambiguous tail.
Operators who want every tool action to require a human can re-add
``tool_approval`` to ``ClarificationConfig.force_manual_origins`` in config."""

PLAN_MODE_REVIEW_INTERRUPT_PREFIX: Final = "plan-mode-review:"
"""Interrupt prefix for plan-mode review clarifications."""


def resume_node_for_clarification_origin(origin: str | None) -> str | None:
    """Map a clarification origin to the StrangeLoop graph station that should resume.

    Returns:
        Canonical graph station name, or ``None`` when the origin is unknown
        or host-only (``rail_pause`` — not a StrangeLoop interrupt).
    """
    if not origin or origin not in CLARIFICATION_ORIGINS:
        return None
    if origin == ORIGIN_RAIL_PAUSE:
        return None
    return CLARIFICATION_ORIGIN_RESUME_NODE[origin]


__all__ = [
    "CLARIFICATION_ORIGINS",
    "CLARIFICATION_ORIGIN_RESUME_NODE",
    "ClarificationOrigin",
    "DEFAULT_FORCE_MANUAL_ORIGINS",
    "ORIGIN_EXECUTE",
    "ORIGIN_PLAN_MODE_REVIEW",
    "ORIGIN_RAIL_PAUSE",
    "ORIGIN_TOOL_APPROVAL",
    "PLAN_MODE_REVIEW_INTERRUPT_PREFIX",
    "resume_node_for_clarification_origin",
]
