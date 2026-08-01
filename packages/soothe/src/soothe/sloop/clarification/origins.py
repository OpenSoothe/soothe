"""Clarification verification-stage origin constants (RFC-622, RFC-633, IG-663, IG-672).

Two different planning concepts must not be conflated:

* **StrangeLoop planning stage** — ``generate_plan`` / ``evaluate``
  (and execute-step ``ask_user`` via ``execute``). Persisted legacy origins
  ``assess`` / ``analyze_gaps`` / ``plan_assess`` / ``plan_gap_analysis`` resume
  to ``evaluate``.
* **Planner subagent review** — ``planner_subagent_review``: human Approve /
  Reject / More comments after the intake-only ``planner`` subagent writes a
  plan artifact. Not a StrangeLoop planning-stage station.
"""

from __future__ import annotations

from typing import Final, Literal

from soothe.sloop.orchestrator.stations import (
    DELEGATE,
    EVALUATE,
    EXECUTE,
    GENERATE_PLAN,
    normalize_station,
)

# --- StrangeLoop planning / execute stages ---------------------------------

ORIGIN_EXECUTE: Final = EXECUTE
"""CoreAgent execute-step ``ask_user`` clarification."""

ORIGIN_PLAN_GENERATE: Final = GENERATE_PLAN
"""StrangeLoop planning-stage ``generate_plan`` station clarification."""

ORIGIN_PLAN_EVALUATE: Final = EVALUATE
"""StrangeLoop planning-stage ``evaluate`` station clarification (IG-672)."""

# --- Planner subagent review (intake specialist; not StrangeLoop plan_*) -----

ORIGIN_PLANNER_SUBAGENT_REVIEW: Final = "planner_subagent_review"
"""Human review gate after the intake ``planner`` subagent (RFC-633)."""

PLANNER_WIRE_SUBAGENT: Final = "planner"
"""Intake-only wire id for the planner specialist (RFC-633 / RFC-618)."""

ClarificationOrigin = Literal[
    "execute",
    "generate_plan",
    "evaluate",
    "planner_subagent_review",
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
    }
)

# Persisted interrupt origins from pre-IG-663 / pre-IG-672 runs.
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
}

DEFAULT_FORCE_MANUAL_ORIGINS: tuple[str, ...] = (ORIGIN_PLANNER_SUBAGENT_REVIEW,)

PLANNER_SUBAGENT_REVIEW_INTERRUPT_PREFIX: Final = "planner-subagent-review:"


def resume_node_for_clarification_origin(origin: str | None) -> str | None:
    """Map a clarification origin to the StrangeLoop graph station that should resume.

    Accepts legacy origin ids (``plan_generate``, ``plan_assess``, …) and normalizes them.

    Returns:
        Canonical graph station name, or ``None`` when the origin is unknown.
    """
    if not origin or origin not in _ACCEPTED_CLARIFICATION_ORIGINS:
        return None
    if origin in CLARIFICATION_ORIGIN_RESUME_NODE:
        return CLARIFICATION_ORIGIN_RESUME_NODE[origin]
    return normalize_station(origin) or origin


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
    "PLANNER_SUBAGENT_REVIEW_INTERRUPT_PREFIX",
    "PLANNER_WIRE_SUBAGENT",
    "STRANGELOOP_PLANNING_ORIGINS",
    "resume_node_for_clarification_origin",
]
