# IG-677: Autopilot Job↔Loop Index (Assignment-Scoped Loop IDs)

**Created**: 2026-08-04
**Status**: Implemented
**Related**: [RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md),
[RFC-228](../specs/RFC-228-autopilot-job-ipc.md),
[RFC-626](../specs/RFC-626-entity-model-state-consolidation.md),
[IG-RQJ-02](IG-RQJ-02-rail-trace-continuity-analysis.md),
[LoopRail draft](../drafts/2026-07-11-loop-rail-design.md)

---

## Executive Summary

Make autopilot’s **job → loops** relationship first-class and durable, while
keeping every loop’s runtime home under `~/.soothe/data/loops/{loop_id}/`.

A **job** remains the root `GoalNode` (`job_id` = root goal id). Each goal
**assignment** gets a unique, job-attributable `loop_id` (UUID suffix — no
fixed digit budget). `WorkerPool` slots stay capacity/reuse handles; logical
`loop_id` is no longer the recycled pool key.

---

## Problem

1. Recycled ids (`autopilot__wNNN`) let `data/loops/{loop_id}/` mix jobs when a
   slot is reused.
2. Job↔loop membership was only live `assigned_loop_id` + in-memory pool — no
   durable history.
3. Job-scoped artifacts cannot safely key off ephemeral worker ids.

---

## Design

### Identities

| Id | Format | Role |
|----|--------|------|
| `job_id` | 8-char hex (root goal id) | Stable job key |
| `loop_id` | `autopilot__{job_id}__{uuid4().hex}` | Assignment runtime home |
| `slot_id` | `autopilot__slot_{nnn}` | In-memory pool capacity key |
| `seq` | monotonic int in index only | Human ordering — **not** in `loop_id` |

### JobLoopIndex (durable)

Same persist backend as the goals snapshot (`AsyncPersistStore`):

- `autopilot:job_loops:{job_id}` — membership + history
- `autopilot:loop_owner:{loop_id}` — reverse map for GC/reconcile

CE DAG snapshot remains SoT for goals. The index is SoT for **job↔loop
membership**.

### WorkerPool

- Index slots by `slot_id`; sticky/LRU/prefer operate on slots.
- On each claim: allocate new `loop_id`, `create_runner(loop_id)`, bind to slot.
- `get_worker` / `mark_idle` / `release_worker` take the assignment `loop_id`.
- `is_autopilot_worker_loop_id`: `startswith("autopilot__")`.

### Disk

```text
~/.soothe/data/loops/autopilot__{job_id}__{uuid}/
```

Assignment runtime only under `loops/`. Job soft-state (e.g. rail trace) lives
under `data/jobs/{job_id}/` per IG-686. Job↔loop membership SoT remains the
persist index (not a directory tree of goals).

### Lifecycle hooks

| Event | Index action |
|-------|----------------|
| Root `submit_task` | Ensure empty job record |
| Dispatch / claim | `record_start` + reverse owner |
| Stream end / cancel | `record_end` (completed/failed/cancelled) |
| Daemon start | Mark stranded `active` → `interrupted` |

---

## Shipped

1. `JobLoopIndex` (+ in-memory fallback when no persist store)
2. Assignment-scoped `loop_id` allocation in `WorkerPool`
3. `AutopilotService` wiring: ensure job, record start/end, interrupt on start,
   `list_job_loops(job_id)`
4. Broader `is_autopilot_worker_loop_id` prefix check

---

## Acceptance

- [x] Assignment `loop_id` is `autopilot__{job_id}__{32-hex}` (unbounded)
- [x] Idle slot reuse keeps `slot_id`, allocates a **new** `loop_id` + runner
- [x] `JobLoopIndex` persists start/end and reverse owner keys
- [x] `is_autopilot_worker_loop_id` matches both legacy and new forms
- [x] Unit tests for pool rebinding + index store
- [x] `./scripts/verify_finally.sh` green

---

## Key files

| Area | Path |
|------|------|
| IG | `docs/impl/IG-677-autopilot-job-loop-index.md` |
| Index | `packages/soothe/src/soothe/autopilot/job_loop_index.py` |
| Pool | `packages/soothe/src/soothe/autopilot/worker_pool.py` |
| Service | `packages/soothe/src/soothe/autopilot/service.py` |
| Tests | `packages/soothe/tests/unit/core/autopilot/test_worker_pool.py`, `test_job_loop_index.py` |
