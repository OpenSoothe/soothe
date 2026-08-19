"""Clarification verification-stage origin constants (RFC-622, RFC-633, RFC-904).

Two different planning concepts must not be conflated:

* **Legacy StrangeLoop planning stage** — origin ids ``generate_plan`` /
  ``evaluate`` (and execute-step ``ask_user`` via ``execute``). Persisted
  legacy origins ``assess`` / ``analyze_gaps`` / ``plan_assess`` /
  ``plan_gap_analysis`` are still accepted, but resume lands on ``DISPATCH``.
* **Planner subagent review** — ``planner_subagent_review``: human Approve /
  Reject / More comments after the intake-only ``planner`` subagent writes a
  plan artifact. Not a StrangeLoop planning-stage station.
"""

from __future__ import annotations

from typing import Final, Literal

from soothe.sloop.orchestrator.stations import DELEGATE, DISPATCH, EXECUTE

# --- StrangeLoop planning / execute stages ---------------------------------

ORIGIN_EXECUTE: Final = EXECUTE
"""CoreAgent execute-step ``ask_user`` clarification."""

ORIGIN_PLAN_GENERATE: Final = "generate_plan"
"""Legacy StrangeLoop ``generate_plan`` clarification origin (resume → DISPATCH)."""

ORIGIN_PLAN_EVALUATE: Final = "evaluate"
"""Legacy StrangeLoop ``evaluate`` clarification origin (resume → DISPATCH)."""

# --- Planner subagent review (intake specialist; not StrangeLoop plan_*) -----

ORIGIN_PLANNER_SUBAGENT_REVIEW: Final = "planner_subagent_review"
"""Human review gate after the intake ``planner`` subagent (RFC-633)."""

ORIGIN_RAIL_PAUSE: Final = "rail_pause"
"""LoopRail ``pause_for_user`` human gate (IG-737); host-side Veritas only."""

PLANNER_WIRE_SUBAGENT: Final = "planner"
"""Intake-only wire id for the planner specialist (RFC-633 / RFC-618)."""

ClarificationOrigin = Literal[
    "execute",
    "generate_plan",
    "evaluate",
    "planner_subagent_review",
    "rail_pause",
    # legacy ids still accepted by normalize / resume
    "assess",
    "analyze_gaps",
    "plan_generate",
    "plan_assess",
    "plan_gap_analysis",
]

CLARIFICATION_ORIGINS: frozenset[str] = frozenset(
    {
        ORIGIN_EXECUTE,
        ORIGIN_PLAN_GENERATE,
        ORIGIN_PLAN_EVALUATE,
        ORIGIN_PLANNER_SUBAGENT_REVIEW,
        ORIGIN_RAIL_PAUSE,
    }
)

# Persisted interrupt origins from pre-/ pre-runs.
_LEGACY_CLARIFICATION_ORIGINS: frozenset[str] = frozenset(
    {
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

STRANGELOOP_PLANNING_ORIGINS: frozenset[str] = frozenset(
    {
        ORIGIN_PLAN_GENERATE,
        ORIGIN_PLAN_EVALUATE,
    }
)

CLARIFICATION_ORIGIN_RESUME_NODE: dict[str, str] = {
    ORIGIN_PLANNER_SUBAGENT_REVIEW: DELEGATE,
    ORIGIN_EXECUTE: EXECUTE,
    # Plan-spine stations removed from the live graph; land on DISPATCH.
    ORIGIN_PLAN_GENERATE: DISPATCH,
    ORIGIN_PLAN_EVALUATE: DISPATCH,
    "plan_generate": DISPATCH,
    "plan_assess": DISPATCH,
    "plan_gap_analysis": DISPATCH,
    "assess": DISPATCH,
    "analyze_gaps": DISPATCH,
}

DEFAULT_FORCE_MANUAL_ORIGINS: tuple[str, ...] = (ORIGIN_PLANNER_SUBAGENT_REVIEW,)

PLANNER_SUBAGENT_REVIEW_INTERRUPT_PREFIX: Final = "planner-subagent-review:"


def resume_node_for_clarification_origin(origin: str | None) -> str | None:
    """Map a clarification origin to the StrangeLoop graph station that should resume.

    Accepts legacy origin ids (``plan_generate``, ``plan_assess``, …) and maps
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
    "ORIGIN_PLANNER_SUBAGENT_REVIEW",
    "ORIGIN_RAIL_PAUSE",
    "PLANNER_SUBAGENT_REVIEW_INTERRUPT_PREFIX",
    "PLANNER_WIRE_SUBAGENT",
    "STRANGELOOP_PLANNING_ORIGINS",
    "resume_node_for_clarification_origin",
]
