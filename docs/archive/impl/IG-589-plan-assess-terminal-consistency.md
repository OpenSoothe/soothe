# IG-589: Plan-Assess Terminal Consistency & Multi-Wave Goal Continuation

**RFCs**: RFC-220 (loop graph), RFC-604 (`StatusAssessment`), RFC-219 (goal completion), RFC-624 (completion policy), RFC-630 (intake / structured light-LLM), RFC-227 (prior-progress digest)
**Created**: 2026-07-13
**Status**: Implemented
**Related**: IG-557 (mid-goal assess accuracy), IG-555 (iter=0 prior-completion bias), IG-567 (heuristic-to-rules migration), IG-580 (ledger-direct structural gates), IG-549 (goal-boundary hardening)
**Motivating observation**: Loop `2a71` goals 4–7 (“fix failed cases / make all tests pass”) terminated after 1–2 execute waves while work remained. Assess returned `status=done` with `goal_progress=none`; gap analysis reported `at_goal` from plan-step satisfaction; multi-wave goals closed without outcome proof.

---

## Executive Summary

Premature goal termination came from **inconsistent structured assess signals** and **asymmetric routing gates** (`goal_progress=complete` guarded; `status=done` not). Fix uses structured light-LLM fields, typed structural gates, and declarative config — **no keyword/regex matching on user goal text**.

**Solution**:

1. Extend `StatusAssessment` with `terminal_readiness` and `gap_alignment`; normalize inconsistent `done`+low-progress pairs.
2. Unified `terminal_assess_may_complete()` gates before `goal_completion` routing (always on).
3. `StepResult.had_recoverable_tool_errors` for wave evidence (executor flag).
4. Replan-wave synthesis requires terminal assessment (always on).

No config toggles — behavior is framework default.

---

## Constraints (RFC-630)

**Prohibited**: keyword/regex lists on user goals, hard-coded goal-type classifiers, new banned-pattern lists for terminal routing.

**Allowed**: Pass 2 `multi_phase`, `StatusAssessment` / `PlanGapAnalysis` fields, `StepResult` flags, config thresholds, digest bucket comparison.

---

## Changes

| Area | File |
|------|------|
| Schema | `packages/soothe/src/soothe/foundation/sloop/state/schemas.py` |
| Terminal gates | `packages/soothe/src/soothe/foundation/sloop/cognition/plan_step_safety.py` |
| Routing | `packages/soothe/src/soothe/foundation/sloop/orchestrator/nodes/plan_assess.py` |
| Assess normalize | `packages/soothe/src/soothe/foundation/sloop/cognition/planner.py` |
| Step flag | `packages/soothe/src/soothe/foundation/sloop/engine/executor.py` |
| Completion | `packages/soothe/src/soothe/foundation/context/planning/completion.py` |
| Prompt | `plan_assess_instructions.xml` |
| Tests | `packages/soothe/tests/unit/core/loop/cognition/test_ig640_terminal_assess.py` |

---

## Verification

- `./scripts/verify_finally.sh`
- Unit: `test_ig640_terminal_assess.py` (loop 2a71 fixture patterns: `done`+`none`, gap `near`+open component, `multi_phase`)
