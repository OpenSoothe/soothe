"""StrangeLoop stem station IDs.

Canonical LangGraph node names for the flat Loop Graph. Legacy clarification
origin → canonical resume-station mapping lives in
``clarification.origins.CLARIFICATION_ORIGIN_RESUME_NODE``. Ledger dual-read
of older ``phase`` tags is handled by ``PLANNING_LEDGER_PHASES`` /
``INTAKE_LEDGER_PHASES``.

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
    "PHASE_EXECUTE_STEP",
    "PHASE_GOAL_COMPLETION",
    "PHASE_GOAL_INTERRUPTED",
    "PHASE_LEDGER_ASSESS",
    "PHASE_LEDGER_GAP",
    "PHASE_LEDGER_GENERATE",
    "PHASE_LEDGER_INTAKE",
    "PLANNING_LEDGER_PHASES",
    "RECORD_PROGRESS",
]
