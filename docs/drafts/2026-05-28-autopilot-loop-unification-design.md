# Autopilot ↔ Loop-Runner Unification (Daemon-Owned Autopilot)

**Draft**: 2026-05-28
**Status**: Draft (Platonic Brainstorming output — input to Phase 1 RFC formalization)
**Scope**: Resolve gap B2 from the autopilot production-readiness analysis — eliminate the two-loop-concepts problem by moving autopilot ownership into the daemon and treating subprocess workers as fungible AgentLoop executors.
**Targets RFCs**: RFC-222 (Autopilot + Goal Engine), RFC-221 (Loop Runner Protocol)
**Related drafts**: `2026-05-27-autopilot-and-goal-engine-design.md` (superseded for B2 only)

---

## Problem Statement

Two unrelated "loop" concepts coexist in the codebase, and neither talks to the other:

1. `AutopilotService.LoopHandle` (`core/autopilot/loop_pool.py:17`) — an abstract slot tracked in `SootheRunner`'s memory.
2. `LoopRunnerFactory` (`soothe-daemon/runner/factory.py:108`) — one OS subprocess (`PoolLoopRunner`) or thread (`ThreadLoopRunner`) per client `loop_id`.

The daemon's "utility" `SootheRunner` (`server.py:217`) is never used to stream goals — real streaming runs in subprocess `PoolLoopRunner`s, each constructing a **fresh `SootheRunner` per request** (`pool_runner.py:464`), and therefore a fresh `AutopilotService`, `GoalEngine`, `LoopPool`, and `FileLockRegistry` per request. Autopilot state lives and dies inside one query/response cycle. It cannot:

- Outlive a single request (no 24/7 DAG)
- Coordinate across client sessions (no shared scheduling)
- Enforce file-lock conflicts across workers (per-process registry only)
- Recover from daemon restarts (no daemon-owned state)
- Reason about goals submitted via HTTP without an active streaming client (HTTP `/autopilot/submit` writes files that nothing consumes)

The thing we built can't be 24/7 autopilot. This design fixes that without breaking subprocess isolation (RFC-221's correctness invariant).

---

## Design Overview

### The architectural invariant

> **AgentLoop is the pure execution unit. Autopilot is the orchestrator.**
>
> AgentLoop knows nothing about the DAG, sibling goals, the autopilot pool, scheduling, or cross-loop file conflicts. Autopilot knows everything about those — and feeds AgentLoop one goal at a time through a value-typed contract.

```
┌──────────────────────────────────────────────────────────────────┐
│ AUTOPILOT (daemon process, singleton)                            │
│ ─────────────────────────────────────                            │
│ Composes (owns):                                                 │
│   GoalEngine             — DAG, state machine, backoff reasoner  │
│   WorkspaceReservation   — workspace-prefix conflict gate (Q1)   │
│   WorkerPool             — sticky-affinity wrapper over LoopRun- │
│                            nerFactory (subprocess workers)       │
│   ContextProjector       — parents' GoalDispatchContexts → bundle        │
│   GoalDispatchContextStore       — durability-backed context storage     │
│   InternalEventBus       — injected, not singleton (Q8)          │
│   ChannelInbox           — autopilot/inbox/*.md consumer         │
│   SchedulerService       — cron-style timed task triggers        │
│                                                                  │
│ Runs: continuous scheduling loop until daemon shutdown.          │
└──────────────────────────────────────────────────────────────────┘
                              │
                  ┌───────────┴───────────┐
                  │   JOB CONTRACT        │
                  │   LoopRunRequest +    │
                  │   AutopilotJob        │
                  │   (incl. GoalDispatchContext  │
                  │    Bundle)            │
                  │                       │
                  │   STREAM CONTRACT     │
                  │   StreamChunk[…] +    │
                  │   GoalCompletionChunk │
                  └───────────┬───────────┘
                              │
┌──────────────────────────────────────────────────────────────────┐
│ AGENTLOOP (subprocess worker, fungible, RFC-221)                 │
│ ──────────────────────────────────                               │
│ Hydrates from bundle → runs plan/execute loop → emits incremental│
│ chunks → emits final GoalCompletionChunk → idle until next job.  │
│                                                                  │
│ Has no GoalEngine, no autopilot, no DAG view, no FileLockReg-    │
│ istry. Solo invocations (`soothe "X"`) skip the autopilot_job    │
│ entirely and run today's single-goal flow unchanged.             │
└──────────────────────────────────────────────────────────────────┘
```

### Why this resolves B2

- One canonical autopilot lives in the daemon for the daemon's lifetime → outlives requests, survives restarts (with persisted GoalDispatchContext).
- Subprocess workers become **fungible AgentLoop executors** — no per-worker autopilot, no per-worker GoalEngine, no per-worker conflict registry.
- The file-lock conflict question collapses to a scheduling-time check at the daemon (Q1), so the cross-process RPC problem doesn't have to be solved.
- Subprocess isolation (RFC-221) is preserved verbatim — workers still crash independently, the daemon still receives streamed events, the cancellation contract is unchanged.
- DAG composability (diamonds, fan-out, backoff jumps, crash recovery) is solved by **bounded summarization** via `GoalDispatchContext`, not by trying to ferry full in-memory state across process boundaries.

---

## The Job Contract (Autopilot → Worker)

### Extending `LoopRunRequest`

Defined in `protocols/runner.py`. Add one optional field:

```python
@dataclass
class LoopRunRequest:
    # … existing fields (thread_id, loop_id, workspace, user_input, config,
    #   autonomous, max_iterations, intent_hint, …) — unchanged

    # NEW: when set, this is an autopilot-dispatched job. When None,
    # this is a solo-mode request; AgentLoop runs today's path.
    autopilot_job: AutopilotJob | None = None


@dataclass(frozen=True)
class AutopilotJob:
    goal_id: str
    goal_description: str
    merged_context: GoalDispatchContextBundle     # pre-projected by ContextProjector
    deadline_seconds: float | None        # wall-clock budget; None = no cap
    attempt: int                          # 1 on first dispatch, N on retry
```

Key properties:
- `autopilot_job` is **optional**. Solo callers pass `None`. AgentLoop branches on its presence — no global config gates behavior.
- `merged_context` is **pre-computed in the daemon**. Worker never reads from `GoalEngine`, never queries parents, never sees the DAG.
- `deadline_seconds` gives autopilot a way to bound runaway goals (closes gap H5).
- `attempt` lets the worker adapt strategy on retries (e.g., switch model, raise planning depth) without daemon-side prompt mutation.

### `GoalDispatchContextBundle` (the value type)

Defined in `core/goal_engine/models.py`:

```python
class GoalDispatchContextBundle(BaseModel):
    """Immutable hydration input for AgentLoop (RFC-222 Model Y′).

    Merged across all parents (`depends_on` ∪ `informs`) by ContextProjector.
    Bounded size — summaries, not raw transcripts.
    """
    prior_plan_steps: list[PriorStepSummary] = []
    files_touched: dict[str, FileTouchSummary] = {}     # path → hash + op
    findings: list[ParentFinding] = []                  # LLM-synthesized
    tool_call_summary: ToolCallStats = ToolCallStats()
    cached_system_prompt_hash: str | None = None        # for provider cache hit

    @model_validator(mode="after")
    def _enforce_bounds(self) -> Self:
        # Hard caps enforced at construction; ContextProjector respects same
        # caps when merging so the post-merge bundle stays bounded.
        ...
        return self
```

Helper types (`PriorStepSummary`, `FileTouchSummary`, `ParentFinding`, `ToolCallStats`) live alongside in `models.py`. All Pydantic, all serializable, all bounded.

### Why bounded summarization (and not full-memory continuity)

| DAG shape | Bounded summarization | Full-memory continuity |
|---|---|---|
| Linear chain (A → B → C) | Project forward; fine | Ideal (just keep the worker) |
| Fan-out (P → C₁, C₂, C₃ parallel) | Each child snapshots P's bundle | Cannot run 3 children from one in-memory state without process fork |
| Diamond join (A, B → G) | Union both bundles | No meaningful "merge two LLM working memories" operation exists |
| Backoff (G fails → resume at X) | Hydrate X's stored bundle | Requires X's worker still alive AND its state from when X completed |
| Worker dies mid-goal | Re-dispatch elsewhere with same bundle | Lose all in-memory state |

Full-memory continuity gives real benefit only for the linear-chain-on-one-worker case. Every other shape forces summarization or worse. The one production-relevant performance benefit (provider-side prompt cache) lives at the provider, not in our process — preserved under summarization as long as the prompt prefix stays stable.

---

## The Stream Contract (Worker → Autopilot)

Workers already emit `StreamChunk`s through the existing pipe (`pool_runner.py:474`). Add one new chunk type, emitted **exactly once** just before the existing terminal `("done", request_id, None)`:

```python
class GoalCompletionChunk(BaseModel):
    type: Literal["autopilot.goal_completion"] = "autopilot.goal_completion"
    goal_id: str
    outcome: Literal["completed", "failed", "needs_replan"]
    goal_result: GoalResult                      # reuses existing type
    context_contribution: GoalDispatchContextContribution  # what this goal adds to DAG
    evidence: EvidenceBundle | None              # populated when outcome == "failed"
```

Daemon's `AutopilotService` subscribes to its own dispatched workers' streams and reacts when it sees `GoalCompletionChunk`. No new IPC mechanism; the streaming pipe is the single channel.

### Worker behavior

Inside `SootheRunner.astream`:

```python
if request.autopilot_job is not None:
    # New: single-goal worker path, hydrated from the bundle.
    async for chunk in self._run_single_autopilot_goal(request.autopilot_job):
        yield chunk
else:
    # Existing solo path (today's _run_agentic / _run_quiz dispatch).
    async for chunk in self._run_today_solo_path(...):
        yield chunk
```

`_run_single_autopilot_goal` (~80 lines, new):
1. Build AgentLoop with the worker's existing CoreAgent.
2. Hydrate AgentLoop's `loop_messages` and plan ledger from `merged_context`.
3. Run AgentLoop on the single goal.
4. On terminal step, emit `GoalCompletionChunk` with synthesized `GoalDispatchContextContribution`.

Does NOT call `GoalEngine.create_goal`/`ready_goals`/`complete_goal`/`fail_goal` — daemon owns all of that.

### Cancellation

Reuse the existing `cancel_event` mechanism (`pool_runner.py:448`). Daemon's `autopilot.cancel_goal(goal_id)` resolves the assigned worker via `goal_engine.get_goal()`, calls `worker.runner.cancel()`, then transitions the goal to failed in the engine. AgentLoop's cooperative cancellation check between chunks (`pool_runner.py:485`) is unchanged.

This closes gap H8.

---

## The Daemon's Scheduler

### Lifecycle

`AutopilotService` is constructed in `SootheDaemon.start()` once per daemon. Construction order:

```python
self._autopilot_service = AutopilotService(
    daemon_cfg=self._daemon_config,
    agent_cfg=self._config,
    runner_factory=self._runner_factory,    # reuses RFC-221 LoopRunnerFactory
    durability=self._runner._durability,
)
await self._autopilot_service.start()
```

`autopilot_service.start()` starts the scheduling task. `autopilot_service.stop()` is called from daemon shutdown — cancels active workers, drains pending stream tasks bounded by a graceful-shutdown timeout, persists final state.

### Scheduling loop (one tick)

```
every poll_interval seconds, until shutdown_event:

  1. INTAKE
     drain channel_inbox → create goals
     drain scheduler.due_tasks() → create goals

  2. SCHEDULE
     ready = goal_engine.peek_ready_goals(limit = max_parallel_goals)
     for goal in ready:
         if not worker_pool.has_capacity(): break
         bundle = await context_projector.project(goal)
         worker = await worker_pool.pick_worker(goal, prefer = sticky(goal))
         if worker:
             await dispatch(goal, bundle, worker)   # fire-and-stream

  3. MONITOR
     for active worker: check deadline, heartbeat → cancel/replace as needed

  4. IDLE RELEASE
     release workers idle past loop_idle_timeout

  5. DREAMING
     if goal_engine.is_complete() and inbox is empty:
         enter dreaming mode (poll less frequently until woken)
```

The tick **does not await goal completion**. Dispatch fires an async task that consumes the worker's stream; reaction to completion happens asynchronously.

### `dispatch()` + stream consumer

```python
async def dispatch(self, goal, bundle, worker) -> None:
    claimed = await self._goal_engine.claim_goal(goal.id, loop_id=worker.loop_id)
    if not claimed:
        await self._worker_pool.return_to_idle(worker)
        return

    request = LoopRunRequest(
        loop_id=worker.loop_id,
        thread_id=f"autopilot__goal_{goal.id}__attempt_{goal.retry_count + 1}",
        user_input="",
        autopilot_job=AutopilotJob(
            goal_id=goal.id,
            goal_description=goal.description,
            merged_context=bundle,
            deadline_seconds=worker.compute_deadline(goal),
            attempt=goal.retry_count + 1,
        ),
        config=self._agent_cfg,
        autonomous=True,
        max_iterations=self._agent_cfg.autonomous.max_iterations,
    )

    worker.active_task = asyncio.create_task(
        self._consume_worker_stream(goal.id, worker, request)
    )


async def _consume_worker_stream(self, goal_id, worker, request) -> None:
    try:
        async for chunk in worker.runner.run(request):
            await self._route_chunk(goal_id, worker, chunk)
    except Exception as exc:
        await self._handle_worker_crash(goal_id, worker, exc)
```

`_route_chunk` dispatches by chunk type:
- Most chunks → forward to clients subscribed to `worker.loop_id` (existing daemon broadcast path).
- `GoalCompletionChunk` → autopilot reacts:
  - `completed` → `goal_engine.complete_goal()` + `context_store.put()` + `worker_pool.mark_idle()`
  - `failed` → `goal_engine.fail_goal(evidence=…)` (engine schedules `BackoffReasoner` per Q6) + `worker_pool.mark_idle()`
  - `needs_replan` → goal stays `active`, autopilot re-projects bundle (applying backoff directives) and re-dispatches without releasing the worker

This is the **only place** the daemon reacts to worker outcomes — single chokepoint, easy to test.

### `WorkerPool` (sticky-affinity wrapper)

Wraps `LoopRunnerFactory`. Sticky scheduling: prefer a worker that recently ran one of the goal's parents (warm caches), fall back to any idle worker, fall back to spawning a new one under the `max_loops` cap.

Worker `loop_id` is namespaced: `autopilot__w001`, `autopilot__w002`, …. The daemon's WebSocket broadcast layer (`daemon/protocol/router.py`) filters `autopilot__*` out of client `subscribe_loop` requests — autopilot workers are not user sessions. Clients see their own session loop_ids; autopilot workers stay private to the daemon.

### Crash recovery

On daemon start, after `GoalEngine.restore_from_durability()`:
1. Scan `_goals` for `status == "active"` — these were mid-flight when the daemon died.
2. Reset to `pending`, clear `assigned_loop_id`, increment `attempts_after_crash` counter, log loudly.
3. Scheduling loop picks them up on next tick.

`GoalDispatchContext` for completed parents is in durability — re-dispatch hydrates from there. One bundle's worth of work is the maximum re-execution loss per crashed goal.

This closes gap H4.

---

## Existing-Code Mapping

| File | Change |
|---|---|
| `core/autopilot/service.py` | **Major rewrite.** Daemon-owned. Composes GoalEngine + WorkerPool + ContextProjector + InternalEventBus. Real scheduling loop. |
| `core/autopilot/loop_pool.py` | **Renamed → `worker_pool.py`.** `LoopHandle` → `WorkerSlot` (wraps `LoopRunnerProtocol`). `working_memory: dict` removed. `goal_to_loop` becomes sticky recency cache. |
| `core/autopilot/context_projector.py` | **New** (~150 lines). |
| `core/autopilot/context_store.py` | **New.** Thin wrapper over `DurabilityProtocol`. |
| `core/autopilot/channel_inbox.py` | **New.** Reads `$SOOTHE_HOME/autopilot/inbox/*.md`. |
| `core/autopilot/workspace_reservation.py` | **New.** Workspace-prefix conflict gate at scheduling time (Q1). Daemon-owned. |
| `core/goal_engine/file_lock_registry.py` | **Code preserved but unwired** (per Q1 — workspace-level reservation supersedes path-level locking). Same treatment as `middleware/file_lock.py`. |
| `core/goal_engine/engine.py` | `GoalEngine` no longer accepts `internal_bus` from outside callers — `AutopilotService` constructs it with its own bus. Adds `restore_from_durability()`. |
| `core/goal_engine/models.py` | **Adds** `GoalDispatchContext`, `GoalDispatchContextBundle`, `GoalDispatchContextContribution`, `PriorStepSummary`, `FileTouchSummary`, `Finding`, `ToolCallStats`. ~150 lines. |
| `protocols/runner.py` | `LoopRunRequest` gains `autopilot_job: AutopilotJob \| None`. New `AutopilotJob` dataclass. |
| `core/runner/__init__.py` (`SootheRunner`) | **Removes** `_autopilot_service`. Becomes solo-mode-or-autopilot-worker, decided per-request. |
| `core/runner/_runner_autonomous.py` | **Most of it deleted** (~600 lines). Multi-goal scheduling, parallel batching, proposal queue, send-back — all move to daemon. Only `_run_single_autopilot_goal` (~80 lines, new) stays for the worker path. |
| `middleware/file_lock.py` | **Code preserved but unwired** (per Q1 — workspace-level locking at scheduling time supersedes path-level middleware locking). |
| `daemon/server.py` | **Adds** AutopilotService construction in `start()`, `await autopilot.stop()` in shutdown. |
| `daemon/transports/http_rest.py` | All `/autopilot/*` endpoints rewire to the live service instead of file-poking. |
| `daemon/runner/factory.py` | **No change.** Worker-pool primitive that autopilot wraps. |
| `daemon/protocol/router.py` | Filters `autopilot__*` loop_ids out of client `subscribe_loop`. |
| `config/models.py` | Adds `AutonomousConfig.context_projection` sub-block (max_findings, max_files, max_plan_steps, context_retention_hours). |

**Net delta**: ~600 lines deleted, ~800 lines added, ~300 lines rewritten.

---

## Migration Plan

The constraint: tests pass at every commit, production daemon keeps working through the transition.

**Phase A — additive scaffolding (no behavior change)**
1. Add `GoalDispatchContext`/`GoalDispatchContextBundle`/`GoalDispatchContextContribution` models + tests.
2. Add `AutopilotJob` + extend `LoopRunRequest` (existing callers pass `None`).
3. Add `ContextProjector` + `GoalDispatchContextStore`. Unit tests, no callers yet.
4. Add `WorkerPool` wrapping `LoopRunnerFactory`. Unit tests, no callers yet.

**Phase B — wire the new worker path (parallel to old)**
5. `SootheRunner.astream` branches on `autopilot_job`. Autopilot-job branch is callable; nothing in production calls it yet.
6. Daemon-side `AutopilotService` constructed in `start()` but `enabled=False`. Scheduling loop runs but has no goals.

**Phase C — cutover one endpoint at a time**
7. HTTP `/autopilot/submit` calls `autopilot.submit_task` instead of writing inbox files. Other endpoints follow.
8. Channel inbox processing turns on. HTTP-submitted goals flow through daemon's autopilot.
9. Run both paths in parallel for one release. Gather telemetry.

**Phase D — destructive cleanup**
10. Delete `SootheRunner._autopilot_service`. Delete `_execute_goal_via_autopilot`. Delete `_run_autonomous` multi-goal scheduling. Delete `initialize_autopilot`. Update `soothe --autopilot` CLI to be a daemon client (Q7).
11. Remove `autonomous=True` from `SootheRunner.astream`.

Phases A and B are reversible. Phase C is the cutover. Phase D is irreversible — gated on the new path running cleanly for a release.

---

## Testing Strategy

| Phase | New tests |
|---|---|
| A | Unit: `GoalDispatchContext` bounds, `ContextProjector.project` for linear/diamond/fanout, `WorkerPool.pick_worker` sticky preference + idle reuse + spawn-under-cap. |
| B | Unit: `_run_single_autopilot_goal` consumes bundle, emits completion chunk. Integration: `AutopilotService.dispatch` → fake `LoopRunnerProtocol` → canned completion. |
| C | **End-to-end**: HTTP `POST /autopilot/submit` → daemon `AutopilotService` → fake worker → goal completes → context stored → child goal scheduled with merged bundle. This is the missing integration test from gap M9. |
| D | Migration tests: assert removed APIs raise clear errors; assert solo-mode path unchanged. |

Existing tests affected:
- All `_run_autonomous` multi-goal tests — most rewrite as daemon-side autopilot tests; some delete outright.
- `SootheRunner._autopilot_service` tests — delete; replaced by daemon-side coverage.
- 11 tests of `AutopilotService.execute_goal` from the Phase 1 round — most adapt to the new `dispatch` signature; lineage tests delete (lineage is now sticky preference, not a correctness invariant).

Expected delta: **~−30 existing tests, ~+50 new tests.** Net coverage up.

---

## Open Questions (Resolved Defaults)

These were debated and locked during brainstorming:

| # | Question | Resolution |
|---|---|---|
| Q1 | File-lock granularity | **Workspace-level for v1.** New `WorkspaceReservation` component, owned by `AutopilotService`, enforced at scheduling time — refuse to dispatch two goals on overlapping workspace prefixes concurrently. Path-level deferred; `FileLockMiddleware` and `FileLockRegistry` code preserved unwired (revive when fine-grained conflicts become a real problem). |
| Q2 | ContextProjector relevance heuristic | **Simple heuristic for v1** (recency + file overlap). Pluggable so LLM-scored projection can be added later. |
| Q3 | GoalDispatchContext eviction | **Per-root-goal + age.** When root goal reaches terminal state, its DAG's contexts become evictable after `context_retention_hours` (default 168h). LRU-evict if quota exceeded. |
| Q4 | Multi-tenancy | **Reject overlapping-workspace submissions** unless explicit shared-mode opt-in. Cross-tenant authz deferred to its own RFC. |
| Q5 | Solo + autopilot coexistence | **Yes, with workspace-overlap check.** Solo invocations register a transient workspace claim with the daemon for their duration. |
| Q6 | Backoff reasoning | **Async fire-and-forget.** `goal_engine.fail_goal()` schedules `BackoffReasoner` as a separate task; goal returns to `pending` (with directives) when reasoner completes. Scheduling loop is non-blocking. |
| Q7 | CLI backwards compatibility (`soothe --autopilot`) | **Becomes a daemon client.** Requires daemon running; posts to `/autopilot/submit`, streams progress via WebSocket. Clear error + start-daemon hint if not running. |
| Q8 | `InternalEventBus` placement | **Drop the singleton `get_internal_bus()`.** Bus is owned by `AutopilotService`; injected to all consumers. Eliminates spooky-action-at-a-distance across test boundaries. |

---

## Out of Scope (Explicit)

- **Distributed multi-daemon autopilot** (DAG sharded across daemons). Single-daemon only. Future RFC.
- **Streaming context updates mid-goal.** Workers emit one `GoalDispatchContextContribution` at end. Mid-flight context checkpointing is a future enhancement.
- **GoalDispatchContext schema versioning.** Bump model version; ad-hoc migration.
- **Cost / token-budget enforcement** (gap H3). Future RFC; this design is the substrate it plugs into.
- **Webhook delivery wiring.** Easy bolt-on once daemon owns the bus — a `WebhookSubscriber` listens to `InternalGoalStateChangedEvent`. Out of scope here.

---

## Gaps This Closes (from production-readiness analysis)

| Gap | Resolution |
|---|---|
| B2 — Two incompatible loop concepts | Resolved by collapsing to one: AutopilotService in daemon, AgentLoop in worker. |
| B1 — Scheduling loop never runs | Daemon owns AutopilotService.start() → continuous scheduling. |
| B3 — GoalEngine state in-process only | Daemon-owned + `restore_from_durability()`. |
| B4 — File-lock registry per-process | Replaced by daemon-owned `WorkspaceReservation` enforced at scheduling time (Q1). `FileLockRegistry` preserved unwired for a future fine-grained design. |
| B5 — FileLockMiddleware not installed | Replaced by workspace-level scheduling check (Q1). `FileLockMiddleware` preserved unwired. |
| H4 — No crash recovery for in-flight goals | Crash recovery routine on daemon start (reset `active` → `pending`, hydrate from GoalDispatchContext). |
| H5 — No deadline / hang detection | `AutopilotJob.deadline_seconds` + monitor tick. |
| H8 — Goal cancellation not wired | `autopilot.cancel_goal()` + existing `cancel_event`. |
| M1 — Channel inbox disconnected | `ChannelInbox` consumer; `/autopilot/submit` cutover. |
| M9 — No integration tests | Phase C end-to-end test required for cutover. |

Remaining production gaps (H1, H2, H3, H6, H7, M2–M8, M10, P*) are deliberately out of scope for this design and tracked in the gap analysis for future RFCs.

---

## Handoff

This design draft is the input to **Platonic Coding Phase 1: RFC formalization**. The Phase 1 RFC will:
- Re-render this as a formal RFC document with sections matching the project's RFC template (Abstract, Motivation, Architecture Position, Specification, …).
- Update or supersede RFC-222 with the changes here (the existing RFC-222 §"Loop Pool Management" and §"Lineage-Aware Loop Assignment" sections are obsolete in their current form).
- Note RFC-221 compatibility (no change to `LoopRunnerProtocol` — only to how the daemon uses it).
- Refine the schemas of `GoalDispatchContext*` types based on what the implementation actually needs.

After RFC formalization, `specs-refine` runs to cross-check consistency with related RFCs (RFC-200 backoff, RFC-204 file discovery, RFC-220 AgentLoop graph, RFC-403 events).
