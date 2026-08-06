# IG-670: Daemon Auto-Resume of Interrupted Goals

**Created**: 2026-07-31
**Status**: Implemented
**Related**: [RFC-225](../specs/RFC-225-loop-continuity-and-goal-record-enrichment.md),
[RFC-223](../specs/RFC-223-thread-inheritance-checkpoint-forking.md),
[RFC-306](../specs/RFC-306-durability-protocol-architecture.md),
[RFC-622](../specs/RFC-622-coreagent-clarification-relay.md),
[RFC-626](../specs/RFC-626-entity-model-state-consolidation.md),
[RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md)

---

## Executive Summary

Daemon startup classifies incomplete StrangeLoop goals (`status=running`) and,
when `agent.loop.checkpoint.auto_resume_on_start` is true, re-enters StrangeLoop
on the same `loop_id` via internal `resume_interrupted` admission so
`recovery_valid_resume` reuses existing threads, CE state, and checkpoints.

---

## Shipped behavior

1. **Config** (`LoopCheckpointConfig`): `auto_resume_on_start` (wired),
   `auto_resume_max_loops`, `auto_resume_max_age_hours`,
   `auto_resume_clarifications` (`skip` | `reannounce`).
2. **Eligibility** (`soothe_daemon.runtime.auto_resume`): cancel-by-age,
   autopilot exclusion, checkpoint resumability, clarification policy,
   concurrency cap.
3. **Admission**: `LoopRunRequest.resume_interrupted` → runner → StrangeLoop
   skips Pass 1 and does not cancel the in-flight goal (unlike bare
   `continue`/`resume` keywords).
4. **Reconciliation**: `_auto_resume_protected_loop_ids` exempt from
   `running → idle` demotion while enqueue settles.
5. **Default**: `auto_resume_on_start: false` — detect/log only; manual
   `soothe loop continue`.

Clarification pending peek at startup is best-effort (`None` = treat as not
pending); parked clarifications that are resumed re-emit at `await_clarification`.

## Key files

| Area | Path |
|------|------|
| Classifier / orchestrator | `packages/soothe-daemon/src/soothe_daemon/runtime/auto_resume.py` |
| Daemon hook | `packages/soothe-daemon/src/soothe_daemon/server/core.py` |
| Admission flag | `packages/soothe/src/soothe/protocols/runner.py` (`resume_interrupted`) |
| StrangeLoop | `packages/soothe/src/soothe/sloop/engine/strange_loop.py` |
| Config | `packages/soothe/src/soothe/config/models.py`, `config/soothe.template.yml` |

## Acceptance

- [x] With `auto_resume_on_start: true`, eligible incomplete solo loops are
      enqueued with `resume_interrupted=True` on the same `loop_id`
- [x] With `auto_resume_on_start: false` (default), no enqueue (manual continue)
- [x] Age cancel wins over resume; Autopilot worker loops skipped
- [x] Clarification `skip` / `reannounce` honored in classifier
- [x] Status reconciliation exempts protected auto-resume loop ids
- [x] Config templates synced; unit tests for classifier + enqueue gate
