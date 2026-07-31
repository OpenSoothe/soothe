# IG-667: Plan Approve — Checkpoint Collision / Resume No-Op

**Created**: 2026-07-31  
**Status**: Implemented  
**Incident**: loop `924a` (`019fb639-e213-7c41-8f92-ebe92024924a`); regression
`ea23` (`019fb65b-d8da-7000-8e23-2a060ce3ea23`)

---

## Problem

Approving a planner review plan caused the TUI to show **Stream ended unexpectedly**.
The worker logged `Resuming pending clarification … 2 answer(s)` then exited in ~3ms
with `turn_completed=False` and no `await_clarification` / routing logs.

Postgres checkpoints showed:

1. Interrupt correctly saved (`__interrupt__` + `pending_clarification`).
2. ~1s later a deepagents `source=update` became HEAD on the **same** `thread_id`
   (loop UUID), orphaning the interrupt.
3. Approve wrote `__resume__` against that head → LangGraph no-op.
4. Intake planner nodes (`recon_model`, …) and `ProgressiveToolMiddleware` writes
   shared the StrangeLoop graph's checkpointer key space.

A first isolation attempt used ``checkpoint_ns=strange_loop``. That failed on
``ea23``: LangGraph treats non-empty ``checkpoint_ns`` as a subgraph path, so
``aget_state`` raised ``Subgraph strange_loop not found`` and approve fell back
to a normal invoke that re-parked without applying the answer.

## Fix

1. Scope StrangeLoop graph checkpoints under dedicated
   ``thread_id={loop_id}__strange_loop`` (empty ``checkpoint_ns``) so CoreAgent
   (``thread_id=loop_id``) cannot advance the review interrupt head.
2. Invoke intake-only specialists with an isolated ``thread_id`` (empty ns).
3. Harden clarification resume: require a live interrupt for ``Command(resume=…)``;
   if ``pending_clarification`` remains but the interrupt was orphaned, apply the
   answer via ``Command(update=…, goto=<resume station>)`` instead of a no-op.

No legacy key-space fallbacks — parked reviews from older key schemes are not
resumed; start a fresh loop after deploying.

## Acceptance

- [x] `build_loop_graph_invoke_config` sets StrangeLoop isolated `thread_id`
- [x] Intake-only runnable invoke uses isolated `thread_id` (no fake ns)
- [x] Resume with live interrupt still uses `Command(resume=…)`
- [x] Resume with orphaned pending uses `goto` recovery (not silent no-op)
- [x] Unit tests for config isolation + resume branching
- [x] `./scripts/verify_finally.sh` green for owned packages
