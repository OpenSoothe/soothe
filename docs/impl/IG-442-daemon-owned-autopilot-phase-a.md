# IG-442: Daemon-Owned Autopilot — Phase A Scaffolding

**Status**: In Progress
**RFC**: [RFC-222 (revised 2026-05-28)](../specs/RFC-222-autopilot-goal-engine-architecture.md)
**Design**: [docs/drafts/2026-05-28-autopilot-loop-unification-design.md](../drafts/2026-05-28-autopilot-loop-unification-design.md)
**Created**: 2026-05-28
**Dependencies**: RFC-221 (LoopRunner protocol), RFC-200, RFC-204

---

## Purpose

Phase A of the RFC-222 (revised) migration plan: **additive scaffolding with no behavior change**. Adds the new types and modules that later phases will wire up, while leaving every existing code path untouched. Every existing test must still pass; no production code yet calls the new modules.

This is the safe, reversible foundation. Phase B (worker path wiring) and Phase C (daemon-side autopilot cutover) build on top.

---

## Scope

### In Scope

1. **Value types** — `GoalDispatchContextBundle`, `GoalDispatchContextContribution`, supporting summary types.
2. **Job contract extension** — `AutopilotJob` dataclass + optional `LoopRunRequest.autopilot_job` field.
3. **Context projection** — `ContextProjector` + `GoalDispatchContextStore`.
4. **Worker pool** — `WorkerPool` wrapping `LoopRunnerFactory` with sticky affinity.
5. **Workspace reservation** — `WorkspaceReservation` conflict gate.
6. **Unit tests** for every new module.

### Out of Scope (later phases)

- Wiring `SootheRunner.astream` to branch on `autopilot_job` (Phase B).
- Constructing daemon-side `AutopilotService` (Phase B).
- HTTP endpoint cutover (Phase C).
- Removing `_run_autonomous` multi-goal scheduling (Phase D).
- Stream chunk type `GoalCompletionChunk` — added when the worker path is wired (Phase B).

---

## Implementation Steps

### A1: Value types in `core/goal_engine/models.py`

Add Pydantic models with hard-cap validators:
- `PriorStepSummary` — id, description, status, duration
- `FileTouchSummary` — content_hash, last_op (read/write/edit/delete), goal_id_origin
- `ParentFinding` — goal_id_origin, summary text, relevance_score
- `Finding` — synthesized finding produced by current goal
- `ToolCallStats` — counts by name/status
- `StepSummary` — id, action, outcome
- `GoalDispatchContextBundle` — hydration input, bounded
- `GoalDispatchContextContribution` — worker output, bounded

Bound enforcement via `@model_validator(mode="after")` — bundle size capped via `context_projection.max_*` config fields (added to `AutonomousConfig` in this step).

**Tests**: `tests/unit/core/goal_engine/test_dispatch_context_models.py`

### A2: `AutopilotJob` + `LoopRunRequest.autopilot_job`

In `packages/soothe-sdk/src/soothe_sdk/protocols/runner.py`:
- Add `AutopilotJob` frozen dataclass.
- Add `autopilot_job: AutopilotJob | None = None` to `LoopRunRequest`. Default `None` means existing callers are unaffected.

**Tests**: `packages/soothe-sdk/tests/unit/protocols/test_runner_autopilot_job.py`

### A3: `ContextProjector` + `GoalDispatchContextStore`

New files:
- `packages/soothe/src/soothe/core/autopilot/context_projector.py` — `project(goal) → GoalDispatchContextBundle`. Heuristic relevance (recency + file overlap). Bounded merge.
- `packages/soothe/src/soothe/core/autopilot/context_store.py` — `put`/`get`/`delete_for_root`. Wraps `DurabilityProtocol`.

**Tests**:
- `tests/unit/core/autopilot/test_context_projector.py` (linear, diamond, fan-out, bound enforcement, soft-vs-hard dep weighting)
- `tests/unit/core/autopilot/test_context_store.py` (round-trip, eviction by root, age-based GC)

### A4: `WorkerPool` wrapping `LoopRunnerFactory`

`packages/soothe/src/soothe/core/autopilot/worker_pool.py`:
- `WorkerSlot` — wraps a `LoopRunnerProtocol`, tracks status (active/idle/error), `last_goal_ids` (recency cache), `current_goal_id`, `idle_since`.
- `WorkerPool` — `pick_worker(goal, prefer)` with sticky preference → idle fallback → spawn-under-cap. `_assignment_lock` for atomicity. `mark_idle`, `release`, capacity helpers.

Sticky scheduling rule: prefer the worker whose `last_goal_ids` contains any of `goal.depends_on`.

**Tests**: `tests/unit/core/autopilot/test_worker_pool.py` (sticky reuse, idle reuse, spawn under cap, concurrent pick atomicity).

### A5: `WorkspaceReservation`

`packages/soothe/src/soothe/core/autopilot/workspace_reservation.py`:
- `acquire(goal_id, workspace_path) → bool`
- `release(goal_id)`
- `conflicts_with_active(workspace_path) → str | None`

Conflict semantics: any prefix overlap counts (`/foo/bar` conflicts with `/foo/bar/baz`).

**Tests**: `tests/unit/core/autopilot/test_workspace_reservation.py` (overlap detection, nested paths, release cleanup, idempotent release).

---

## File Changes

### New Files

| Path | Purpose |
|------|---------|
| `packages/soothe/src/soothe/core/autopilot/context_projector.py` | A3 |
| `packages/soothe/src/soothe/core/autopilot/context_store.py` | A3 |
| `packages/soothe/src/soothe/core/autopilot/worker_pool.py` | A4 |
| `packages/soothe/src/soothe/core/autopilot/workspace_reservation.py` | A5 |
| `packages/soothe/tests/unit/core/goal_engine/test_dispatch_context_models.py` | A1 tests |
| `packages/soothe/tests/unit/core/autopilot/test_context_projector.py` | A3 tests |
| `packages/soothe/tests/unit/core/autopilot/test_context_store.py` | A3 tests |
| `packages/soothe/tests/unit/core/autopilot/test_worker_pool.py` | A4 tests |
| `packages/soothe/tests/unit/core/autopilot/test_workspace_reservation.py` | A5 tests |
| `packages/soothe-sdk/tests/unit/protocols/test_runner_autopilot_job.py` | A2 tests |

### Modified Files

| Path | Change |
|------|--------|
| `packages/soothe/src/soothe/core/goal_engine/models.py` | A1: add dispatch-context types |
| `packages/soothe-sdk/src/soothe_sdk/protocols/runner.py` | A2: extend `LoopRunRequest` |
| `packages/soothe/src/soothe/config/models.py` | A1: add `AutonomousConfig.context_projection` sub-block |
| `packages/soothe/src/soothe/core/autopilot/__init__.py` | Re-export new types/classes |
| `config/config.template.yml` + `config/config.dev.yml` | A1: document new config fields |

---

## Verification

```bash
./scripts/verify_finally.sh
```

Acceptance criteria:
- Format check passes
- Lint passes (zero errors)
- Full unit test suite passes — existing count + new tests for A1–A5
- No behavior change: no production code path executes the new modules yet

---

## Open Loose Ends (handled in later phases)

- **Phase B**: `SootheRunner.astream` branches on `autopilot_job`; daemon constructs `AutopilotService(enabled=False)`. New worker entry point `_run_single_autopilot_goal` added.
- **Phase C**: HTTP `/autopilot/submit` cutover; `ChannelInbox` consumer turns on; both old and new path coexist for a release.
- **Phase D** (destructive): delete `SootheRunner._autopilot_service`, delete `_run_autonomous` multi-goal scheduling, delete `_execute_goal_via_autopilot`. Migrate `soothe --autopilot` CLI to be a daemon client.

---

## Changelog

### 2026-05-28
- IG created for RFC-222 (revised) Phase A
- Listed 5 sub-steps with file paths + test locations
- Acceptance criteria specified
