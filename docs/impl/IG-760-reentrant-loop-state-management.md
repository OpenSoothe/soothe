# IG-760: Reentrant Loop State Management

**Created**: 2026-08-24
**Status**: Implemented
**Related**: RFC-622 (clarification relay), RFC-624 (CE persistence), RFC-633 (planner review), IG-682 (composer plan mode), IG-749 (clarification relay hardening)

## Problem

Loop state was coupled to runtime worker lifecycles. When a worker process
exited (crash, daemon restart, or user disconnect during a long-running
LLM call), in-flight state was lost:

- Plan-mode review refinement comments (`plan_review_comments`) lived only on
  `ctx.scratch` (in-memory `LoopPhaseScratch`), not persisted.
- Clarification resume couldn't find CE goals parked in
  `awaiting_clarification` status — only `active` goals were matched.
- A cancel during refinement synthesis changed the goal to `interrupted`,
  and the user's reconnect input was treated as a new goal instead of a
  reject-with-comments answer.

Users experienced "stuck" loops: Reject → no visible activity → user sends
new input → old refinement killed → loop starts a fresh goal, losing the
plan-mode review context entirely.

## Goal

Loop state must be **independent of runtime workers** — pauseable and
resumable across arbitrary time intervals (seconds, hours, days). A worker
exit during any phase (exploration, plan synthesis, refinement, AWAIT_USER)
must not lose state. The user's next input must correctly resume the loop
from where it parked, whether it was awaiting plan approval, mid-refinement,
or mid-execution.

## Design: Three-Layer Persistent State

No new state management layer was needed. The existing three-layer
architecture already provides worker-independent persistence. The fixes
closed specific gaps in how state flows between layers.

### Layer 1: LangGraph Checkpointer (graph channel values)

**Storage**: SQLite (`checkpoints.db`) or PostgreSQL (`soothe_checkpoints` db).
**Persistence**: `AsyncSqliteSaver` / `AsyncPostgresSaver` — no in-memory
fallback. Data committed to disk before the worker process exits.

**Channels persisted** (in `LoopGraphState`):
- `pending_clarification` — dict with `origin_node`, questions, and for
  plan-mode review: `plan_path`, `plan_markdown`, `plan_review_comments`
- `pending_clarification_answer` — the answer to resume with
- `last_clarification_origin` — routes resume to the correct graph node
- `plan_approved_follow_on` — survives the AWAIT_USER round-trip for approve
- `plan_refinement_requested` — ephemeral, consumed same turn

**Thread isolation**: StrangeLoop graph uses
`thread_id = f"{loop_id}__strange_loop"`, separate from CoreAgent which uses
`thread_id = loop_id`.

**Resume mechanism**: `compiled.aget_state(config)` reads the persisted
snapshot. `snapshot_has_resumable_interrupt()` checks if the LangGraph
interrupt is still live → `Command(resume=...)` resumes it. If the interrupt
is gone but `pending_clarification` is in channel values →
`Command(update=..., goto=...)` routes to the origin node.

### Layer 2: Context Engine (CE) — goal DAG + ledger

**Storage**: SQLite (`context.db`, tables `ce_dag` + `ce_ledger`) or
PostgreSQL.

**What persists**:
- `GoalNode`: `status` (active, pending, awaiting_clarification, suspended,
  completed, failed, cancelled), `description` (the goal text), and
  `pending_clarification` dict (stored on the GoalNode itself).
- Full message ledger: `execute_step` messages, `goal_completion` pairs,
  `goal_interrupted` markers.
- Step DAG: decomposition proposals, step IDs, wave assignments.

**Lifecycle**: Per-loop, spanning all goals. `ce.load()` restores the full
DAG + ledger on every `run_with_progress` call. `ce.save()` persists before
the graph parks on `await_user`.

**Resume**: `resolve_clarification_resume_ce_goal()` finds a goal with
`status in {"active", "awaiting_clarification"}`. When the goal is in
`awaiting_clarification`, `answer_clarification()` transitions it to
`pending`, then `activate_goal()` re-activates it.

### Layer 3: Plan Artifacts (disk)

**Storage**: `{workspace}/.soothe/plans/{timestamp}-{slug}.md` on disk.
YAML frontmatter (status, goal_id, loop_id, created_at) + plan body markdown.

**Fallback**: When `plan_markdown` is missing from the graph channel (e.g.,
checkpoint corruption or schema migration), `hydrate_scratch_from_pending`
reads the file at `plan_path` from disk.

### Layer 4: LoopPhaseScratch (in-memory, partially recovered)

**Storage**: In-memory `dataclass` on `LoopRuntimeContext`. Not serialized by
LangGraph (by design — payloads reference rich non-primitive models).

**Fields**: `plan_result`, `decision`, `step_results`, `plan_draft_path`,
`plan_draft_markdown`, `plan_review_comments`, `follow_on_exec`.

**Recovery**: `hydrate_scratch_from_pending()` reads `plan_path`,
`plan_markdown`, and `plan_review_comments` from the `pending_clarification`
channel values (Layer 1) back onto a fresh scratch. Disk fallback for
`plan_markdown` via Layer 3. Other fields are rebuilt during the resumed
graph execution or consumed one-shot (e.g., `follow_on_exec` is consumed by
finalize and doesn't need persistence).

## Fixes Applied

### Fix 1: Persist `plan_review_comments` in pending channel

`build_plan_mode_review_pending` now stores `plan_review_comments` into the
`pending_clarification` dict (alongside `plan_path` and `plan_markdown`).
`hydrate_scratch_from_pending` restores it on resume. The LangGraph
checkpointer serializes the entire channel, so comments survive worker
crash/restart.

**Before**: worker crash during refinement synthesis → `plan_review_comments`
lost → `_refine_plan` reads empty → degrades to re-emitting the old plan.

**After**: comments recovered from checkpoint → refinement re-synthesis
re-runs with the correct comments.

### Fix 2: Clarification resume matches `awaiting_clarification` goals

`resolve_clarification_resume_ce_goal` (goal_text.py) now accepts both
`"active"` and `"awaiting_clarification"` statuses. `_RESUMABLE_CE_STATUSES`
also includes `"awaiting_clarification"`. `strange_loop.py` unparks an
`awaiting_clarification` goal by calling `answer_clarification()` →
`activate_goal()`.

**Before**: goal parked in `awaiting_clarification` (plan-mode review) →
worker crash → user reconnects with `clarification_answer=True` →
`resolve_clarification_resume_ce_goal` only found `active` goals → created
a new goal → user's reject answer treated as a new goal text.

**After**: the parked goal is found and re-activated → reject answer
correctly enters the plan-mode review refinement path.

### Fix 3: Stale-loop reconciler skips clarification-parked loops

`peek_clarification_pending` (auto_resume.py) implemented to check the
LangGraph checkpoint for `pending_clarification`. The reconciler
(`_reconcile_stale_running_loops` in daemon `core.py`) now skips loops with
a pending clarification — they have no active runner by design (parked for
user input), and demoting them kills the clarification flow.

### Fix 4: TUI shows refinement activity + reject-with-comments input flow

- `node_plan_review` emits `plan_refinement_started`/`plan_refinement_completed`
  events during the long LLM synthesis call. The runner maps these to
  `StrangeLoopPlanPhaseStatusEvent` wire events. The TUI spinner shows
  "Refining plan" / "Synthesizing plan" so the user sees activity.
- When the user selects Reject, the TUI no longer immediately submits — it
  focuses the chat input with a placeholder ("Enter refinement comments for
  the plan, then press Enter to reject…") so the user can type comments
  before the reject is sent. The next Enter submits `["Reject", comments]`
  as the clarification answer.

## Design Principles

1. **State is in storage, not in process.** Loop state lives in three
   persistent layers (LangGraph checkpointer, CE, disk artifacts). Workers
   are stateless conduits that read state on entry and persist state on
   exit. A worker crash loses nothing that isn't already on disk.

2. **The `pending_clarification` channel is the re-entry contract.** When a
   loop parks for user input, everything needed to resume (plan draft, plan
   path, refinement comments, clarification origin) is serialized into the
   `pending_clarification` graph channel. A fresh worker reads this channel
   via `aget_state` and reconstructs the full context.

3. **CE goal status is the source of truth for parking.** A goal in
   `awaiting_clarification` is intentionally parked — not crashed, not
   stale. Reconcilers, auto-resume, and clarification-resume all check this
   status before acting.

4. **Scratch is ephemeral; channels are durable.** `LoopPhaseScratch` is
   deliberately not serialized (it carries rich non-primitive models).
   Fields that must survive are projected into graph channels before
   parking. `hydrate_scratch_from_pending` is the inverse projection.

5. **Cancel ≠ terminal.** A cancel during a long-running LLM call
   (synthesis, refinement) cancels the in-flight operation, not the goal.
   The goal's clarification status is preserved so the user's next input
   resumes from the same parked state, not from a new goal.

## Test Coverage

- `test_plan_mode_review_refine.py` — 9 tests: refinement trigger,
  refinement flow, failed refinement fallback, trigger message content,
  trigger truncation, **comments persistence** (3 new tests for
  build_pending → hydrate round-trip).
- `test_auto_resume.py` — 21 tests: including 7 new tests for
  `peek_clarification_pending` (pending, answered, no-pending, no-runner,
  no-checkpointer, no-tuple, error).
- `test_plan_mode_review_approve.py` — 3 tests: approve flow.
- `test_clarification_routing.py` — 12 tests: routing for plan review,
  clarification resume, reject re-emit.
- `test_checkpoint_isolation_resume.py` — orphaned-interrupt recovery.
