# IG-537: Context vs Loop Planning Consolidation (Phases A–D)

**Related**: RFC-624 (Context Engine), RFC-625 (AutopilotMonitor), RFC-626 (LoopState elimination)
**Created**: 2026-07-01
**Status**: Implemented

---

## Problem

Planning logic is split across `foundation/context/planning/` (CE state + heuristics)
and `foundation/loop/cognition/` (StrangeLoop LLM cognition). Legacy `PlanManager` /
`PlanDAG` removed. Goal decomposition wired through `GoalPlanningSubengine` and
`GoalDAGVerifier`. Scheduling unified via `GoalScheduler` delegation on CE.

---

## Scope

| Phase | Goal |
|-------|------|
| **A** | Delete `loop/planning/manager.py` and `dag.py`; migrate tests to `StepPlanManagerAdapter` |
| **B** | Implement `GoalPlanningSubengine` mutation helpers; wire `AutopilotMonitor` → `GoalDAGVerifier` |
| **C** | `ContextEngine.peek_ready_goals` / `claim_goal` delegate to `GoalScheduler` |
| **D** | Move StrangeLoop cognition to `loop/cognition/`; canonical `expand_dependency_satisfaction_ids` in `context/dag_utils.py` |

**Non-goals**: Merge `LLMPlanner` into ContextEngine; change prompt templates or graph topology.

---

## Phase A — Legacy step-plan state removal

- Delete `manager.py`, `dag.py`
- Tests import `CompletionStrategy` from `context/planning/models.py` only
- Equivalence tests target `StepPlanningSubengine` / `StepPlanManagerAdapter` only

## Phase B — Goal planning unification

- `GoalPlanningSubengine.apply_llm_subgoals()` — LLM decompose payloads → `GoalNode` children
- `GoalDAGVerifier.apply_health_report()` / `apply_post_completion()` — CE mutations via planning submodule
- `AutopilotMonitor` owns `GoalDAGVerifier`; intake + verification loops call verifier

## Phase C — Scheduling API

- `ContextEngine` scheduler methods delegate to `self._scheduler`
- `GoalScheduler.claim_goal` unchanged; CE retains callback firing

## Phase D — Package layout

```
foundation/context/dag_utils.py          # expand_dependency_satisfaction_ids (canonical)
foundation/context/planning/             # CE planning submodule
foundation/loop/cognition/             # LLMPlanner, PlanPhase, parsers, bypasses
```

The `foundation/loop/planning/` package is **removed** (no backward-compat shims).
All imports use `loop.cognition` or `context.dag_utils` directly.

---

## Verification

```bash
./scripts/verify_finally.sh
```
