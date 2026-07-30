"""StrangeLoop stem station IDs (IG-663).

Canonical LangGraph node names for the flat Loop Graph. Legacy IDs remain
accepted via ``normalize_station`` for persisted clarification origins and
dual-read of older ledger ``phase`` tags.

Client/CLI wire deliverable phases (``goal_completion``, ``execute_step``) and
checkpoint ledger phases that soothe-sdk filters (``intent_classify``,
``plan_assess``, ``plan_generate``, ``plan_gap_analysis``) stay on their
legacy string values — writers must not rename those.
"""

from __future__ import annotations

from typing import Final

# --- Preprocess ---
INTAKE: Final = "intake"
ENTER_LOOP: Final = "enter_loop"

# --- Plan ---
GATHER_EVIDENCE: Final = "gather_evidence"
ANALYZE_GAPS: Final = "analyze_gaps"
ASSESS: Final = "assess"
GENERATE_PLAN: Final = "generate_plan"

# --- Execute ---
COMMIT_PLAN: Final = "commit_plan"
VALIDATE_PLAN: Final = "validate_plan"
EXECUTE: Final = "execute"
RECORD_PROGRESS: Final = "record_progress"
CHECK_LIMITS: Final = "check_limits"
BEGIN_ITERATION: Final = "begin_iteration"

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
        ASSESS,
        GENERATE_PLAN,
        ANALYZE_GAPS,
        INTAKE,
        PHASE_LEDGER_ASSESS,
        PHASE_LEDGER_GENERATE,
        PHASE_LEDGER_GAP,
        PHASE_LEDGER_INTAKE,
        "continuation",
    }
)

INTAKE_LEDGER_PHASES: frozenset[str] = frozenset({INTAKE, PHASE_LEDGER_INTAKE})

# Legacy LangGraph / origin ids → canonical station (resume + normalize).
LEGACY_TO_STATION: dict[str, str] = {
    "intent_classify": INTAKE,
    "init_or_resume": ENTER_LOOP,
    "bounded_evidence_gather": GATHER_EVIDENCE,
    "plan_gap_analysis": ANALYZE_GAPS,
    "plan_assess": ASSESS,
    "plan_generate": GENERATE_PLAN,
    "resolve_decision": COMMIT_PLAN,
    "validate_evidence_bindings": VALIDATE_PLAN,
    "record_iteration": RECORD_PROGRESS,
    "iteration_gate": CHECK_LIMITS,
    "iteration_start": BEGIN_ITERATION,
    "goal_completion": FINALIZE,
    "await_clarification": AWAIT_USER,
    "invoke_wired_subagent": DELEGATE,
    INTAKE: INTAKE,
    ENTER_LOOP: ENTER_LOOP,
    GATHER_EVIDENCE: GATHER_EVIDENCE,
    ANALYZE_GAPS: ANALYZE_GAPS,
    ASSESS: ASSESS,
    GENERATE_PLAN: GENERATE_PLAN,
    COMMIT_PLAN: COMMIT_PLAN,
    VALIDATE_PLAN: VALIDATE_PLAN,
    EXECUTE: EXECUTE,
    RECORD_PROGRESS: RECORD_PROGRESS,
    CHECK_LIMITS: CHECK_LIMITS,
    BEGIN_ITERATION: BEGIN_ITERATION,
    FINALIZE: FINALIZE,
    AWAIT_USER: AWAIT_USER,
    DELEGATE: DELEGATE,
}


def normalize_station(station_or_legacy: str | None) -> str | None:
    """Map a legacy or canonical station id to the canonical station id.

    Args:
        station_or_legacy: Graph node id, clarification origin, or internal phase.

    Returns:
        Canonical station id, or ``None`` when unknown / empty.
    """
    if not station_or_legacy:
        return None
    return LEGACY_TO_STATION.get(station_or_legacy)


__all__ = [
    "ANALYZE_GAPS",
    "ASSESS",
    "AWAIT_USER",
    "BEGIN_ITERATION",
    "CHECK_LIMITS",
    "COMMIT_PLAN",
    "DELEGATE",
    "ENTER_LOOP",
    "EXECUTE",
    "FINALIZE",
    "GATHER_EVIDENCE",
    "GENERATE_PLAN",
    "INTAKE",
    "INTAKE_LEDGER_PHASES",
    "LEGACY_TO_STATION",
    "PHASE_EXECUTE_STEP",
    "PHASE_GOAL_COMPLETION",
    "PHASE_GOAL_INTERRUPTED",
    "PHASE_LEDGER_ASSESS",
    "PHASE_LEDGER_GAP",
    "PHASE_LEDGER_GENERATE",
    "PHASE_LEDGER_INTAKE",
    "PLANNING_LEDGER_PHASES",
    "RECORD_PROGRESS",
    "VALIDATE_PLAN",
    "normalize_station",
]
