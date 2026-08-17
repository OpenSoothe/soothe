# RFC-222: Autopilot Daemon Architecture

**RFC**: 222
**Title**: Autopilot Daemon Architecture (Worker Dispatch)
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-05-27
**Updated**: 2026-08-16
**Dependencies**: RFC-000, RFC-201, RFC-204, RFC-221 (Loop Runner Protocol), RFC-625, RFC-626, RFC-214 (Loop Message Surface)
**Related**: RFC-200 (Goal Lifecycle), RFC-220 (Loop Orchestrator), RFC-403 (Events), RFC-229 (Cron Service for Autopilot), RFC-204 §1.3 (report-commit judgment), RFC-231 (LoopRail), RFC-214 (loop message ledger), design draft `docs/drafts/2026-08-16-autopilot-goal-dag-pair-projection-design.md`, `docs/archive/drafts/2026-08-08-autopilot-report-commit-judgment-design.md`

> **Ownership**: Goal/step DAG state lives in **ContextEngine** (RFC-624 / RFC-625). This RFC owns the daemon-side **dispatch contract**: `AutopilotService`, `WorkerPool`, `WorkspaceReservation`, `AutopilotJob` / `GoalCompletionChunk`, and report-commit handoff into CE. Sections that still name `GoalEngine` describe deleted components — treat CE + AutopilotMonitor as authoritative for those concerns.

---

## Abstract

This RFC defines **daemon-owned autopilot**: one `AutopilotService` per daemon that schedules fungible StrangeLoop workers via `LoopRunnerProtocol` (RFC-221), gates concurrent workspace use with `WorkspaceReservation`, and hydrates each worker from a bounded `GoalDispatchContextBundle` built from CE. Workers execute one goal, emit `GoalCompletionChunk`, and the daemon commits the StrangeLoop ledger report to CE for report-commit judgment (RFC-204 §1.3).

The model enables 24/7 operation, cross-session coordination, crash recovery via persisted context contributions, and workspace-level conflict gating at scheduling time.

---

## Motivation

### The two-loop problem (gap B2 from production-readiness analysis)

Two unrelated "loop" concepts coexist in the codebase and never communicate:

1. **`AutopilotService.LoopHandle`** — abstract slot in `SootheRunner` memory (`core/autopilot/loop_pool.py:17`).
2. **`LoopRunnerFactory`** — one OS subprocess (`PoolLoopRunner`) or thread per client `loop_id` (`soothe-daemon/runner/factory.py:108`).

The daemon's "utility" `SootheRunner` (`server.py:217`) is never used to stream goals. Real streaming runs in subprocess `PoolLoopRunner`s, each constructing a **fresh `SootheRunner` per request** (`pool_runner.py:464`), and therefore a fresh `AutopilotService`, `GoalEngine`, `LoopPool`, and `FileLockRegistry` per request. Autopilot state lives and dies inside a single request/response cycle.

The consequence: autopilot today cannot outlive a request, cannot coordinate across sessions, cannot enforce file conflicts across workers, and cannot recover from daemon restarts. The HTTP `/autopilot/submit` endpoint writes files to a directory that nothing reads (gap M1).

### DAG composability problem

The prior design pinned a worker to a goal's parent for "context reuse." Real DAGs aren't trees:

- **Diamond joins** (G has parents A, B): which parent's worker hosts G? No principled answer.
- **Fan-out** (P has children C₁, C₂, C₃ in parallel): they can't all share P's in-memory state.
- **Backoff jumps** (G fails → resume at ancestor X): X's worker may be long gone.
- **Worker crash**: in-memory state is lost; the whole lineage dies.

In-memory continuity only handles linear-chain-on-one-worker. Every other shape forces summarization or worse.

### Goals

1. **Single autopilot, daemon-lifetime.** `AutopilotService` is constructed once during `SootheDaemon.start()` and runs until shutdown.
2. **StrangeLoop as pure execution unit.** StrangeLoop knows nothing about the DAG, sibling goals, the autopilot pool, scheduling, or cross-loop file conflicts. The job → worker → completion-chunk contract is the entire surface autopilot shares with StrangeLoop.
3. **Bounded summarization for DAG composability.** Cross-goal context flows as a serializable `GoalDispatchContextBundle` (kilobytes, not megabytes). Diamonds and fan-out compose naturally. Crash recovery is automatic.
4. **Workspace-level conflict gate at scheduling time.** Daemon refuses to dispatch two goals on overlapping workspace prefixes concurrently. Removes the need for cross-process file-lock RPC.
5. **Subprocess isolation preserved (RFC-221).** Workers still crash independently; the daemon still consumes their streams; cancellation still uses the existing `cancel_event`.
6. **Solo mode unchanged.** `soothe -p "do X"` bypasses autopilot entirely — no CE job DAG dispatch, no `GoalDispatchContextBundle`.

---

## Architectural Invariant

> **StrangeLoop is the pure execution unit. Autopilot is the orchestrator.**
>
> StrangeLoop knows nothing about the DAG, sibling goals, the autopilot pool, scheduling, or cross-loop file conflicts. Autopilot knows everything about those — and feeds StrangeLoop one goal at a time through a value-typed contract.

This invariant gates every design choice. If a proposed change would require StrangeLoop to know about its siblings or about the DAG shape, it doesn't belong.

---

## Architecture Position

### Layer Model

```
Autopilot (daemon process, singleton)
  ┌──────────────────────────────────────────────────────────────┐
  │ AutopilotService (composes the following)                    │
  │   • ContextEngine (RFC-625) — GoalNode DAG, reports, backoff │
  │   • AutopilotMonitor      — DAG health / dreaming (non-rail) │
  │   • WorkspaceReservation  — workspace-prefix conflict gate   │
  │   • WorkerPool            — sticky wrapper over LoopRunner-  │
  │                             Factory (subprocess workers)     │
  │   • CE projection         — parents → GoalDispatchContextBundle │
  │   • InternalEventBus      — injected, not singleton          │
  │   • SchedulerService      — cron-style timed task triggers   │
  │                                                              │
  │ Lifecycle: daemon.start() → autopilot.start() →              │
  │            scheduling loop runs until daemon shutdown        │
  └──────────────────────────────────────────────────────────────┘
                                │
                       JOB / STREAM CONTRACT
                  (LoopRunRequest + AutopilotJob ↓)
                  (StreamChunk[…] + GoalCompletion ↑)
                                │
StrangeLoop (subprocess worker, fungible, RFC-221)
  ┌──────────────────────────────────────────────────────────────┐
  │ One subprocess per worker slot (LoopRunnerFactory).          │
  │ Per request: SootheRunner.astream(autopilot_job=…) →         │
  │              _run_single_autopilot_goal(job) →               │
  │              StrangeLoop hydrates from bundle, executes,       │
  │              emits GoalCompletionChunk + done.               │
  │                                                              │
  │ Knows: nothing about the DAG, autopilot, or siblings.        │
  └──────────────────────────────────────────────────────────────┘

CoreAgent (per StrangeLoop)
  Unchanged from prior RFC. Tools, subagents, MCP, middleware.
```

### Service Boundary Definition

**AutopilotService responsibilities (daemon-resident):**
- Accept task submissions via HTTP/CLI (`submit_task`) and scheduled tasks
- Run the scheduling loop (peek → project → assign → claim → dispatch)
- Manage `WorkerPool` (sticky affinity, idle release, deadline monitoring)
- Compute `GoalDispatchContextBundle` per dispatch via `ContextProjector`
- Consume worker streams; react to `GoalCompletionChunk`
- Drive backoff via `GoalEngine.fail_goal` (which schedules `BackoffReasoner` async)
- Enforce `WorkspaceReservation` at scheduling time
- Dispatch internal events through `InternalEventBus` (consumed by webhook subscribers, observability, etc.)
- Manage dreaming mode transitions
- Handle crash recovery on daemon startup

**Not responsible for:**
- Single-goal execution logic (`StrangeLoop` owns this)
- Plan/execute/reflect mechanics (RFC-201, RFC-220 own these)
- Tool/subagent execution (CoreAgent owns this)
- Subprocess lifecycle (`LoopRunnerFactory` owns this — autopilot is a consumer)

**StrangeLoop responsibilities (subprocess worker):**
- Hydrate `loop_messages` and plan ledger from `GoalDispatchContextBundle` on entry — including seeding `preamble_messages` pairs into the CE ledger as a transcript before the current goal turn (§Goal-Report-Pair Projection)
- Drive plan/execute/reflect loop for the one goal at hand
- Emit `GoalCompletionChunk` exactly once, just before the terminal `done` chunk
- Cooperatively check `cancel_event` between chunks (existing mechanism)

**Not responsible for:**
- DAG state / multi-goal scheduling
- Other goals (sibling/parent/child)
- File-lock coordination across workers
- `GoalEngine` calls (`create_goal`, `ready_goals`, `complete_goal`, `fail_goal`)

---

## The Job and Stream Contracts

Defined in `soothe/protocols/runner.py`.

### Job Contract — Autopilot → Worker

```python
@dataclass
class LoopRunRequest:
    # … existing RFC-221 fields (thread_id, loop_id, workspace, user_input,
    #   config, autonomous, max_iterations, intent_hint, …) — unchanged

    # RFC-222: when set, this is an autopilot-dispatched job. When None,
    # this is a solo-mode request and StrangeLoop runs today's path.
    autopilot_job: AutopilotJob | None = None


@dataclass(frozen=True)
class AutopilotJob:
    goal_id: str
    goal_description: str
    merged_context: GoalDispatchContextBundle      # pre-projected by daemon
    deadline_seconds: float | None         # wall-clock budget; None = no cap
    attempt: int                           # 1 on first dispatch, N on retry
```

Properties:
- `autopilot_job` is **optional**. Solo callers pass `None`. StrangeLoop branches on presence — no global config gates behavior.
- `merged_context` is **pre-computed in the daemon**. Worker never queries CE parents or the DAG.
- `deadline_seconds` bounds runaway goals.
- `attempt` lets the worker adapt strategy on retries without daemon-side prompt mutation.
- **One implement dispatch per attempt (IG-725):** Autopilot does **not** re-dispatch the same goal for workspace/git proof theater. StrangeLoop loop end → ledger report → CE `commit_goal_report` → `goal_report_committed` → Autopilot report-commit judge (accept / send_back / fail + bounded DAG ops per RFC-204 §1.3). Worker completion MUST NOT invent a second judgment path outside CE. On accept, LoopRail is notified; AutopilotMonitor may evaluate non-rail CE DAG health.

### Job abstraction (CE entities)

1. `goal_id` in `AutopilotJob` references CE `GoalNode` directly.
2. Wave execution metrics live on CE (`WaveMetrics` / related GoalNode fields).
3. `merged_context` is built from CE projection + `GoalNode` lineage.
4. `GoalCompletionChunk.context_contribution` is written to CE (`GoalNode` / EpisodicSubmodule).
5. Workers hydrate from the bundle and emit a completion chunk; completion updates CE via `complete_goal` / report commit.

### Stream Contract — Worker → Autopilot

Workers already emit `StreamChunk`s through the existing IPC pipe (`pool_runner.py:474`). RFC-222 adds **one new chunk type**, emitted exactly once just before the terminal `done` chunk:

```python
class GoalCompletionChunk(BaseModel):
    # Internal namespace per RFC-403 — never broadcast to external clients.
    type: Literal["soothe.internal.autopilot.goal_completion"] = (
        "soothe.internal.autopilot.goal_completion"
    )
    goal_id: str
    outcome: Literal["completed", "failed", "needs_replan"]
    goal_result: GoalResult                                # reuses existing type
    context_contribution: GoalDispatchContextContribution  # what this goal adds to DAG
    evidence: EvidenceBundle | None                        # populated when outcome == "failed"
```

`AutopilotService` subscribes to its own dispatched workers' streams and reacts when it sees `GoalCompletionChunk`. No new IPC mechanism — the streaming pipe is the single channel.

#### Report commit before judgment

On `GoalCompletionChunk` (or equivalent loop-end), the daemon MUST:

1. Project the StrangeLoop ledger report into CE via `commit_goal_report`
   (always write a **minimal** report if the loop ended without a rich
   finalize payload).
2. Use **`goal_report_committed`** as the sole Autopilot LLM judgment
   entrypoint (RFC-204 §1.3): project CE report → accept / send_back / fail
   + optional bounded DAG ops.
3. NOT rebuild evidence from the workspace or from a second narrative
   outside CE for that judgment.

Dispatch / WorkerPool claim ready goals from CE status and deps only — bare
`pending`/`active` transitions MUST NOT call the judge. LoopRail phase
advancement remains event-driven after the verdict (RFC-231).

### Cancellation Contract

Reuse the RFC-221 `cancel_event` mechanism. Autopilot's `cancel_goal(goal_id)`
resolves the assigned worker, cancels the runner, and transitions the CE goal
to `failed`. StrangeLoop's cooperative check between chunks is unchanged.

---

## GoalDispatchContextBundle (worker hydration)

> **Naming**: `GoalDispatchContext*` is the bounded summary Autopilot ships to a
> worker so StrangeLoop can hydrate without seeing the DAG. It is distinct from
> `GoalContext` in RFC-217 / RFC-200. Bundles are produced from CE projection
> (RFC-625 / RFC-626), not a separate GoalEngine store.

### Why bounded summarization (not full-memory continuity)

| DAG shape | Bounded summarization (this design) | Full-memory continuity |
|---|---|---|
| Linear chain (A → B → C) | Project context forward | Ideal — keep the worker |
| Fan-out (P → C₁, C₂, C₃ parallel) | Each child snapshots P's bundle | Cannot run children from one in-memory state without process fork |
| Diamond join (A, B → G) | Union bundles in projector | No meaningful "merge two LLM working memories" operation exists |
| Backoff (G fails → resume at X) | Hydrate X's stored bundle | Requires X's worker still alive AND its state from when X completed |
| Worker dies mid-goal | Re-dispatch elsewhere with same bundle | Lose all in-memory state |

Full-memory continuity is only achievable for the linear-chain-on-one-worker case. Every other shape forces summarization or worse. The one production-relevant performance benefit (provider-side prompt cache) lives at the provider, not in our process — preserved under summarization as long as the prompt prefix stays stable.

### `GoalDispatchContextBundle` (hydration input)

Defined in `core/goal_engine/models.py`:

```python
class GoalDispatchContextBundle(BaseModel):
    """Immutable hydration input for StrangeLoop.

    Merged across all parents (depends_on ∪ informs) by ContextProjector.
    Bounded size — summaries, not raw transcripts.
    """
    prior_plan_steps: list[PriorStepSummary] = []
    prior_effects: list[GoalEffect] = []  # domain-agnostic side-effect claims
    findings: list[ParentFinding] = []               # LLM-synthesized
    tool_call_summary: ToolCallStats = ToolCallStats()
    cached_system_prompt_hash: str | None = None     # for provider cache hit
    preamble_messages: list[GoalReportUserTurn | GoalReportAITurn] = []
    # ↑ ancestor (user, ai) pairs, topo-ordered, seeded into the CE ledger as
    #   a real transcript before the current goal turn (§Goal-Report-Pair
    #   Projection). Additive: prior_* fields stay for structured consumers.

    @model_validator(mode="after")
    def _enforce_bounds(self) -> Self:
        # Hard caps; ContextProjector respects same caps on merge
        ...
        return self
```

The two preamble turn types are deliberately small and serializable (they
cross the IPC boundary on the bundle):

```python
class GoalReportUserTurn(BaseModel):
    """The 'user' half of a projected ancestor pair — the ancestor's directive."""
    goal_id_origin: str
    content: str = Field(max_length=2000)

class GoalReportAITurn(BaseModel):
    """The 'ai' half of a projected ancestor pair — the ancestor's goal report."""
    goal_id_origin: str
    outcome: str            # completed / failed / needs_replan
    summary: str = Field(max_length=2000)
    findings: list[str] = Field(default_factory=list, max_length=8)
    effects: list[GoalEffect] = Field(default_factory=list, max_length=8)
```

`preamble_messages` is **additive**: the flat `prior_effects` / `findings` /
`prior_plan_steps` fields remain and continue to feed structured consumers
(verifier reasoner, consensus, worker effect checks). The new field is an
*additional* projection that gives the executing LLM a real multi-turn
transcript instead of a flattened prose blob.

### `GoalDispatchContextContribution` (worker output)

What this goal's execution adds to the DAG's context pool:

```python
class GoalDispatchContextContribution(BaseModel):
    plan_steps_executed: list[StepSummary]
    effects: list[GoalEffect]  # StrangeLoop-emitted; opaque refs, not host FS probes
    findings: list[Finding]
    tool_call_stats: ToolCallStats
```

`GoalEffect` (`kind`, `ref`, `statement`, optional `digest` / `confidence`) is
domain-agnostic: coding paths, URLs, ticket ids, or `"answer"` for narrative-only
goals. Host never infers effects from prose or the filesystem (IG-712). Effects
are hydration/observability metadata only — never a consensus or maturity latch
(IG-710 / IG-711 / RFC-230).

Daemon stores it keyed by `goal_id` in `GoalDispatchContextStore` and feeds it to children via `ContextProjector`.

### `ContextProjector`

```python
class ContextProjector:
    """Builds a GoalDispatchContextBundle from a goal's parents.

    Bounded — picks the K most relevant context elements rather than
    blindly unioning. Relevance is heuristic (recency + effect-ref overlap
    with the new goal's description) for v1; pluggable for future
    LLM-scored projection.
    """

    async def project(self, goal: Goal) -> GoalDispatchContextBundle: ...
```

Merge rules:
- **Effects**: dedup by `ref`, latest parent wins (cap `max_effects`)
- **Findings**: concatenate, truncate to top-K by relevance
- **Plan steps**: union, prefer recent N
- **Tool stats**: aggregate
- **Cached prompt hash**: take from most recent parent (for cache hit)
- **Preamble pairs**: one `(GoalReportUserTurn, GoalReportAITurn)` per
  transitive ancestor, in topological order (roots first). See
  §Goal-Report-Pair Projection.

### `GoalDispatchContextStore`

Thin wrapper over `DurabilityProtocol`:
- `put(goal_id, contribution)` — called on completion
- `get(goal_id)` — called by projector
- `delete_for_root(root_goal_id)` — called when a root goal's DAG ages out (per Q3, default 168h after root reaches terminal state)

### Goal-Report-Pair Projection

The flat `prior_*` fields give the executing LLM ancestor context as *prose
bullets bolted onto one user message* — the worker's
`_goal_text_with_bundle` appends `## Prior effects` / `## Operator guidance`
sections to the goal string. This loses the turn structure: the model cannot
tell which ancestor was *asked* what versus which *reported* what, and
provenance (parent → effect) is erased by `ref`-dedup.

The `preamble_messages` field replaces that flattening with a real
multi-turn transcript. For each transitive ancestor goal, the projector
emits one `(GoalReportUserTurn, GoalReportAITurn)` pair:

- **User half** = the ancestor's directive (`GoalNode.description`).
- **AI half** = the ancestor's committed goal report, built by the existing
  `build_goal_report` path (outcome + summary + top findings + top effects).
  Reused unchanged — this is the same report committed via CE
  `commit_goal_report` (RFC-204 §1.3, IG-726).

**Walk**: BFS/DFS over `depends_on` (hard) + `informs` (soft), recursively,
from the dispatched goal — the **full transitive** subgraph, not just direct
parents. A `visited: set[str]` guard prevents re-visiting even if `informs`
soft-links form a cycle (the scheduler guarantees acyclic `depends_on`, but
`informs` is not policed — the guard is cheap insurance).

**Ordering**: ancestors are topologically sorted roots-first (a node never
appears before its own `depends_on` parents); ties broken by `created_at`
(older first). The current goal directive becomes the **final** user message,
so the transcript reads as a real conversation leading up to the current ask.

**Per-ancestor rules**:
- Skip an ancestor with no stored contribution (e.g. crashed before emitting
  one) rather than emit an empty AI turn — the transcript omits it cleanly.
- `build_goal_report` guarantees a minimal `outcome + summary` on thin/crash
  terminals, so every projected AI turn is non-empty by construction.

**Cap**: stop once `len(preamble_messages) >= MAX_PREAMBLE_TURNS` (the
hard IPC bound, `12` = 6 pairs — a fixed constant in `goal_contracts.py`,
not a config knob). When the cap bites mid-subgraph, log the drop count (no
silent truncation) and keep the most-recently-completed ancestors by
`updated_at`.

**Worker seeding**: the worker extracts the pairs from
`job.merged_context.preamble_messages` into `LoopHumanMessage` /
`LoopAIMessage` (phase `"preamble"`) and passes them to
`run_with_progress(goal=…, preamble=pairs)`. StrangeLoop seeds the CE ledger
**after** `state.bind_ce(ce_instance, ce_goal.id)` and **before**
`pump_graph`, so the pairs join the same ledger that `loop_messages` is
rebuilt from (RFC-214) — no extra reflection wiring. The `"preamble"` phase
is excluded from `last_ledger_ai_content` so preamble AI turns are not
surfaced as final user-facing output in `ledger_direct` completion mode.

> **Why seed the ledger, not the goal string?** `loop_messages` is rebuilt
> from the CE ledger on every access (`_build_loop_messages_from_ce_sync`,
> RFC-214). A cache stuffed at dispatch time would be overwritten. The
> ledger is the SoT; committing the preamble there is the only path that
> survives the rebuild. The CE ledger is created *inside*
> `run_with_progress` (line 757) and `state.bind_ce` happens at line 974,
> so the worker cannot pre-seed — it must pass pairs via the `preamble`
> parameter, and StrangeLoop commits them after `bind_ce`.

---

## Goal Lifecycle & DAG

### Goal lifecycle states (unchanged)

Per RFC-204 — 7 states: `pending`, `active`, `validated`, `completed`, `failed`, `suspended`, `blocked`.

### Autopilot-specific Goal fields (revised)

Already present on `GoalNode` (ContextEngine / RFC-626):
- `assigned_loop_id: str | None` — live assignment loop id while the goal is active
  (format `autopilot__{job_id}__{uuid}` per IG-677; cleared when the assignment ends)
- `locked_files: list[str]` — **reserved for future fine-grained locking; unused in v1**
- `lock_status`, `lock_acquired_at` — **reserved for future fine-grained locking; unused in v1**

> **IG-677**: Durable job↔loop membership is **not** `assigned_loop_id` alone.
> `JobLoopIndex` (`autopilot:job_loops:{job_id}` / `autopilot:loop_owner:{loop_id}`)
> records assignment history. Pool **slots** (`autopilot__slot_NNN`) are capacity
> handles; each dispatch allocates a fresh assignment `loop_id` under
> `data/loops/{loop_id}/`.

### `peek_ready_goals` and `claim_goal` (Phase 1 deliverables)

Already implemented (`engine.py:259-307`):
- `peek_ready_goals(limit)` — read-only filter, no state mutation, no events
- `claim_goal(goal_id, *, loop_id)` — atomic activation with conflict re-check, stamps `assigned_loop_id`, emits transition event

Autopilot uses `peek_ready_goals` for capacity planning and `claim_goal` per-dispatch.

### Backoff reasoning (revised — async)

When `GoalCompletionChunk(outcome="failed")` arrives, autopilot calls `goal_engine.fail_goal(goal_id, evidence=…)`. The engine:
1. Updates goal status to `failed` (or `pending` if retry budget remains)
2. **Schedules `BackoffReasoner` as a separate async task** (does not block the dispatch loop)
3. When reasoner completes, applies `BackoffDecision` (may transition another goal to `pending` with new directives)
4. Emits `InternalGoalStateChangedEvent` for each transition

The scheduling loop is non-blocking — it does not await backoff reasoning. This closes the synchronous-LLM-call concern (Q6).

---

## WorkspaceReservation (replaces File Lock Conflict Resolution)

**Per Q1 from brainstorming**: workspace-level reservation enforced at scheduling time replaces per-path file-lock middleware.

### Why

Per-path file-lock conflict requires cross-process RPC because the registry lives in the daemon and the conflict check happens in a worker subprocess. That requires either a new IPC channel or batching all file ops through the daemon. Both are expensive.

Workspace-level reservation is a scheduling-time check in the daemon. It has no runtime cost in the worker. It catches the realistic conflict (two goals operating on overlapping workspace prefixes) which is by far the common case. Fine-grained per-path conflicts within a single workspace are deferred until they become a real problem.

### Specification

```python
class WorkspaceReservation:
    """Daemon-owned scheduling-time workspace conflict gate.

    Refuses to dispatch a new goal whose workspace prefix overlaps with
    any goal currently active or about to be dispatched.
    """

    def acquire(self, goal_id: str, workspace_path: Path) -> bool: ...
    def release(self, goal_id: str) -> None: ...
    def conflicts_with_active(self, workspace_path: Path) -> str | None: ...
```

Called from `AutopilotService.dispatch` immediately before `claim_goal`. If reservation fails, the candidate is deferred to the next tick.

### Preserved code

`FileLockRegistry` (`core/goal_engine/file_lock_registry.py`) and `FileLockMiddleware` (`middleware/file_lock.py`) are **preserved unwired** — they're correct implementations of fine-grained per-path locking that we'll revive if/when conflicts within a single workspace become a real production issue. Until then, they're dead-but-tested code.

This closes gaps B4 and B5 by replacement.

---

## Autopilot Scheduling Loop

### Lifecycle

```python
# In SootheDaemon.start():
self._autopilot_service = AutopilotService(
    daemon_cfg=self._daemon_config,
    agent_cfg=self._config,
    runner_factory=self._runner_factory,    # reuses RFC-221 LoopRunnerFactory
    durability=self._durability,
)
await self._autopilot_service.start()

# In SootheDaemon.shutdown:
await self._autopilot_service.stop()       # graceful drain, then force
```

### One tick of the scheduling loop

```
every poll_interval seconds, until shutdown_event:

  1. INTAKE
     drain scheduler.due_tasks() → goal_engine.create_goal(...)
     (HTTP/CLI submissions arrive via submit_task outside the tick)

  2. SCHEDULE
     ready = goal_engine.peek_ready_goals(limit = max_parallel_goals)
     for goal in ready:
         if not worker_pool.has_capacity():     break
         if workspace_reservation.conflicts_with_active(goal.workspace):
                                                continue   # defer
         bundle = await context_projector.project(goal)
         worker = await worker_pool.pick_worker(goal, prefer = sticky(goal))
         if not worker:                         break
         workspace_reservation.acquire(goal.id, goal.workspace)
         await dispatch(goal, bundle, worker)   # fire-and-stream

  3. MONITOR
     for active worker: check deadline, heartbeat → cancel/replace as needed

  4. IDLE RELEASE
     release workers idle past loop_idle_timeout

  5. DREAMING
     if goal_engine.is_complete():
         enter dreaming mode (poll less frequently until woken)
```

The tick **does not await goal completion**. Dispatch fires an async task that consumes the worker's stream; reaction happens asynchronously.

### `dispatch()` and stream consumer

```python
async def dispatch(self, goal, bundle, worker) -> None:
    claimed = await self._goal_engine.claim_goal(goal.id, loop_id=worker.loop_id)
    if not claimed:
        self._workspace_reservation.release(goal.id)
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
```

```python
async def _consume_worker_stream(self, goal_id, worker, request) -> None:
    try:
        async for chunk in worker.runner.run(request):
            await self._route_chunk(goal_id, worker, chunk)
    except Exception as exc:
        await self._handle_worker_crash(goal_id, worker, exc)
```

`_route_chunk` dispatches by type:
- Most chunks → forward to clients subscribed to `worker.loop_id` (existing daemon broadcast path).
- `GoalCompletionChunk` → autopilot reacts:
  - `completed` → `goal_engine.complete_goal()` + `context_store.put()` + `workspace_reservation.release()` + `worker_pool.mark_idle()`
  - `failed` → `goal_engine.fail_goal(evidence=…)` (engine schedules `BackoffReasoner` async) + `workspace_reservation.release()` + `worker_pool.mark_idle()`
  - `needs_replan` → goal stays `active`, autopilot re-projects bundle (with backoff directives applied) and re-dispatches **without releasing** the worker (sticky continuation)

This is the **only place** the daemon reacts to worker outcomes — single chokepoint, easy to test.

### `WorkerPool` (sticky-affinity wrapper over `LoopRunnerFactory`)

```python
class WorkerPool:
    """Sticky-affinity wrapper around LoopRunnerFactory (IG-677)."""

    async def pick_worker(
        self, goal: Goal, *, job_id: str, prefer: str | None = None
    ) -> WorkerSlot | None:
        # 1. Prefer idle slot (by slot_id or last loop_id)
        # 2. Sticky: idle slot that recently ran any goal.depends_on
        # 3. Any idle slot (LRU) — rebind with a NEW assignment loop_id
        # 4. Spawn new slot under max_loops cap
        # 5. None — caller defers
```

**Slot vs assignment loop id (IG-677):**

| Id | Format | Role |
|----|--------|------|
| `slot_id` | `autopilot__slot_NNN` | Reusable pool capacity / sticky affinity key |
| `loop_id` | `autopilot__{job_id}__{uuid4().hex}` | Per-assignment runtime home under `data/loops/{loop_id}/` |

Idle slot reuse keeps the **slot** and allocates a **new** `loop_id` + runner so directories never mix jobs. The daemon filters `autopilot__*` out of client `subscribe_loop` requests — autopilot workers are not user sessions.

This softens lineage-pinning to *preference*: a child of a parent that just completed will likely land on the same **slot**, but gets its own assignment `loop_id`.

### Crash recovery

On daemon start, after restoring the CE DAG snapshot (and `JobLoopIndex`):
1. Scan goals for `status == "active"` — mid-flight when the daemon died.
2. Reset to `pending`, clear `assigned_loop_id`, increment `attempts_after_crash`, log loudly.
3. Mark stranded index entries `interrupted` (`JobLoopIndex.interrupt_active_loops`).
4. Scheduling loop picks pending goals on the next tick (new assignment `loop_id`s).

`GoalDispatchContextContribution` for completed parents is in durability — re-dispatch hydrates from there. One bundle's worth of work is the maximum re-execution loss per crashed goal. Closes gap H4.

---

## Internal EventBus (revised)

### Per Q8: no module-global singleton

`AutopilotService` constructs and owns its `InternalEventBus` instance. The bus is **injected** into every consumer (`GoalEngine`, `WorkerPool`, subscribers). The `get_internal_bus()` singleton from the current implementation is dropped — it created spooky-action-at-a-distance across test boundaries.

### Event namespaces (unchanged from prior RFC)

| Namespace | Bus | Purpose |
|---|---|---|
| `soothe.internal.goal.*` | Internal | DAG state transitions, ready notifications |
| `soothe.internal.loop.*` | Internal | Worker lifecycle, sticky scheduling |
| `soothe.internal.file.*` | Internal | (reserved — unused in v1 per Q1) |
| `soothe.internal.autopilot.*` | Internal | Service lifecycle, dreaming, pool changes |
| `soothe.cognition.*` | External | User-facing progress (existing) |
| `soothe.output.*` | External | User-facing output (existing) |

**Key principle**: internal events never leak to external clients (WebSocket, TUI). The daemon's chunk router filters them by namespace prefix.

### Subscribers

In daemon-owned autopilot, the natural subscribers are:
- `WebhookSubscriber` (bridges `InternalGoalStateChangedEvent` → HTTP POST to configured webhook URLs)
- `MetricsSubscriber` (Prometheus / OpenTelemetry exporters — future)
- `ObservabilityLogger` (structured audit log for backoff decisions — future, addresses gap M8)

The existing internal-event types declared in `events/internal_events.py` are reused; no new event types are introduced by this revision.

---

## Solo Mode (Unchanged)

```
┌────────────────────────────────────────────────────────────┐
│ Solo Mode: bypasses autopilot entirely                     │
│                                                            │
│ Entry:                                                     │
│   `soothe -p "user input"` (CLI headless)                  │
│   `soothe` → TUI → user input                              │
│                                                            │
│ Flow:                                                      │
│   CLI/TUI → SootheRunner → StrangeLoop ↔ CoreAgent           │
│                                                            │
│ Status:                                                    │
│   No GoalEngine, no AutopilotService, no dispatch bundle   │
│   LoopRunRequest.autopilot_job = None                      │
│   StrangeLoop runs today's _run_agentic / _run_quiz paths    │
└────────────────────────────────────────────────────────────┘
```

The `soothe --autopilot` / Autopilot CLI path is a **daemon client**: it posts to `/api/v1/autopilot/submit` (or equivalent IPC) and streams progress via WebSocket. Prints a clear error + start-daemon hint if the daemon isn't running.

---

## Configuration

Autopilot host config lives under `agent.autopilot:` (e.g.
`agent.autopilot.enabled`, default `true`).

```yaml
agent:
  loop:
    # Shared StrangeLoop iteration budget (interactive + Autopilot workers)
    max_iterations: 99

  autopilot:
    enabled: true

    # Goal lifecycle / scheduling (not StrangeLoop knobs)
    max_retries: 2
    max_parallel_goals: 16

    # Orchestration
    max_send_backs: 3
    checkpoint_interval: 10

    # Dreaming
    dreaming_enabled: true
    dreaming_consolidation_interval: 300
    dreaming_health_check_interval: 60

    # Scheduler / webhooks
    webhooks: {}

    # Loop pool (RFC-222) — AutopilotService worker management.
    max_loops: 16
    loop_idle_timeout: 300
    poll_interval: 5
    dreaming_poll_interval: 60

    # Context projection (RFC-222 revised) — bounds GoalDispatchContextBundle size.
    context_projection:
      max_findings: 20
      max_effects: 50
      max_plan_steps: 30
      context_retention_hours: 168   # 1 week; per-root-goal eviction (Q3)

    # Workspace reservation (RFC-222 revised) — scheduling-time conflict gate.
    workspace_reservation:
      enabled: true
      strict_overlap: true           # treat any prefix overlap as conflict
```

> Full field list lives in `config/soothe.template.yml` under `agent.autopilot`.
> Production readiness gaps: [IG-678](../archive/impl/IG-678-autopilot-ce-rails-production-readiness.md).

---

## Implementation Phases

**Phase A — additive scaffolding (no behavior change)**
1. Add `GoalDispatchContextBundle` / `GoalDispatchContextContribution` models + tests.
2. Add `AutopilotJob` + extend `LoopRunRequest.autopilot_job: AutopilotJob | None = None`. Existing callers pass `None`; tests unaffected.
3. Add `ContextProjector` + `GoalDispatchContextStore`. Unit tests, no callers yet.
4. Add `WorkerPool` wrapping `LoopRunnerFactory`. Unit tests, no callers yet.
5. Add `WorkspaceReservation`. Unit tests.

**Phase B — wire the new worker path (parallel to old)**
6. `SootheRunner.astream` branches on `autopilot_job`: if set, call new `_run_single_autopilot_goal`; else, today's path. Autopilot-job branch is callable but no production code calls it yet.
7. Daemon-side `AutopilotService` constructed in `SootheDaemon.start()` but `enabled=False` by default. Scheduling loop runs but no goals exist in its DAG.

**Phase C — cutover endpoint-by-endpoint**
8. HTTP `/autopilot/submit` and related endpoints route through live `AutopilotService`.
9. Goals submitted via HTTP flow through daemon's autopilot, get dispatched to workers via `LoopRunRequest(autopilot_job=…)`.
10. Run both paths in parallel for one release. Gather telemetry.

**Phase D — destructive cleanup**
11. Delete `SootheRunner._autopilot_service`. Delete `_execute_goal_via_autopilot`. Delete `_run_autonomous` multi-goal scheduling. Delete `initialize_autopilot`. Migrate `soothe --autopilot` CLI to be a daemon client.
12. Remove `autonomous=True` flag from `SootheRunner.astream` (no caller needs it).

Phases A and B are reversible; C is the cutover; D is irreversible — gated on a release cycle of clean telemetry.

---

## Open Questions (Resolved)

These were debated in the brainstorming session and locked as defaults:

| # | Question | Resolution |
|---|---|---|
| Q1 | File-lock granularity | **Workspace-level for v1.** `WorkspaceReservation` at scheduling time. Path-level deferred; `FileLockMiddleware` and `FileLockRegistry` preserved unwired. |
| Q2 | ContextProjector relevance heuristic | **Simple heuristic for v1** (recency + file overlap). Pluggable for future LLM-scored projection. |
| Q3 | `GoalDispatchContextContribution` eviction | **Per-root-goal + age.** When root reaches terminal state, contributions evictable after `context_retention_hours` (default 168h). LRU-evict if quota exceeded. |
| Q4 | Multi-tenancy | **Reject overlapping-workspace submissions** unless explicit shared-mode opt-in. Cross-tenant authz deferred to its own RFC. |
| Q5 | Solo + autopilot coexistence | **Yes**, with workspace-overlap check. Solo invocations register a transient workspace claim. |
| Q6 | Backoff reasoning | **Async fire-and-forget.** Engine schedules `BackoffReasoner` as a separate task; scheduling loop is non-blocking. |
| Q7 | Autopilot CLI | **Daemon client.** Requires daemon running; posts to `/autopilot/submit`, streams via WebSocket. |
| Q8 | `InternalEventBus` placement | **Drop the singleton `get_internal_bus()`.** Owned by `AutopilotService`; injected to all consumers. |

---

## Out of Scope (Explicit)

- **Distributed multi-daemon autopilot** (DAG sharded across daemons). Single-daemon only. Future RFC.
- **Streaming context updates mid-goal.** Workers emit one `GoalDispatchContextContribution` at end. Mid-flight context checkpointing is a future enhancement.
- **`GoalDispatchContextBundle` / `GoalDispatchContextContribution` schema versioning.** Bump model version; ad-hoc migration.
- **Cost / token-budget enforcement** (production gap H3). Future RFC; this design is the substrate it plugs into.
- **Fine-grained per-path file-lock conflict resolution.** Workspace-level reservation suffices for v1. `FileLockMiddleware` preserved unwired.

---

## Gaps This RFC Closes (from production-readiness analysis)

| Gap | Resolution |
|---|---|
| B1 — Scheduling loop never runs | Daemon owns `AutopilotService.start()` → continuous scheduling. |
| B2 — Two incompatible loop concepts | Resolved by collapsing to one: AutopilotService in daemon, StrangeLoop in worker. |
| B3 — GoalEngine state in-process only | Daemon-owned + `restore_from_durability()`. |
| B4 — File-lock registry per-process | Replaced by daemon-owned `WorkspaceReservation` (Q1). |
| B5 — FileLockMiddleware not installed | Replaced by workspace-level scheduling check (Q1). |
| H4 — No crash recovery for in-flight goals | Reset `active` → `pending` on daemon start; hydrate from `GoalDispatchContextContribution`. |
| H5 — No deadline / hang detection | `AutopilotJob.deadline_seconds` + monitor tick. |
| H8 — Goal cancellation not wired | `autopilot.cancel_goal()` + existing RFC-221 `cancel_event`. |
| M1 — Channel inbox disconnected | Resolved: file-based inbox removed; `/autopilot/submit` and related endpoints require live `AutopilotService`. |
| M9 — No integration tests | Phase C end-to-end test required before cutover. |

Remaining gaps (H1, H2, H3, H6, H7, M2–M8, M10) are deliberately out of scope and tracked for future RFCs.

---

## Guarded Production Pilot (Minimum Bar)

**Status**: Implemented (2026-07-01)

When `agent.autopilot.enabled=true` (the default), the following wiring is required before unattended 24/7 operation. This section tracks the **minimum bar** for a guarded pilot (deadlines, monitoring; set `enabled: false` to opt out).

### Configuration

| Setting | Pilot recommendation | Notes |
|---------|---------------------|-------|
| `agent.autopilot.enabled` | `true` (default) | Master switch; scheduling loop does not start when `false` |
| `goal_deadline_seconds` | `1209600` (14 days) | AutopilotMonitor cancels workers past this wall-clock budget; `null` disables |
| `max_parallel_goals` | tuned to capacity | Service + runner semaphores |
| `verify_interval` | `30` | Active DAG health tick; idle uses `verify_idle_interval` + LLM gate |
| `verify_idle_interval` | `300` | Idle/empty tick; health LLM skipped while idle |

Pydantic default for `enabled` is **`true`** — set `agent.autopilot.enabled: false` to disable the scheduling loop.

### Daemon wiring (implemented)

1. **AutopilotService.start/stop** starts and stops **AutopilotMonitor** background loops (verification + dreaming timer).
2. **submit_task** routes through **AutopilotMonitor.intake_goal** when a monitor is wired (create-first; LLM placement refine runs async); falls back to direct `ContextEngine.create_goal` when no monitor.
3. **Consensus model**: `SootheConfig.create_chat_model("think")` tries the `think` router role, then **`default`** on instantiation failure when specs differ. Router resolution already maps unset `think` → `default`.

### Verification

| Test | Location |
|------|----------|
| Monitor lifecycle + intake routing | `packages/soothe/tests/unit/core/autopilot/test_monitor_lifecycle.py` |
| think→default model fallback | `packages/soothe/tests/unit/config/test_create_chat_model_fallback.py` |
| Enabled daemon starts scheduling + monitor | `packages/soothe-daemon/tests/integration/autopilot/test_autopilot_enabled_startup.py` |
| Real dispatch E2E (fake runner) | `packages/soothe/tests/unit/core/autopilot/test_real_dispatch.py` |

### Explicitly deferred (post-pilot)

- Full dreaming distillation persistence (procedure / semantic / profile modes)
- Backoff decision application in AutopilotMonitor
- Webhook notifications
- Token-budget enforcement (gap H3)
- Per-loop solo/autopilot toggle (removed; use `/autopilot` job submit + `agent.autopilot.enabled`)

### Production gaps from long-running eval (2026-08-04)

Tracked in [IG-680](../archive/impl/IG-680-autopilot-dag-health-evidence-deps.md) (not
optional soak — these break job-status honesty):

| Gap | Impact | Fix home |
|-----|--------|----------|
| Subgoals omit `parent.workspace` | Workers write under `~/.soothe/data/workspaces/anonymous/ws_*` while the job workspace is the client path; consensus rejects “wrong” paths | IG-680 P0-3; RFC-625 errata |
| `GoalDispatchContextContribution.effects` empty | Child hydration lacks prior side-effect claims (consensus still uses sloop response — IG-710) | IG-712; StrangeLoop assess emits effects when done |
| DAG health auto-cancels umbrella roots | Job status `cancelled` despite workspace success | IG-680 P0-1; RFC-625 remove policy |
| Flat `depends_on` after decompose | Test/review race implement | IG-680 P1; RFC-625 `wire_dependencies` |

**Invariant addendum:** When `AutopilotJob.workspace` (or root `GoalNode.workspace`)
is set, every descendant created by monitor/health/worker decompose MUST inherit
that workspace unless an intake explicitly overrides it. Workspace reservation
still gates overlapping **distinct** workspaces; same-job children share one
reservation key via the inherited path.

---

## References

- RFC-000: System Conceptual Design
- RFC-200: Goal Management and Backoff Authority
- RFC-201: StrangeLoop Plan-Execute Loop Architecture
- RFC-204: Goal File Discovery & Status Tracking
- RFC-220: LangGraph Loop Orchestrator
- RFC-221: Loop Runner Protocol and Subprocess Isolation
- RFC-403: Event System Architecture
- Design draft: `docs/archive/drafts/2026-05-28-autopilot-loop-unification-design.md`

---

## Changelog

### 2026-05-27 (Draft)
- Initial RFC draft defining Autopilot + GoalEngine architecture
- Internal EventBus specification with `soothe.internal.*` namespace
- Goal-AL exclusive assignment and file lock conflict resolution
- Lineage-aware loop reuse for context preservation
- Solo mode preserved (no GE integration) vs Autopilot mode (GE active)
- Channel and webhook integration patterns

### 2026-05-28 (Revised — daemon-ownership pivot)
- **AutopilotService moved to daemon ownership.** One instance per daemon, constructed at `SootheDaemon.start()`, lifetime = daemon lifetime.
- **StrangeLoop reframed as pure execution unit.** No GoalEngine, no AutopilotService, no DAG view inside subprocess workers.
- **Bounded summarization via `GoalDispatchContextBundle`** replaces lineage-based in-memory continuity. Composes for diamond joins, fan-out, backoff, worker crash. Linear chains still get warm caches via sticky scheduling.
- **`WorkspaceReservation`** replaces `FileLockRegistry` / `FileLockMiddleware` as the conflict gate. Enforced at scheduling time in the daemon. Fine-grained per-path locking preserved unwired (revivable when needed).
- **Job contract** added: `LoopRunRequest.autopilot_job: AutopilotJob | None`. Worker branches on presence; solo callers pass `None`.
- **Stream contract** added: `GoalCompletionChunk` emitted exactly once by worker, consumed by daemon's `_route_chunk`. No new IPC mechanism.
- **`WorkerPool` sticky-affinity wrapper** over `LoopRunnerFactory` (RFC-221). Autopilot ids namespaced as `autopilot__*` and filtered from client subscriptions.
- **Crash recovery** added: scan `active` goals on daemon start, reset to `pending`, re-dispatch.
- **Async backoff reasoning** — `BackoffReasoner` runs as a separate task; scheduling loop is non-blocking.
- **`InternalEventBus` singleton dropped** — bus owned by `AutopilotService`, injected to consumers.
- **`soothe --autopilot` CLI becomes a daemon client.** Legacy in-process multi-goal mode removed.
- Open questions Q1–Q8 explicitly resolved with defaults.

### 2026-07-01 (Guarded production pilot minimum bar)
- Documented **Guarded Production Pilot** section: config recommendations, monitor lifecycle wiring, intake routing, consensus model fallback.
- Implementation: `AutopilotService` starts/stops `AutopilotMonitor`; `submit_task` uses `intake_goal` when monitor wired; `create_chat_model(consensus_model_role)` for daemon consensus model.

### 2026-08-04 (IG-677 Job↔Loop Index)
- Assignment `loop_id` is `autopilot__{job_id}__{uuid}` (unbounded); pool **slots** are separate reusable capacity keys.
- Durable `JobLoopIndex` records job↔loop membership across restarts; live `assigned_loop_id` remains the in-flight pointer only.

### 2026-08-04 (IG-680 eval gaps)
- Documented production gaps: workspace inherit on decompose, consensus evidence
  grounding, health remove guardrails, pipeline `depends_on` wiring.
- Related errata in RFC-625; implementation backlog [IG-680](../archive/impl/IG-680-autopilot-dag-health-evidence-deps.md).

### 2026-08-08 (Report-commit judgment + legacy cleanup)
- Worker completion → CE `commit_goal_report` → `goal_report_committed` is the
  sole Autopilot LLM judgment path (RFC-204 §1.3).
- Retitled to daemon dispatch architecture; normative layer model uses
  ContextEngine / AutopilotMonitor; removed “partially superseded”,
  “historical reference only”, and backward-compat hedges from the body.
- Aligns with design draft
  `docs/archive/drafts/2026-08-08-autopilot-report-commit-judgment-design.md`.

### 2026-08-16 (Goal-report-pair projection)
- **New `preamble_messages` field on `GoalDispatchContextBundle`** carries
  `(GoalReportUserTurn, GoalReportAITurn)` pairs — one per transitive
  ancestor goal, topologically ordered. Additive: the flat `prior_*` fields
  remain for structured consumers (verifier reasoner, consensus, effect
  checks). Formalizes the design draft
  `docs/drafts/2026-08-16-autopilot-goal-dag-pair-projection-design.md`.
- **`ContextProjector` walks the full transitive ancestor subgraph**
  (`depends_on` ∪ `informs`, recursively) with a `visited` cycle guard, and
  topologically sorts ancestors roots-first. The current goal directive
  becomes the final user message. Reuses `build_goal_report` for the AI half.
- **Worker seeds the CE ledger** with the pairs (phase `"preamble"`) via a
  new `run_with_progress(preamble=…)` parameter, after `state.bind_ce` and
  before `pump_graph`. Pairs surface through `loop_messages` automatically
  (RFC-214 ledger SoT); the `"preamble"` phase is excluded from
  `last_ledger_ai_content` so preamble turns are not surfaced as final
  user-facing output.
- **Cap is a fixed constant** (`MAX_PREAMBLE_TURNS = 12` in
  `goal_contracts.py`, enforced by both the projector and
  `GoalDispatchContextBundle._enforce_bounds`), not a config knob.
- **StrangeLoop worker hydration responsibility** updated to call out
  preamble seeding. RFC-214 added as a dependency (loop message ledger).

---

*Daemon-owned AutopilotService composing StrangeLoop workers as fungible executors, enabling 24/7 autonomous goal execution with bounded-summarization context flow, workspace-level conflict gating, and crash recovery — while preserving subprocess isolation (RFC-221) and solo-mode behavior.*
