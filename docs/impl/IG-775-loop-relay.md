# IG-775: LoopRelay — Standalone Interrupt/Relay/Resume Bridge

**Created**: 2026-09-06
**Status**: In progress
**Related**: RFC-622 (clarification relay), RFC-904 (sloop recursive decomposition),
IG-760 (reentrant loop state), IG-763 (ask_user in-thread continuation),
IG-765 (unify ask_user + interrupt_on relay paths), IG-768 (clarification fail-fallback)

## Problem

The interrupt / relay / resume path between the StrangeLoop graph and the
CoreAgent graph is scattered across six locations with **no single owner**:

1. `clarification/capture.py` — `ClarificationQueue` + `ResumeTicket` (FIFO)
2. `clarification/origins.py` — origin taxonomy + resume-node mapping
3. `engine/execute/graph_interrupt.py` — `build_*_resume_payload`, `is_*_interrupt`
4. `engine/execute/executor.py:955-994` — the `GraphInterrupt` capture site
5. `stations/sidecars/await_user.py` — `node_await_clarification` (policy dispatch)
6. `orchestrator/{runner,checkpoint,routing}.py` + `plans/plan_mode_review.py`
   — resume commands, thread-id grammar, origin routing, scratch projection

Three coexisting "park" vocabularies (LangGraph `interrupt()`,
`park_for_clarification` + `mark_goal_awaiting_clarification`,
`mark_goal_interrupted`) and four resume payload shapes converge on the same
ad-hoc graph channels (`pending_clarification`, `clarification_queue`,
`resume_ticket`, `clarification_resume_tickets`, `last_clarification_origin`).

The empty `sloop/relay/` directory (src + tests, only stale `__pycache__`) is
the gap this IG fills — the relay mechanism was removed or never landed.

### Fragilities

1. **`LoopPhaseScratch` is not serialized by LangGraph**
   (`orchestrator/runtime_context.py:57`). On every `ainvoke` — including
   clarification-resume turns — it is rebuilt heuristically (~140 lines in
   `stations/execute/execute.py:481-622`); `hydrate_scratch_from_pending`
   is the inverse projection. A worker crash mid-park loses anything not
   mirrored into a graph channel.
2. **No typed CoreAgent→StrangeLoop relay channel.** Interrupts flow via
   exception catch + a shared mutable `ClarificationQueue` on
   `LoopRuntimeContext`. Not auditable, not concurrency-guarded.
3. **Event emission is informal** — `step_started`, `clarification_requested`,
   `fatal_error`, `goal_unblocked` are raw strings via `ctx.emit`, not
   registered in `events/catalog.py`.
4. **Concurrency unguarded at the relay level.** The daemon's per-loop worker
   (`LoopInputDispatcher`) enforces one-worker-per-loop, but nothing prevents
   two parallel step threads from racing the same resume, and a stale resume
   (post worker crash + re-dispatch) is not detected.

## Goal

A single, typed, auditable `LoopRelay` object per StrangeLoop run that owns the
full **interrupt → park → resume** lifecycle between the two graphs:

- **Reliable relay**: one capture site, one resume site, one durable channel.
- **Interrupt + resume**: survives worker crash/restart via graph-channel
  projection; rehydrates on a fresh worker (Rule 15 — reentrant loop state).
- **Concurrency-safe**: per-fork-thread `asyncio.Lock` serializes resume per
  thread; parallel across threads. Stale-resume detection via snapshot diff.
- **Origin-aware routing**: every captured interrupt reaches its correct
  resume node (`EXECUTE` vs `PLAN_REVIEW`) and payload shape.
- **Robust to errors**: every capture/resume wrapped → typed `RelayError`
  outcomes routed to `AWAIT_USER` (park) or `FINALIZE` (fail); append-only
  audit log for `diagnose-loop`.
- **Single reentrancy boundary**: the relay owns BOTH interrupt state AND
  `LoopPhaseScratch` projection — fixes fragility #1 directly.

## Design

### Placement

`packages/soothe/src/soothe/sloop/relay/` — the already-existing empty
directory. Stays in the `soothe` package (both StrangeLoop and CoreAgent
host wrapper live here; per `package-boundaries.md`).

### Module layout

```
sloop/relay/
├── __init__.py     # re-export LoopRelay only (Rule 16 — minimum exposure)
├── relay.py        # LoopRelay: capture/route/resume/project/hydrate/snapshot/resume_slot
├── inbox.py        # RelayInbox FIFO (absorbs ClarificationQueue + QueuedClarification)
├── outbox.py       # Command(resume=...) builders (absorbs build_*_resume_payload + is_*_interrupt)
├── router.py       # OriginRouter: origin → resume_node + pause mode (absorbs resume-node mapping)
├── channel.py      # RelayChannel: single projection of inbox+scratch → relay_state (absorbs build_plan_mode_review_pending + hydrate_scratch_from_pending)
├── ticket.py       # ResumeTicket (moved from clarification/capture.py — single owner)
├── events.py       # relay event constants (registered in events/catalog.py)
├── errors.py       # RelayError hierarchy
├── snapshot.py     # RelaySnapshot + snapshot predicates (absorbs snapshot_has_*)
└── _adapter.py     # private LangGraph Command/interrupt adapters (no user surface)
```

### Graph channel change (`orchestrator/stations.py`)

Add a single typed channel; remove the six ad-hoc ones it replaces:

```python
class LoopGraphState(TypedDict, total=False):
    # ... unchanged route/outcome channels ...
    relay_state: dict[str, Any] | None   # single projection target (IG-775)
    # Removed (big-bang, no compat shims):
    #   pending_clarification, pending_clarification_answer,
    #   last_clarification_origin, clarification_queue,
    #   clarification_resume_tickets, resume_ticket
    # Kept (not relay-owned): tool_approval_allowlist, plan_approved_follow_on,
    #   plan_rejected_terminal, plan_refinement_requested, after_record_route,
    #   interaction_mode, intake_label
```

`relay_state` carries: serialized inbox (FIFO of `QueuedClarification`),
active origin/route, head `ResumeTicket`, `ScratchProjection` (serializable
subset of `LoopPhaseScratch`: `plan_result`, `decision`, `plan_draft_path`,
`plan_draft_markdown`, `plan_review_comments`, `decompose_proposals`,
`follow_on_exec`, `plan_rejected` — NOT `iteration_perf_start` (ephemeral
timer) or `step_results` (CE-backed)). Append-only audit log.

### Core contract (`relay/relay.py`)

```python
class LoopRelay:
    """Single typed bridge between the StrangeLoop and CoreAgent graphs.

    Owns the full interrupt → park → resume lifecycle for one StrangeLoop
    run. Reentrant across worker exits: all state is projected to the
    ``relay_state`` graph channel before parking and rehydrated on resume.
    """

    def __init__(self, *, loop_id: str, emit: Callable[[str, Any], Awaitable[None]]): ...

    # --- capture (CoreAgent → StrangeLoop) ---
    async def capture_interrupt(
        self, *, exc: GraphInterrupt, origin: ClarificationOrigin,
        ticket: ResumeTicket, step_id: str | None,
        detector: ClarificationDetector, loop_state_view: LoopStateView,
    ) -> CaptureOutcome: ...

    # --- route (after capture) ---
    def route_captured(self) -> RouteDecision: ...

    # --- resume (StrangeLoop → CoreAgent) ---
    @asynccontextmanager
    async def resume_slot(self, ticket_id: str) -> AsyncIterator[None]: ...

    async def build_resume_command(
        self, *, answer: ClarificationAnswer,
    ) -> Command: ...

    # --- reentrancy (Rule 15) ---
    def project_to_channels(self, state: LoopGraphState) -> LoopGraphState: ...
    def hydrate_from_channels(self, state: LoopGraphState) -> None: ...
    def snapshot(self) -> RelaySnapshot: ...
```

### Concurrency

- `dict[str, asyncio.Lock]` keyed by `ResumeTicket.thread_id` in
  `resume_slot(ticket_id)`. Serializes resume per fork thread; parallel
  across threads (matches the parallel-step model in `executor.py`).
- `build_resume_command` compares the head ticket against the snapshot
  captured at park time; raises `RelayStaleInterrupt` → caught →
  `relay_stale_interrupt_skipped` event → route to `DISPATCH` (treat as
  resolved). Survives worker crash + re-dispatch.

### Error routing

| Error | Cause | Loop route |
|---|---|---|
| `RelayStaleInterrupt` | head no longer matches snapshot | `DISPATCH` (skip + log) |
| `RelayConcurrentResume` | per-thread lock held by another worker | no-op return |
| `RelayResumeMismatch` | answer shape ≠ origin shape | `AWAIT_USER` (re-ask) |
| capture parse fail | malformed `GraphInterrupt` | `FINALIZE` (fatal `StepExecutionRecord`) |

### What stays in `clarification/`

The policies are *decision logic* (how to answer), not relay mechanics
(how to capture/route/resume). They import relay types and stay put:

`interactive.py`, `auto.py`, `protocol.py` (`ClarificationRequest` +
`ClarificationAnswer` + `ClarificationPolicy` + `(de)serialize` helpers),
`detector.py` (`ClarificationDetector.detect` — post-IG-765 single entry),
`tool_approval_pipeline.py`, `interrupt_rules.py`, `tool_rule_matcher.py`,
`selector.py`, `runtime_factory.py`, `events.py`.

`origins.py` origin *constants* (`ORIGIN_EXECUTE`, `CLARIFICATION_ORIGINS`,
`ClarificationOrigin`, `DEFAULT_FORCE_MANUAL_ORIGINS`,
`PLAN_MODE_REVIEW_INTERRUPT_PREFIX`) stay — they are shared taxonomy consumed
by policies. Only the resume-node mapping
(`resume_node_for_clarification_origin` + `CLARIFICATION_ORIGIN_RESUME_NODE`)
moves to `relay/router.py`.

### What is preserved unchanged

- **IG-763 thread isolation** (`executor.py:394-402`): the relay does NOT
  touch how CoreAgent is invoked — only how interrupts are captured/routed/
  resumed. `strip_parent_checkpoint_coordinates` stays.
- **Thread-id grammar** (`orchestrator/checkpoint.py:20-100`): the
  constructors (`strange_loop_thread_id`, `execute_step_thread_id`, etc.)
  stay; the relay consumes their output.
- **`GraphStreamChunkReader`** (`engine/execute/graph_interrupt.py`): the
  stream reader + `DispatchTimeoutError` + `_classify_stream_chunk` stay
  (they are stream mechanics, not relay mechanics). Only the payload
  builders + `is_*_interrupt` move to `relay/outbox.py`.
- **`mark_goal_interrupted`** (user-cancel cursor) and
  **`mark_goal_awaiting_clarification`** (CE park): the relay calls these
  via `LoopRuntimeContext.park_for_clarification`; it does not replace them.

## Migration (big-bang, single PR)

Per operator decision: absorb all six pieces in one pass, no facade phase.
Risk mitigation: each absorbed piece is gated by an existing test that must
pass unchanged after the move; `verify_finally.sh` runs after each absorption
chunk (not just at the end).

### Order

1. Create `relay/` module: `errors`, `ticket`, `inbox`, `outbox`, `router`,
   `snapshot`, `channel`, `_adapter`, `events` registration.
2. `relay.py` + `__init__.py` (the orchestrator + minimum-exposure export).
3. Add `relay_state` channel to `LoopGraphState`; remove the six ad-hoc
   channels.
4. Move `ResumeTicket`/`ClarificationQueue`/`QueuedClarification` →
   `relay/{ticket,inbox}.py`; delete `clarification/capture.py`.
5. Move `build_*_resume_payload`/`is_*_interrupt`/`_answer_to_decision` →
   `relay/outbox.py`.
6. Move `resume_node_for_clarification_origin`/`CLARIFICATION_ORIGIN_RESUME_NODE`
   → `relay/router.py`.
7. Move `build_plan_mode_review_pending`/`hydrate_scratch_from_pending` +
   `ScratchProjection` → `relay/channel.py`.
8. Move `snapshot_has_*` predicates → `relay/snapshot.py`.
9. Rewire call sites: `executor.py:955` (capture), `await_user.py` (route +
   resume), `runner.py` (`_clarification_resume_command` → relay),
   `plan_mode_review.py` (project/hydrate via relay),
   `stations/execute/execute.py:481-622` (scratch rebuild → relay hydrate),
   `runtime_context.py` (`park_for_clarification` calls relay project).
10. Wire per-thread lock + stale-check + audit log into `LoopRelay`.
11. Cleanse: delete `clarification/capture.py`; trim `clarification/__init__.py`
    re-exports; remove dead imports.
12. Tests in `packages/soothe/tests/unit/core/loop/relay/`.
13. `./scripts/verify_finally.sh` to green.

## Files

**New** (under `packages/soothe/src/soothe/sloop/relay/`):
`__init__.py`, `relay.py`, `inbox.py`, `outbox.py`, `router.py`, `channel.py`,
`ticket.py`, `events.py`, `errors.py`, `snapshot.py`, `_adapter.py`.

**New tests** (under `packages/soothe/tests/unit/core/loop/relay/`):
`test_relay_capture.py`, `test_relay_resume.py`, `test_relay_router.py`,
`test_relay_channel.py`, `test_relay_concurrency.py`, `test_relay_errors.py`,
`test_relay_snapshot.py`, `test_relay_scratch_projection.py`.

**Modified**:
- `orchestrator/stations.py` — add `relay_state`, remove six channels.
- `engine/execute/executor.py` — capture site calls `relay.capture_interrupt`.
- `engine/execute/graph_interrupt.py` — payload builders move to `relay/outbox.py`.
- `stations/sidecars/await_user.py` — calls `relay.route_captured` + `relay.build_resume_command`.
- `stations/execute/execute.py` — scratch rebuild → `relay.hydrate_from_channels`.
- `plans/plan_mode_review.py` — `build_*`/`hydrate_*` move to `relay/channel.py`.
- `orchestrator/runner.py` — `_clarification_resume_command` delegates to relay.
- `orchestrator/runtime_context.py` — `park_for_clarification` calls relay project.
- `orchestrator/checkpoint.py` — `snapshot_has_*` move to `relay/snapshot.py`.
- `clarification/__init__.py` — trim re-exports.
- `events/catalog.py` — register relay events.

**Deleted**:
- `clarification/capture.py` (absorbed by `relay/{ticket,inbox}.py`).

## Verification

`./scripts/verify_finally.sh` — zero lint, all tests green. The existing
`test_ask_user_and_interrupt_on_e2e.py` (9 cases), `test_cancel_then_retry_resume.py`,
`test_interrupt_resume_hydrate.py`, `test_checkpoint_isolation_resume.py`,
`test_clarification_routing.py`, `test_clarification_queue.py`, and
`test_loop_agent_clarification_round_trip.py` must pass unchanged — they
are the regression gates for IG-763, IG-765, and Rule 15 reentrancy.
