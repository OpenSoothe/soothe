"""StrangeLoop stem station IDs and Loop Graph channel schema.

Canonical LangGraph node names for the flat Loop Graph. Legacy clarification
origin → canonical resume-station mapping lives in
``clarification.origins.CLARIFICATION_ORIGIN_RESUME_NODE``. Ledger dual-read of
older ``phase`` tags is handled by ``PLANNING_LEDGER_PHASES`` /
``INTAKE_LEDGER_PHASES``.

Wire deliverable phases (``goal_completion``, ``execute_step``) and soothe-sdk
ledger filter strings must stay stable — writers must not rename those values.

Channel fields that conceptually hold ``IntakeLabel`` / ``ClarificationOrigin``
are typed as ``str`` so this module stays import-safe from
``clarification.origins`` (no cycle through ``intention``).
"""

from __future__ import annotations

from typing import Any, Final, Literal, TypedDict

# --- Preprocess ---
INTAKE: Final = "intake"
ENTER_LOOP: Final = "enter_loop"

# --- Plan ---
GATHER_EVIDENCE: Final = "gather_evidence"
EVALUATE: Final = "evaluate"
GENERATE_PLAN: Final = "generate_plan"

# --- Execute ---
COMMIT_PLAN: Final = "commit_plan"
EXECUTE: Final = "execute"
RECORD_PROGRESS: Final = "record_progress"
CHECK_LIMITS: Final = "check_limits"

# --- Complete ---
FINALIZE: Final = "finalize"

# --- Sidecars ---
AWAIT_USER: Final = "await_user"
DELEGATE: Final = "delegate"

# Wire-stable deliverable phases (soothe-sdk / CLI contract — do not rename).
PHASE_GOAL_COMPLETION: Final = "goal_completion"
PHASE_EXECUTE_STEP: Final = "execute_step"
PHASE_GOAL_INTERRUPTED: Final = "goal_interrupted"

# Checkpoint ledger phases filtered by soothe-sdk card_binder (do not rename).
_PHASE_LEDGER_INTAKE: Final = "intent_classify"
_PHASE_LEDGER_ASSESS: Final = "plan_assess"
_PHASE_LEDGER_GENERATE: Final = "plan_generate"
_PHASE_LEDGER_GAP: Final = "plan_gap_analysis"

PLANNING_LEDGER_PHASES: frozenset[str] = frozenset(
    {
        EVALUATE,
        GENERATE_PLAN,
        INTAKE,
        _PHASE_LEDGER_ASSESS,
        _PHASE_LEDGER_GENERATE,
        _PHASE_LEDGER_GAP,
        _PHASE_LEDGER_INTAKE,
        "assess",
        "analyze_gaps",
        "continuation",
    }
)

INTAKE_LEDGER_PHASES: frozenset[str] = frozenset({INTAKE, _PHASE_LEDGER_INTAKE})

# --- Graph channel schema / route literals ---

_IterationOutcome = Literal["continue", "completed", "fatal", "max_iterations", "deferred"]
PlanRoute = Literal["goal_done", "execute"]
_IntentRoute = Literal["continue_loop", "fast_path", "wired_subagent"]
_AssessRoute = Literal["continue_generate", "skip_generate"]
_EvidenceGatherRoute = Literal[
    "evaluate",
    "plan_generate_skip_evaluate",
    "keep_plan",
]

PLAN_ROUTE_GOAL_DONE: PlanRoute = "goal_done"
PLAN_ROUTE_EXECUTE: PlanRoute = "execute"


class LoopGraphState(TypedDict, total=False):
    """Channels merged between Loop Graph nodes."""

    last_outcome: _IterationOutcome | None
    plan_route: PlanRoute | None
    intent_route: _IntentRoute | None
    assess_route: _AssessRoute | None
    evidence_gather_route: _EvidenceGatherRoute | None
    intake_label: str | None  # IntakeLabel at runtime
    is_continuation: bool | None
    is_fresh_goal: bool | None
    new_goal_created: bool | None
    is_task: bool | None
    scope: str | None  # IntakeLabel at runtime
    has_deliverable: bool | None
    pending_clarification: dict[str, Any] | None
    pending_clarification_answer: dict[str, Any] | None
    last_clarification_origin: str | None  # ClarificationOrigin at runtime
    planner_implement_handoff: bool | None
    resume_synth: bool | None
    after_record_route: Literal["finalize", "goal_completion", ""] | None


__all__ = [
    "AWAIT_USER",
    "CHECK_LIMITS",
    "COMMIT_PLAN",
    "DELEGATE",
    "ENTER_LOOP",
    "EVALUATE",
    "EXECUTE",
    "FINALIZE",
    "GATHER_EVIDENCE",
    "GENERATE_PLAN",
    "INTAKE",
    "INTAKE_LEDGER_PHASES",
    "LoopGraphState",
    "PHASE_EXECUTE_STEP",
    "PHASE_GOAL_COMPLETION",
    "PHASE_GOAL_INTERRUPTED",
    "PLANNING_LEDGER_PHASES",
    "PLAN_ROUTE_EXECUTE",
    "PLAN_ROUTE_GOAL_DONE",
    "PlanRoute",
    "RECORD_PROGRESS",
]
