"""StrangeLoop stem station IDs and Loop Graph channel schema.

Canonical LangGraph node names for the flat Loop Graph. Legacy clarification
origin → resume-station mapping lives in
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

# --- Execute ---
EXECUTE: Final = "execute"
RECORD_PROGRESS: Final = "record_progress"

# --- Decompose work-queue (RFC-904) ---
DISPATCH: Final = "dispatch"
RECONCILE: Final = "reconcile"
ROOT_EVAL: Final = "root_eval"

# --- Complete ---
FINALIZE: Final = "finalize"

# --- Sidecars ---
AWAIT_USER: Final = "await_user"
DELEGATE: Final = "delegate"

# Wire-stable deliverable phases (soothe-sdk / CLI contract — do not rename).
PHASE_GOAL_COMPLETION: Final = "goal_completion"
PHASE_EXECUTE_STEP: Final = "execute_step"
PHASE_GOAL_INTERRUPTED: Final = "goal_interrupted"
PHASE_PREAMBLE: Final = "preamble"

# Ledger dual-read: historical plan-spine / intake ``phase`` tags (not live nodes).
# Writers after RFC-904 use live station ids / wire phases only.
PLANNING_LEDGER_PHASES: frozenset[str] = frozenset(
    {
        "evaluate",
        "generate_plan",
        "intake",
        "plan_assess",
        "plan_generate",
        "plan_gap_analysis",
        "intent_classify",
        "assess",
        "analyze_gaps",
        "continuation",
    }
)

INTAKE_LEDGER_PHASES: frozenset[str] = frozenset({INTAKE, "intent_classify"})

# --- Graph channel schema / route literals ---

_IterationOutcome = Literal["continue", "completed", "fatal", "max_iterations", "deferred"]
_IntentRoute = Literal["continue_loop", "fast_path", "wired_subagent"]
_DispatchRoute = Literal["execute", "root_eval", "fatal"]
_ReconcileRoute = Literal["dispatch", "root_eval"]
_RootEvalRoute = Literal["finalize", "dispatch"]


class LoopGraphState(TypedDict, total=False):
    """Channels merged between Loop Graph nodes."""

    last_outcome: _IterationOutcome | None
    intent_route: _IntentRoute | None
    dispatch_route: _DispatchRoute | None
    reconcile_route: _ReconcileRoute | None
    root_eval_route: _RootEvalRoute | None
    intake_label: str | None  # IntakeLabel at runtime
    is_continuation: bool | None
    is_fresh_goal: bool | None
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
    "DELEGATE",
    "DISPATCH",
    "ENTER_LOOP",
    "EXECUTE",
    "FINALIZE",
    "INTAKE",
    "INTAKE_LEDGER_PHASES",
    "LoopGraphState",
    "PHASE_EXECUTE_STEP",
    "PHASE_GOAL_COMPLETION",
    "PHASE_GOAL_INTERRUPTED",
    "PHASE_PREAMBLE",
    "PLANNING_LEDGER_PHASES",
    "RECONCILE",
    "RECORD_PROGRESS",
    "ROOT_EVAL",
]
