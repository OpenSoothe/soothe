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

from typing import TYPE_CHECKING, Any, Final, Literal, TypedDict

if TYPE_CHECKING:
    from soothe.sloop.clarification.capture import ResumeTicket

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
PLAN_REVIEW: Final = "plan_review"

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
    pending_clarification: dict[str, Any] | None
    pending_clarification_answer: dict[str, Any] | None
    last_clarification_origin: str | None  # ClarificationOrigin at runtime
    # Interrupt-resume identity (thread + step) for an ask_user /
    # tool_approval interrupt. Carried on a single channel (consolidates the
    # former three separate scalar fields). Read
    # by the resume path to re-enter the CoreAgent on the same thread
    # (Command(resume=...)) and re-emit step_started with the original step
    # identity+title the TUI already has a card for. Survives the AWAIT_USER
    # round-trip via graph checkpoint.
    resume_ticket: ResumeTicket | None
    after_record_route: Literal["finalize", "goal_completion", ""] | None
    interaction_mode: str | None  # "agent" | "ask" | "plan" — set by enter_loop
    # Plan-mode approve (Bug #3 fix): set True by ``handle_plan_mode_review_answer``
    # on approve so routers finalize the plan-mode goal (instead of grounding
    # onto its already-completed root). The finalize node reads the follow-on
    # exec signal from ctx.scratch and attaches it to the ``completed`` event;
    # the daemon enqueues the exec goal. Survives the AWAIT_USER round-trip.
    plan_approved_follow_on: bool | None
    # Plan-mode reject: set True to finalize the current goal without a
    # follow-on execution goal.
    plan_rejected_terminal: bool | None
    # Plan-mode Refine with comments: set True by ``handle_plan_mode_review_answer``
    # so ``node_plan_review`` (async) runs a refinement re-synthesis before
    # re-emitting the review. Ephemeral — consumed within the same node turn.
    plan_refinement_requested: bool | None


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
    "PLAN_REVIEW",
    "PHASE_GOAL_COMPLETION",
    "PHASE_GOAL_INTERRUPTED",
    "PHASE_PREAMBLE",
    "PLANNING_LEDGER_PHASES",
    "RECONCILE",
    "RECORD_PROGRESS",
    "ROOT_EVAL",
]
