---
# Step↔Thread Surfacing — Design Draft

> Status: approved (design dialogue 2026-08-26). Routed to IG-764 for implementation. RFC-218 and RFC-504 updated to reflect the consolidated design.

## 1. Problem & scope
StrangeLoop (sloop) drives a goal via steps executed by CoreAgent threads. The step↔thread mapping, thread reuse, and interrupt-resume were underspecified and partly fictional:
- A parallel "anchor/branch" checkpoint tree (RFC-218) was built but **never written in production** — `save_failed_branch` had no caller, `iteration_end` anchors read the main thread (which holds no step checkpoints), and `checkpoint_anchors`/`failed_branches` tables were always empty.
- A `loop_tree`/`loop_prune` RPC + CLI surface rendered permanently-empty data.
- The loop registry carried a `thread_ids` history that degenerated to a single value (`current_thread_id == loop_id`).
- Docstrings claimed a `{loop_id}__step_<id>` thread grammar that never existed (live is random `{main}__{hex5}`).

**Scope**: the internal step↔thread mapping layer (id, thread reuse, interrupt resume) and checkpoint alignment — not a user-facing surfacing feature.
**Motivation**: fix alignment gaps, not documentation-only.

## 2. Current state (verified)
- Loop graph thread: `{loop_id}__strange_loop`. Intake delegate: `{loop_id}__intake__{wire}`. Execute step: `{main}__{hex5}` (random). Synthesis: `{parent}__synth_gc__{uuid}`. All with empty `checkpoint_ns` (isolation).
- Thread reuse (`thread_selection.py`): strict linear chain (single parent, single child) + interrupt resume; else new random thread.
- Interrupt resume: `GraphInterrupt` captured → `resume_thread_id`/`resume_step_id`/`resume_step_description` on `ClarificationCapture` → graph channels → rebuild decision.
- Parent checkpoint-coordinate stripping (IG-763): `strip_parent_checkpoint_coordinates` puts CoreAgent checkpoints at thread root so `Command(resume=...)` reaches interrupts.
- Message-ID dedup: `LoopContextProjector` filters ledger messages already checkpointed on the fork thread.
- CE working registry: `StepExecution.thread_id`, `goal_records.thread_id`, ledger `execute_step` rows carry `thread_id` + `iteration`.

## 3. Invariants (the design)
1. **Main thread id == loop_id** is the only loop-registry invariant. Drop `thread_ids` history.
2. **CE is the registry.** Step→thread mapping lives in CE (`StepExecution.thread_id`, `goal_records.thread_id`, ledger). No parallel anchor/branch tables.
3. **Thread ids are random & opaque.** Execute-step id is `{main}__{hex5}`; CE maps step→thread, not the id grammar. No deterministic step-id encoding.
4. **Checkpoints are reachable, not indexed.** Reach them via the shared checkpointer (`Command(resume=...)`, `aget_state`); do not store a `checkpoint_id` on `StepExecution`.

## 4. Changes
- **A. Retire anchor/branch machinery.** Delete `CheckpointAnchorManager` + its 7 methods across manager/sqlite/postgres backends + DDL (`checkpoint_anchors`, `failed_branches`) + `anchor_manager.py` + the `record_progress` iteration-end anchor capture.
- **B. Retire RPC/CLI surface.** Remove `loop_tree`/`loop_prune` RPCs (`router.py`, `LoopTreeParams`/`LoopPruneParams`, loop-status `failed_branches`/`checkpoint_anchors` fields) and the CLI `tree`/`prune` commands + `visualize_loop_tree`.
- **C. Collapse loop registry.** Remove `thread_ids` history in `loop_dispatcher`; fix `{loop_id}__step_<id>` docstrings; update tests.
- **D. Thread-id grammar ownership.** Move step/synth constructor functions into `orchestrator/checkpoint.py`; add `thread_kind()` classifier; document `step_thread_ids` as a runtime cache.
- **E. ResumeTicket.** Replace `resume_thread_id`/`resume_step_id`/`resume_step_description` with one `ResumeTicket` channel; update `ClarificationCapture`, `stations`, `execute`, `executor`.

## 5. Untouched
- Core interrupt-resume flow (capture → channel → rebuild) stays; only the container changes (E).
- Thread-reuse rules (`thread_selection.py`) stay; only constructor ownership moves (D).
- CE ledger / goal-record schema stays; only the parallel anchor/branch tables are removed (A).

## 6. Risks
- Anchor-manager references appear as kwargs in many test constructors (`anchor_manager=Mock()`) — must sweep all call sites.
- `client/python` (WS-client submodule) still calls `loop_tree`/`loop_prune` RPCs — excluded here; retire in the client repo as follow-up.
- ResumeTicket refactor must preserve the serialize→channel→rebuild data flow or interrupt-resume breaks.

## 7. Verification
- Grep for removed symbols → zero in soothe/daemon/cli.
- ruff clean; targeted pytest green.
- `./scripts/verify_finally.sh` green (authoritative).
---
