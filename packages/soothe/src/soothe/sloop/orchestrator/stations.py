"""StrangeLoop stem station IDs and Loop Graph channel schema.

Canonical LangGraph node names for the flat Loop Graph. Legacy clarification
origin → canonical resume-station mapping lives in
``clarification.origins.CLARIFICATION_ORIGIN_RESUME_NODE``. Ledger dual-read
of older ``phase`` tags is handled by ``PLANNING_LEDGER_PHASES`` /
``INTAKE_LEDGER_PHASES``.

Client/CLI wire deliverable phases (``goal_completion``, ``execute_step``) and
checkpoint ledger phases that soothe-sdk filters (``intent_classify``,
``plan_assess``, ``plan_generate``, ``plan_gap_analysis``) stay on their
legacy string values — writers must not rename those.

Channel fields that conceptually hold ``IntakeLabel`` / ``ClarificationOrigin``
are typed as ``str`` here so this module stays import-safe from
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
# RFC-903 P3: ``validate_plan`` and ``begin_iteration`` were folded into
# ``commit_plan`` and ``check_limits`` respectively. Their station constants
# are removed; persisted checkpoints resume at the folding station.

# --- Complete ---
FINALIZE: Final = "finalize"

# --- Sidecars ---
AWAIT_USER: Final = "await_user"
DELEGATE: Final = "delegate"

# Wire-stable deliverable phases (soothe-sdk / CLI contract — do not rename).
PHASE_GOAL_COMPLETION: Final = "goal_completion"
PHASE_EXECUTE_STEP: Final = "execute_step"
PHASE_GOAL_INTERRUPTED: Final = "goal_interrupted"

# Checkpoint ledger phases filtered by soothe-sdk card_binder (do not rename writers).
PHASE_LEDGER_INTAKE: Final = "intent_classify"
PHASE_LEDGER_ASSESS: Final = "plan_assess"
PHASE_LEDGER_GENERATE: Final = "plan_generate"
PHASE_LEDGER_GAP: Final = "plan_gap_analysis"

# Dual-read: canonical station ids may appear in newer host-only rows; legacy
# ledger strings remain the writer contract for client-visible checkpoints.
PLANNING_LEDGER_PHASES: frozenset[str] = frozenset(
    {
        EVALUATE,
        GENERATE_PLAN,
        INTAKE,
        PHASE_LEDGER_ASSESS,
        PHASE_LEDGER_GENERATE,
        PHASE_LEDGER_GAP,
        PHASE_LEDGER_INTAKE,
        "assess",
        "analyze_gaps",
        "continuation",
    }
)

INTAKE_LEDGER_PHASES: frozenset[str] = frozenset({INTAKE, PHASE_LEDGER_INTAKE})

# --- Graph channel schema / route literals ---

IterationOutcome = Literal["continue", "completed", "fatal", "max_iterations", "deferred"]

PlanRoute = Literal["goal_done", "execute"]
IntentRoute = Literal["continue_loop", "fast_path", "wired_subagent"]
AssessRoute = Literal["continue_generate", "skip_generate"]
EvidenceGatherRoute = Literal[
    "evaluate",
    "plan_generate_skip_evaluate",
    "keep_plan",
]

PLAN_ROUTE_GOAL_DONE: PlanRoute = "goal_done"
PLAN_ROUTE_EXECUTE: PlanRoute = "execute"


class LoopGraphState(TypedDict, total=False):
    """Channels merged between Loop Graph nodes."""

    last_outcome: IterationOutcome | None
    plan_route: PlanRoute | None
    intent_route: IntentRoute | None
    assess_route: AssessRoute | None
    evidence_gather_route: EvidenceGatherRoute | None
    # RFC-630: 4-class intake label set by enter_loop, read by
    # route_after_preprocess for fresh trivial/simple inject vs gather_evidence.
    # Runtime values are IntakeLabel; typed str to avoid import cycles.
    intake_label: str | None
    # RFC-630: structural continuation overlay (continue_loop_mode + prior goals).
    # Kept for ledger/prompts; preprocess routing uses ``is_fresh_goal``.
    is_continuation: bool | None
    # True for first goal with no prior loop work. Fresh trivial/simple
    # inject → commit_plan; all mid-loop and fresh complex → gather_evidence.
    is_fresh_goal: bool | None
    # True when daemon created a new goal record (fresh loop or new goal
    # on idle loop). Used by route_after_preprocess routing guard to block chitchat
    # fast-path when structural admission contradicts social classification.
    new_goal_created: bool | None
    # derived intake fields for routing and downstream consumers.
    is_task: bool | None
    scope: str | None  # IntakeLabel at runtime
    has_deliverable: bool | None
    # Clarification relay (RFC-622): serialized to keep the channel JSON-safe.
    pending_clarification: dict[str, Any] | None
    pending_clarification_answer: dict[str, Any] | None
    last_clarification_origin: str | None  # ClarificationOrigin at runtime
    # Approve cleared planner wire; route_after_wired_subagent → generate_plan.
    planner_implement_handoff: bool | None
    # Set true when execute synthesizes a step result on the
    # clarification-resume path (no scratch decision / plan_result). Routing
    # skips record_progress in that case to avoid the "missing plan or
    # decision" fatal — the synthesized step has already emitted
    # step_completed and the next iteration will replan from the answer.
    resume_synth: bool | None
    # RFC-226 / terminal bootstrap: record_progress → finalize.
    after_record_route: Literal["finalize", "goal_completion", ""] | None


__all__ = [
    "AWAIT_USER",
    "AssessRoute",
    "CHECK_LIMITS",
    "COMMIT_PLAN",
    "DELEGATE",
    "ENTER_LOOP",
    "EVALUATE",
    "EXECUTE",
    "EvidenceGatherRoute",
    "FINALIZE",
    "GATHER_EVIDENCE",
    "GENERATE_PLAN",
    "INTAKE",
    "INTAKE_LEDGER_PHASES",
    "IntentRoute",
    "IterationOutcome",
    "LoopGraphState",
    "PHASE_EXECUTE_STEP",
    "PHASE_GOAL_COMPLETION",
    "PHASE_GOAL_INTERRUPTED",
    "PHASE_LEDGER_ASSESS",
    "PHASE_LEDGER_GAP",
    "PHASE_LEDGER_GENERATE",
    "PHASE_LEDGER_INTAKE",
    "PLANNING_LEDGER_PHASES",
    "PLAN_ROUTE_EXECUTE",
    "PLAN_ROUTE_GOAL_DONE",
    "PlanRoute",
    "RECORD_PROGRESS",
]
