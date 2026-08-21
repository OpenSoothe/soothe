"""Clarification verification-stage origin constants (RFC-622, RFC-904).

Live origins: ``execute`` (step ``ask_user``), ``plan_mode_review``
(plan draft approve/reject/comment gate), ``rail_pause`` (host gate).

Legacy plan-spine origins (``generate_plan``, ``evaluate``, and ledger
aliases) are still accepted for resume of persisted interrupts from
pre-RFC-904 runs; they resume at ``DISPATCH``.
"""

from __future__ import annotations

from typing import Final, Literal

from soothe.sloop.orchestrator.stations import DELEGATE, DISPATCH, EXECUTE

# --- Live StrangeLoop / host origins ----------------------------------------

ORIGIN_EXECUTE: Final = EXECUTE
"""CoreAgent execute-step ``ask_user`` clarification."""

ORIGIN_PLAN_MODE_REVIEW: Final = "plan_mode_review"
"""Human review gate after plan-mode draft (approve / reject / more comments)."""

ORIGIN_RAIL_PAUSE: Final = "rail_pause"
"""LoopRail ``pause_for_user`` human gate (IG-737); host-side Veritas only."""

# --- Legacy plan-spine origins (resume → DISPATCH; dual-read only) --------

ORIGIN_PLAN_GENERATE: Final = "generate_plan"
"""Legacy StrangeLoop ``generate_plan`` clarification origin."""

ORIGIN_PLAN_EVALUATE: Final = "evaluate"
"""Legacy StrangeLoop ``evaluate`` clarification origin."""

ClarificationOrigin = Literal[
    "execute",
    "plan_mode_review",
    "rail_pause",
    # legacy ids still accepted by normalize / resume
    "planner_subagent_review",
    "generate_plan",
    "evaluate",
    "assess",
    "analyze_gaps",
    "plan_generate",
    "plan_assess",
    "plan_gap_analysis",
]

CLARIFICATION_ORIGINS: frozenset[str] = frozenset(
    {
        ORIGIN_EXECUTE,
        ORIGIN_PLAN_MODE_REVIEW,
        ORIGIN_RAIL_PAUSE,
    }
)

# Persisted interrupt origins from pre-RFC-904 plan-spine runs.
_LEGACY_CLARIFICATION_ORIGINS: frozenset[str] = frozenset(
    {
        ORIGIN_PLAN_GENERATE,
        ORIGIN_PLAN_EVALUATE,
        "planner_subagent_review",
        "plan_generate",
        "plan_assess",
        "plan_gap_analysis",
        "assess",
        "analyze_gaps",
    }
)

_ACCEPTED_CLARIFICATION_ORIGINS: frozenset[str] = (
    CLARIFICATION_ORIGINS | _LEGACY_CLARIFICATION_ORIGINS
)

# Public alias for (de)serializers that must accept legacy interrupt origins.
ACCEPTED_CLARIFICATION_ORIGINS: frozenset[str] = _ACCEPTED_CLARIFICATION_ORIGINS

# All legacy plan-spine origins that resume at DISPATCH (incl. ledger aliases).
STRANGELOOP_PLANNING_ORIGINS: frozenset[str] = _LEGACY_CLARIFICATION_ORIGINS

CLARIFICATION_ORIGIN_RESUME_NODE: dict[str, str] = {
    ORIGIN_PLAN_MODE_REVIEW: DELEGATE,
    ORIGIN_EXECUTE: EXECUTE,
    # Plan-spine stations removed from the live graph; land on DISPATCH.
    ORIGIN_PLAN_GENERATE: DISPATCH,
    ORIGIN_PLAN_EVALUATE: DISPATCH,
    "planner_subagent_review": DELEGATE,  # legacy checkpoint resume
    "plan_generate": DISPATCH,
    "plan_assess": DISPATCH,
    "plan_gap_analysis": DISPATCH,
    "assess": DISPATCH,
    "analyze_gaps": DISPATCH,
}

DEFAULT_FORCE_MANUAL_ORIGINS: tuple[str, ...] = (ORIGIN_PLAN_MODE_REVIEW,)

PLAN_MODE_REVIEW_INTERRUPT_PREFIX: Final = "plan-mode-review:"
"""Interrupt prefix for plan-mode review clarifications."""


def resume_node_for_clarification_origin(origin: str | None) -> str | None:
    """Map a clarification origin to the StrangeLoop graph station that should resume.

    Accepts legacy origin ids (``generate_plan``, ``plan_assess``, …) and maps
    them to a live graph station (``DISPATCH`` for former plan-spine origins).

    Returns:
        Canonical graph station name, or ``None`` when the origin is unknown
        or host-only (``rail_pause`` — not a StrangeLoop interrupt).
    """
    if not origin or origin not in _ACCEPTED_CLARIFICATION_ORIGINS:
        return None
    if origin == ORIGIN_RAIL_PAUSE:
        return None
    return CLARIFICATION_ORIGIN_RESUME_NODE[origin]


__all__ = [
    "ACCEPTED_CLARIFICATION_ORIGINS",
    "CLARIFICATION_ORIGINS",
    "CLARIFICATION_ORIGIN_RESUME_NODE",
    "ClarificationOrigin",
    "DEFAULT_FORCE_MANUAL_ORIGINS",
    "ORIGIN_EXECUTE",
    "ORIGIN_PLAN_EVALUATE",
    "ORIGIN_PLAN_GENERATE",
    "ORIGIN_PLAN_MODE_REVIEW",
    "ORIGIN_RAIL_PAUSE",
    "PLAN_MODE_REVIEW_INTERRUPT_PREFIX",
    "STRANGELOOP_PLANNING_ORIGINS",
    "resume_node_for_clarification_origin",
]
