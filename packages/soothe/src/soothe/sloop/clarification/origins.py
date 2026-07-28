"""Clarification verification-stage origin constants (RFC-622, RFC-633).

Two different planning concepts must not be conflated:

* **StrangeLoop planning stage** — ``plan_generate`` / ``plan_assess`` /
  ``plan_gap_analysis`` (and execute-step ``ask_user`` via ``execute``).
* **Planner subagent review** — ``planner_subagent_review``: human Approve /
  Reject / More comments after the intake-only ``planner`` subagent writes a
  plan artifact. Not a StrangeLoop planning-stage node.
"""

from __future__ import annotations

from typing import Final, Literal

# --- StrangeLoop planning / execute stages ---------------------------------

ORIGIN_EXECUTE: Final = "execute"
"""CoreAgent execute-step ``ask_user`` clarification."""

ORIGIN_PLAN_GENERATE: Final = "plan_generate"
"""StrangeLoop planning-stage ``plan_generate`` node clarification."""

ORIGIN_PLAN_ASSESS: Final = "plan_assess"
"""StrangeLoop planning-stage ``plan_assess`` node clarification."""

ORIGIN_PLAN_GAP_ANALYSIS: Final = "plan_gap_analysis"
"""StrangeLoop planning-stage ``plan_gap_analysis`` node clarification."""

# --- Planner subagent review (intake specialist; not StrangeLoop plan_*) -----

ORIGIN_PLANNER_SUBAGENT_REVIEW: Final = "planner_subagent_review"
"""Human review gate after the intake ``planner`` subagent (RFC-633)."""

PLANNER_WIRE_SUBAGENT: Final = "planner"
"""Intake-only wire id for the planner specialist (RFC-633 / RFC-618)."""

ClarificationOrigin = Literal[
    "execute",
    "plan_generate",
    "plan_assess",
    "plan_gap_analysis",
    "planner_subagent_review",
]

CLARIFICATION_ORIGINS: frozenset[str] = frozenset(
    {
        ORIGIN_EXECUTE,
        ORIGIN_PLAN_GENERATE,
        ORIGIN_PLAN_ASSESS,
        ORIGIN_PLAN_GAP_ANALYSIS,
        ORIGIN_PLANNER_SUBAGENT_REVIEW,
    }
)

# StrangeLoop planning-stage origins (excludes execute + planner subagent review).
STRANGELOOP_PLANNING_ORIGINS: frozenset[str] = frozenset(
    {
        ORIGIN_PLAN_GENERATE,
        ORIGIN_PLAN_ASSESS,
        ORIGIN_PLAN_GAP_ANALYSIS,
    }
)

# Graph node to resume after clarification when it differs from the origin id.
CLARIFICATION_ORIGIN_RESUME_NODE: dict[str, str] = {
    ORIGIN_PLANNER_SUBAGENT_REVIEW: "invoke_wired_subagent",
}

DEFAULT_FORCE_MANUAL_ORIGINS: tuple[ClarificationOrigin, ...] = (ORIGIN_PLANNER_SUBAGENT_REVIEW,)

PLANNER_SUBAGENT_REVIEW_INTERRUPT_PREFIX: Final = "planner-subagent-review:"


def resume_node_for_clarification_origin(origin: str | None) -> str | None:
    """Map a clarification origin to the StrangeLoop graph node that should resume.

    Returns:
        Graph node name, or ``None`` when the origin is unknown.
    """
    if not origin or origin not in CLARIFICATION_ORIGINS:
        return None
    return CLARIFICATION_ORIGIN_RESUME_NODE.get(origin, origin)


__all__ = [
    "CLARIFICATION_ORIGINS",
    "CLARIFICATION_ORIGIN_RESUME_NODE",
    "ClarificationOrigin",
    "DEFAULT_FORCE_MANUAL_ORIGINS",
    "ORIGIN_EXECUTE",
    "ORIGIN_PLAN_ASSESS",
    "ORIGIN_PLAN_GAP_ANALYSIS",
    "ORIGIN_PLAN_GENERATE",
    "ORIGIN_PLANNER_SUBAGENT_REVIEW",
    "PLANNER_SUBAGENT_REVIEW_INTERRUPT_PREFIX",
    "PLANNER_WIRE_SUBAGENT",
    "STRANGELOOP_PLANNING_ORIGINS",
    "resume_node_for_clarification_origin",
]
