# IG-689: Mirror Worker StepDAG onto Autopilot Goals for `top`

**Created**: 2026-08-05  
**Status**: Implemented  
**Related**: [RFC-228 §autopilot_top](../specs/RFC-228-autopilot-job-ipc.md),
[RFC-625](../specs/RFC-625-autopilot-monitor-context-engine-unification.md),
[IG-678 CE-1](IG-678-autopilot-ce-rails-production-readiness.md),
[IG-686](IG-686-autopilot-job-artifacts-and-top-polish.md),
[IG-688](IG-688-autopilot-top-interactive-keymaps.md)

---

## Executive Summary

`soothe autopilot top` with `steps=on` showed no STEP rows because planned
steps live on the **worker loop-scoped CE** while `top` reads the **daemon
Autopilot CE**. Mirror `plan_decision` / `step_completed` progress events from
the worker stream onto the dispatched Autopilot `GoalNode.steps`.

Dual CE remains intentional (IG-678 CE-1 / P1-4); this IG does not unify them.

---

## Problem

| Layer | Goal id | Steps | Visible in `top` |
|-------|---------|-------|------------------|
| Autopilot CE (job DAG) | dispatched id e.g. `252f732b` | empty | yes |
| StrangeLoop loop CE | shadow id e.g. `9ffa0533` | ingested plan | no |

Worker already forwards `progress.plan_decision` and `progress.step_completed`;
`_consume_worker_stream` ignored everything except `goal_completion`.

---

## Design

In `_consume_worker_stream`:

1. On `soothe.internal.autopilot.progress.plan_decision` → add/update
   `StepNode`s on Autopilot goal (same rules as `StepPlanningSubengine.ingest_plan`).
2. On `…progress.step_started` → `activate_step` (status ``active``).
3. On `…progress.step_completed` → `complete_step` / `fail_step` on Autopilot CE.
4. On completion, backfill any missing nodes from
   `context_contribution.plan_steps_executed`.
5. Persist Autopilot DAG after plan mirror (and at stream end as today).

No wire/CLI changes; `s` toggle already client-renders `node.steps`.

---

## Acceptance

- [x] Live `top` shows STEP lines under an active goal after `plan_decision`
- [x] Step status updates on `step_completed`
- [x] Unit test covers mirror; `./scripts/verify_finally.sh` green
- [x] No IG/RFC ids in user-visible strings

---

## Implementation notes

- `AutopilotService._consume_worker_stream` handles `progress.plan_decision` /
  `progress.step_completed` and backfills from contribution on completion.
- Worker `_build_contribution` / evidence grounding share
  `decision_step_actions()` (`steps` canonical, legacy `actions` fallback).
- `top` / `top_snapshot` order jobs newest-first by root `created_at`.
- Derive JOB/root GOAL ``active`` when children/loops are running (rail roots
  stay ``pending`` in CE).
- ``StepStatus.active`` + ``step_started`` mirror so in-flight STEPs are not
  stuck on ``pending``.
- CLI renders STEPs as a flat list (deps as ``←id``), not a nested step tree.
- ``mode=active`` filters terminal goals/loops only; StepDAG under kept goals
  stays intact so ``steps=on`` lists plan progress for live work.
- Removed unused AutopilotService ``_execution_semaphore`` /
  ``_assignment_lock`` (schedule uses ``max_loops`` / ``max_parallel_goals``;
  ``WorkerPool`` owns assignment locking).
