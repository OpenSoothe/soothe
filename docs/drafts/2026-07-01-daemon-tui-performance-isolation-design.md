# Daemon ↔ TUI Performance Isolation Design

> Multi-client, multi-loop performance program for the Soothe daemon streaming path and TUI consumption pipeline. Prioritizes **correctness (no silent loss)**, then **fairness/capacity**, then **latency**.

**Status**: Approved (quick pass 2026-07-01)  
**Created**: 2026-07-01  
**Dependencies**: [RFC-614](../specs/RFC-614-unified-streaming-messaging.md), [RFC-450](../specs/RFC-450-daemon-communication-protocol.md), [RFC-0013](../specs/RFC-0013-event-bus-architecture.md) (event bus)  
**Builds on**: [IG-533](../impl/IG-533-goal-completion-tui-worker-lifecycle-fixes.md) (stream integrity + worker lifecycle; partially implemented)  
**Incident context**: Loop `019f1b8a-8385-70f1-9248-c40213b8b036` — `done` dropped on full queue → stale busy → delayed synthetic `RuntimeError` (fixed 2026-07-01)

---

## 1. Overview

### 1.1 Problem Statement

Under **multiple clients running intensive work on different loops**, event **routing isolation is correct** (no cross-loop frame leakage), but **performance isolation is weak**. Heavy loop A slows loop B through shared resources:

| Shared resource | Default / size | Effect |
|-----------------|----------------|--------|
| Singleton `ThreadPool` | `max_pool_size: 6` | Hard cap on parallel worker executions |
| `ResponsePusher` semaphore | Global **200** slots | Any slow consumer blocks all worker threads |
| Per-request bridge queue | **maxsize=100** | Worker→main backpressure; terminal frames at risk if full |
| Single daemon asyncio loop | 1 | All coalesce + broadcast + card ingest multiplexed |
| Event bus client queue | **maxsize=10000** | NORMAL priority drops when full |
| Sender batch window | **300ms** (`streaming_interval_ms`) | Adds latency per batch |
| TUI inbound queue | **10000**, drop-oldest | Silent client-side frame loss |

Users experience: incomplete synthesis cards, misleading worker errors, UI gaps/jumps, and long queue waits — even when their loop completed successfully on the daemon.

### 1.2 Success Criteria (priority order)

| Rank | Criterion | ID | Definition |
|------|-----------|-----|------------|
| **1** | No silent event loss | **B** | Every dropped or degraded frame is logged **and** surfaced to the client when user-visible content is affected |
| **2** | Multi-loop fairness & capacity | **A** | N concurrent heavy loops do not cause unbounded cross-loop slowdown or starvation |
| **3** | End-to-end latency | **C** | Time-to-first-chunk and synthesis-visible latency improve without violating B or A |

**Locked priority**: **B → A → C**.

### 1.3 Scope

**In scope**

- Worker → main bridge (`response_bridge.py`, `thread_runner.py`, `pool_runner.py`)
- Query engine hot path (`_process_stream`, `_broadcast_stream_tuple`, coalescer)
- Event bus priority and drop policy (`event/bus.py`)
- Session sender batching (`server/session.py`)
- TUI/SDK consumption (`websocket.py`, `session.py`, turn pipeline)
- Observability and load-test harness

**Out of scope (this program)**

- StrangeLoop / LLM execution logic
- PostgreSQL query optimization (separate track; noted as secondary contention in thread-pool mode)
- Gateway / mizar-airway (IG-533 Phase 4)
- Worker-pool vs thread-pool mode selection (documented as optional Phase 2 escalation, not default)

### 1.4 Non-goals

- Perfect real-time fairness (weighted fair queueing across tenants)
- Zero-copy wire protocol
- Replacing RFC-450 protocol-1 envelopes

---

## 2. Current Architecture

### 2.1 Data flow

```
Worker thread                Daemon asyncio loop              Per client
─────────────                ───────────────────              ──────────
astream() ──► ResponsePusher ──► Queue(100) ──► submit()
                              QueryEngine._process_stream
                                ├─ StreamDeliveryCoalescer
                                ├─ _broadcast_stream_tuple
                                └─ LoopCardManager.ingest
                              EventBus.publish(loop:{id})
                              ClientSession.event_queue(10k)
                              _sender_loop (batch ≤50, ≤300ms)
                              send_to_client → next envelope
                                                    ──► WebSocket
                                                          ──► inbound_queue(10k)
                                                          ──► iter_turn_chunks
                                                          ──► TurnEventPipeline
                                                          ──► Textual UI
```

### 2.2 Isolation guarantees (correctness)

| Boundary | Mechanism |
|----------|-----------|
| Loop routing | `EventBus` topic `loop:{loop_id}`; `_broadcast` requires `loop_id` on client-visible frames |
| Per-client delivery | Separate `ClientSession.event_queue`, `sender_task`, `send_lock` |
| Per-loop input | `LoopInputDispatcher` — one queue per `loop_id` |
| TUI filter | `iter_turn_chunks` drops frames where `event_loop_id ≠ active loop` |

### 2.3 Isolation gaps (performance)

| Gap | Risk |
|-----|------|
| Global `_pending_slots` semaphore | Cross-loop producer blocking |
| `_loop_stream_delivery[loop_id]` | Last subscriber sets coalescing mode for all observers on that loop |
| `_current_query_task` singleton | Ambiguous cancel/timeout under concurrent queries |
| Card ingest on hot broadcast path | Main-loop occupancy scales with chunk rate × loops |
| NORMAL drop at full client queue | Silent synthesis/tool UI loss |

---

## 3. Design Principles

1. **Correctness before throughput** — never drop terminal frames (`done`, `error`, `complete`, `status: idle`); degrade visibly before dropping invisibly.
2. **Scope backpressure** — pressure must apply to the slow scope (loop/client), not globally, where possible.
3. **Measure before tune** — every phase ships metrics and a load harness gate.
4. **Minimal wire churn** — prefer daemon-side and config changes; extend RFC-450/614 only for client-visible degradation signals.
5. **Incremental delivery** — four phases, each independently shippable.

---

## 4. Phased Program

### Phase 0 — Observability & load harness

**Goal**: Make bottlenecks visible; establish regression gates.

#### 4.0.1 Metrics (daemon)

| Metric | Source | Labels |
|--------|--------|--------|
| `soothe_response_bridge_queue_depth` | per-request asyncio queue | `request_id`, `loop_id` |
| `soothe_response_bridge_put_wait_seconds` | time blocked on `queue.put` | `msg_type` |
| `soothe_response_bridge_chunks_dropped_total` | backpressure retry exhaustion | `goal_completion` |
| `soothe_event_bus_dropped_total` | `event/bus.py` | `priority`, `topic` |
| `soothe_session_queue_depth` | `ClientSession.event_queue.qsize()` | `client_id` |
| `soothe_sender_batch_size` | events per WebSocket write | `client_id` |
| `soothe_thread_pool_waiting` | dispatch waiters | — |
| `soothe_thread_pool_busy_workers` | active workers | — |

#### 4.0.2 Metrics (client)

| Metric | Source |
|--------|--------|
| `soothe_ws_inbound_dropped_total` | `WebSocketClient._inbound_dropped` |
| `soothe_turn_time_to_first_chunk_seconds` | TUI turn start → first chunk applied |
| `soothe_turn_synthesis_visible_seconds` | daemon goal complete → TUI card mounted |

#### 4.0.3 Load harness

Location: `packages/soothe-daemon/tests/integration/daemon/test_multi_loop_performance.py` (new).

Scenario:

- **N** synthetic clients, **N** distinct `loop_id`s
- Each runs a grep-heavy turn (replay captured chunk rate or stub runner)
- Duration: ≥5 min wall time
- Assert at SLO (Phase 1 gates):

| Gate | Threshold |
|------|-----------|
| Terminal `done` delivery failures | **0** |
| NORMAL drops without `stream_degraded` client signal | **0** for `goal_completion` tagged frames |
| Cross-loop p95 start delay (loop N vs loop 1) | ≤ **2×** baseline (Phase 2 gate) |

---

### Phase 1 — Correctness (B): no silent loss

**Goal**: User-visible stream integrity; complete turns or explicit degradation.

#### 4.1.1 Worker bridge terminal delivery ✅ (partial)

**Done (2026-07-01)**:

- All `ResponsePusher` deliveries use blocking `await queue.put()` via `_schedule_queue_put`
- `_recover_stale_busy_worker` delivers recovery `done` when worker exits with stale busy state and no `last_error`

**Remaining**:

- Audit `pool_runner.py` for `put_nowait` on terminal messages; align with thread runner
- Add integration test: full queue at synthesis tail → client receives `done`, no synthetic worker error

#### 4.1.2 Event bus: protect synthesis frames

**Problem**: NORMAL priority frames dropped silently when `event_queue` is full (`event/bus.py`).

**Design**:

- Classify `goal_completion` phase (RFC-614) and `status: running|idle` as **non-droppable**
- Options (implement **both** 1.2a + 1.2b):

| Option | Change |
|--------|--------|
| **1.2a** | Promote wire frames with `payload.data.phase == "goal_completion"` to HIGH minimum |
| **1.2b** | Block (not drop) NORMAL only when queue ≥90% **and** frame is user-visible per `decide_client_wire_visibility` |

**Error handling**: If CRITICAL/HIGH block exceeds 30s, log ERROR and emit `stream_degraded` custom event to client.

#### 4.1.3 Client-visible degradation signal

**Wire** (extends RFC-450 custom event via existing `type: event` / `mode: custom`):

```json
{
  "type": "event",
  "loop_id": "...",
  "mode": "custom",
  "data": {
    "type": "stream_degraded",
    "reason": "inbound_queue_overflow",
    "dropped_count": 42,
    "recoverable": true
  }
}
```

**TUI behavior**: Mount a non-blocking banner; offer `/resume` or ledger fetch (IG-533 §1.3).

**SDK**: Increment `_inbound_dropped`; after threshold, send degradation upstream via daemon notification (optional) or local-only banner.

#### 4.1.4 Stream lifecycle fixes (from IG-533)

| Item | Description | Files |
|------|-------------|-------|
| 1.4a | Extend `_POST_IDLE_DRAIN_DEADLINE_S` to 30s (configurable) | `soothe-cli/.../session.py` |
| 1.4b | Cancel in-flight turn on `/clear` before loop switch | `_execution.py`, `commands.py` |
| 1.4c | Ledger fetch fallback on turn abort | `textual_adapter.py`, session helper |

#### 4.1.5 Phase 1 exit criteria

- [ ] Load harness: 0 terminal delivery failures
- [ ] Load harness: 0 silent `goal_completion` drops
- [ ] TUI shows degradation banner when `inbound_dropped > 0` during active turn
- [ ] `/clear` during synthesis does not leave orphan busy workers

---

### Phase 2 — Fairness & capacity (A): partition backpressure

**Goal**: Reduce cross-loop interference without full pipeline rewrite.

#### 4.2.1 Per-worker ResponsePusher semaphore (recommended 2a)

**Change**: Replace global `_pending_slots` with per-`worker_id` semaphore (default **50** slots each).

```python
# Conceptual — worker_id keyed semaphores in response_bridge.py
_worker_pending_slots: dict[str, threading.Semaphore] = {}
_DEFAULT_SLOTS_PER_WORKER = 50
```

**Rationale**: Loop assigned to `thread-worker-2` cannot exhaust loop on `thread-worker-0`'s budget.

**Config** (daemon.template.yml):

```yaml
thread_pool:
  response_pending_slots_per_worker: 50
```

#### 4.2.2 Per-loop in-flight budget (optional 2b)

If 2a insufficient in load tests, add `loop_id → Semaphore` on asyncio side before `_broadcast`:

- Default **80** in-flight chunks per loop toward event bus
- Excess blocks that loop's `submit()` consumer only

#### 4.2.3 Decouple card ingest from hot path

**Change**: `LoopCardManager.ingest_stream_tuple` → `asyncio.create_task` with bounded per-loop queue (max 500); ingest failures logged, never block stream.

**Trade-off**: Cards may lag stream by ≤1s; acceptable for ledger consistency.

#### 4.2.4 Thread pool sizing

- Document `max_pool_size` vs expected concurrent loops in config guide
- Daemon startup log: `ThreadPool: max_pool_size=N, recommend ≥ concurrent heavy loops`
- Optional: expose `thread_pool.metrics` on `daemon_status` RPC

#### 4.2.5 Escalation: worker pool mode

If CPU isolation or crash blast radius required:

- Enable `worker_pool` in daemon config (separate processes, no GIL)
- Out of default path; document in Phase 2 appendix only

#### 4.2.6 Phase 2 exit criteria

- [ ] Load harness N=8: p95 cross-loop start delay ≤ 2× single-loop baseline
- [ ] No worker blocked >30s solely due to another loop's consumer (metric: `response_bridge_put_wait` correlated by `loop_id`)
- [ ] Card ingest p99 lag <2s under load

---

### Phase 3 — Latency (C): tune without violating B/A

**Goal**: Improve perceived responsiveness after correctness and fairness gates pass.

#### 4.3.1 Sender batching

| Knob | Current | Proposed (TUI) | Proposed (headless) |
|------|---------|----------------|---------------------|
| `streaming_interval_ms` | 300 | **100** | 300 |
| `sender_batch_max` | 50 | 50 | 100 |

HIGH/CRITICAL bypass unchanged (IG-436).

#### 4.3.2 Stream delivery mode

| Mode | Use |
|------|-----|
| `adaptive` | **Default** for TUI multi-tenant |
| `streaming` | Debug / latency experiments only |
| `batch` | Headless / log-only consumers |

**Change**: Store `stream_delivery` on `ClientSession`, not `_loop_stream_delivery[loop_id]` — per-client preference.

#### 4.3.3 Synthesis chunk priority

Ensure coalescer output for `phase=goal_completion` registers as HIGH in `EventMeta` before `_broadcast`.

#### 4.3.4 TUI render path

- Profile `run_turn_pipeline` `apply_fn` (Textual mounts)
- Batch DOM updates where textual_adapter mounts multiple widgets per tick
- Keep `_socket_reader_loop` running during turn (revisit cancel in `_execution.py` if dual-consumer issue resolved)

#### 4.3.5 Phase 3 exit criteria

- [ ] p50 time-to-first-chunk ↓ **20%** vs Phase 2 baseline (same harness)
- [ ] p95 synthesis visible within **5s** of daemon `Goal completed` log
- [ ] No regression on Phase 1 drop gates

---

## 5. Deep Analysis: Hidden Bottlenecks & New Optimization Opportunities

> **Beyond the phased program above**, this section documents bottlenecks discovered through code-level analysis that represent **future optimization opportunities** once Phase 1-3 gates pass.

### 5.1 QueryEngine Hot Path: `_broadcast_stream_tuple` Multiplicity

**Current flow** (per chunk):
1. `coalescer.ingest()` → returns 0-N output tuples
2. For each output tuple → `_broadcast_stream_tuple()`
3. `_broadcast_stream_tuple` → `d._broadcast()` → `EventBus.publish()`
4. `EventBus.publish()` → iterates all subscriber queues → `put_nowait` or blocking `put`

**Hidden bottleneck**: A single chunk can trigger **multiple broadcasts** (coalescer flushes, tool batches, goal_completion blocks). Each broadcast iterates all subscribers and performs queue operations. Under N concurrent loops with M subscribers each, this is O(N×M) queue operations per chunk.

**Optimization opportunity (Phase 4 candidate)**:

| Approach | Description |
|----------|-------------|
| **Batched broadcast** | Collect all output tuples from one `ingest()` call, emit single batched envelope to `EventBus` |
| **Subscriber queue pooling** | Use `asyncio.gather` for concurrent `put_nowait` instead of sequential iteration |
| **Zero-copy subscriber dispatch** | For same-loop subscribers, pass envelope reference instead of copying |

**Estimated impact**: 15-25% reduction in daemon-side latency under 4+ concurrent loops.

### 5.2 TUI Apply Path: Widget Mount Storms

**Analysis of `textual_adapter.py`** (3666 lines, `_apply_turn_chunk` in `execute_task_textual`):

The `_apply_turn_chunk` callback runs for **every stream chunk** and performs:
- Message parsing and normalization
- Tool-call state ingestion (`ingest_tool_call_stream_state`)
- Widget mounting (`_mount_message` → async Textual DOM mutation)
- Step-card updates (multiple `set_tool_running`, `update_tool_args`)
- Token accounting (`record_token_usage` → widget update)
- File preview mounting (`mount_file_change_preview`)

**Hidden bottleneck**: Each chunk can trigger **multiple async widget operations**. Textual DOM mutations serialize on the app's event loop. Under high chunk rates (streaming synthesis), the TUI event loop saturates with DOM work, causing:
- Delayed `read_event()` calls → SDK inbound queue fills → drops
- Missed heartbeat responses → false connection-loss detection

**Optimization opportunity (Phase 4 candidate)**:

| Approach | Description |
|----------|-------------|
| **Chunk batching at apply boundary** | Collect N chunks (e.g., 5-10) before calling `_apply_turn_chunk`; reduces DOM mutations per second |
| **Widget update coalescing** | Track dirty widgets, batch `set_tool_*` calls into single refresh per render tick |
| **Mount deferral** | Queue new widget mounts, flush on next Textual `on_idle` callback instead of inline |
| **Apply path offload** | Run non-UI work (parsing, token accounting) in `asyncio.to_thread`, only DOM work on main loop |

**Estimated impact**: 30-40% reduction in TUI-side latency under dense tool-call streams.

### 5.3 Card Binding Synchronous Block

**Analysis of `LoopCardManager._flush_buffers_to_ledger`**:

```python
async def _flush_buffers_to_ledger(self, loop_id: str, state: _BindingBuffers) -> None:
    cards = await asyncio.to_thread(self._bind_cards, state.messages, state.log_events)
    ledger = await self._open_ledger(loop_id)
    mutations = cards_to_mutations(cards) if cards else []
    if mutations:
        await ledger.replace_with(mutations)
```

**Hidden bottleneck**: `asyncio.to_thread` offloads to a thread pool, but:
1. Thread pool has finite workers (default `min(32, os.cpu_count() + 4)`)
2. Card binding involves `card_binder.convert_messages_to_data` which parses all accumulated messages
3. `ledger.replace_with` writes to disk (JSONL append)

Under N concurrent loops, all loops compete for the same thread pool → queue builds → blocks hot path.

**Current mitigation in Phase 2.3**: `asyncio.create_task` with bounded queue.

**Optimization opportunity (Phase 4 candidate)**:

| Approach | Description |
|----------|-------------|
| **Dedicated card-bind thread pool** | Separate thread pool (2-4 workers) for card binding, isolated from general `to_thread` pool |
| **Incremental binding** | Bind only new messages since last flush, not full accumulated state |
| **Lazy persistence** | Batch mutations in memory, persist only on turn end or explicit request |
| **Ledger append-only** | Replace `replace_with` with incremental append (no full file rewrite) |

**Estimated impact**: 10-15% reduction in daemon main-loop occupancy under 4+ concurrent loops.

### 5.4 WebSocket Reader → Inbound Queue Drop Chain

**Analysis of `WebSocketClient._socket_reader_loop`**:

```python
async def _socket_reader_loop(self) -> None:
    while self._connected and self._ws is not None:
        event = await self._read_from_socket()
        # ...
        await self._enqueue_inbound(event)

async def _put_inbound_queue(self, event: dict[str, Any] | None) -> None:
    if self._inbound_queue.full():
        with contextlib.suppress(asyncio.QueueEmpty):
            self._inbound_queue.get_nowait()  # Drop oldest!
        self._inbound_dropped += 1
    await self._inbound_queue.put(event)
```

**Hidden bottleneck**: Drop-oldest policy drops **oldest frames** (possibly terminal `done`, `idle`) to make room for new frames. This is the opposite of the daemon's drop-newest NORMAL policy. A slow TUI processing a dense tool-call stream can accumulate backlog → oldest (which may be earlier `status: running` or goal_completion chunks) get dropped → UI shows incomplete synthesis even though daemon delivered correctly.

**Optimization opportunity (Phase 4 candidate)**:

| Approach | Description |
|----------|-------------|
| **Priority-aware drop-oldest** | Inspect frame type before drop; never drop terminal/goal_completion frames |
| **Drop-newest for NORMAL** | Align with daemon policy — drop newest NORMAL when full, preserve oldest terminal |
| **Two-tier inbound queue** | HIGH/CRITICAL frames → dedicated small queue (never drops); NORMAL → main queue (drop-newest) |
| **Adaptive drain** | When queue >80%, trigger aggressive early filtering (`should_drop_stream_chunk_early`) |

**Estimated impact**: Eliminates "synthesis missing but daemon says complete" class of bugs.

### 5.5 EventBus Lock-Free Publish: Subscriber Set Copy

**Analysis of `EventBus.publish`**:

```python
async def publish(self, topic: str, event: dict[str, Any], event_meta: EventMeta | None = None) -> None:
    # NO LOCK! Direct dict read (atomic in Python) - IG-258 Phase 2
    queues = self._subscribers.get(topic, set()).copy()  # <-- COPY!
    
    for queue in queues:
        # ... per-queue operations
```

**Hidden bottleneck**: `.copy()` creates a new set object on every publish. For hot topics (`loop:{active_loop}` with potentially 10+ subscribers for same loop across multiple clients), this allocates a new set N times per second (where N = chunk rate).

**Optimization opportunity (Phase 4 candidate)**:

| Approach | Description |
|----------|-------------|
| **Frozen subscriber set** | Store subscribers as immutable tuple; replace on subscribe/unsubscribe (amortized copy) |
| **Subscription versioning** | Track version number; only re-fetch subscriber list when version changes |
| **Direct iteration without copy** | Rely on Python's atomic dict read + set iteration safety (subscribers cannot mutate during iteration since publish is reader operation) |

**Estimated impact**: Minor but measurable (~5% under very high chunk rates).

### 5.6 Coalescer Ingest: Per-Chunk Time.Monotonic Calls

**Analysis of `StreamDeliveryCoalescer.ingest`**:

```python
def ingest(self, namespace: tuple[str, ...] | list[str], mode: str, data: Any) -> list[...]:
    ns = tuple(namespace) if namespace else ()
    now = time.monotonic()  # <-- Called on every chunk!
    out_prefix = self._flush_due_tool_batches(now)
    out_prefix.extend(self._maybe_flush_goal_completion_block(now))
```

**Hidden bottleneck**: `time.monotonic()` is a system call. Called on every chunk for flush checks. Under 100+ chunks/second (dense streaming), this adds measurable overhead.

**Optimization opportunity**:

| Approach | Description |
|----------|-------------|
| **Batched monotonic** | Pass `now` from caller (`_process_stream`) instead of per-ingest call |
| **Lazy flush check** | Only call `monotonic` every N chunks (e.g., 10) or when `last_flush_count` changes |

**Estimated impact**: Minor (~2-3%), but simple to implement.

### 5.7 Thread Runner: Per-Chunk Cancel Poll

**Analysis of `_thread_worker_body` cancel polling**:

```python
async def _poll_cancel_event() -> None:
    try:
        while True:
            await asyncio.sleep(0.25)  # <-- Wake up every 250ms
            if cancel_event.is_set():
                stream_task.cancel()
                return
    except asyncio.CancelledError:
        raise
```

**Hidden bottleneck**: Every worker thread's asyncio loop has a cancel-poll task that wakes every 250ms. With N=8 workers, that's 32 wakeups/second just for cancel polling, even when no work is running.

**Optimization opportunity**:

| Approach | Description |
|----------|-------------|
| **Event-driven cancel** | Use `threading.Event.wait(timeout)` in worker thread, signal via `call_soon_threadsafe` to cancel stream task |
| **Cancel on demand** | Only spawn poll task when `cancel_event` is actually being monitored (daemon requested cancel) |
| **Longer poll interval** | Increase to 500ms or 1s for non-critical paths |

**Estimated impact**: Minor CPU reduction on idle workers.

---

## 6. Component Changes Summary

| Component | Phase | Change |
|-----------|-------|--------|
| `response_bridge.py` | 1 ✅, 2a | Blocking terminal put; per-worker semaphores |
| `thread_runner.py` | 1 ✅ | Stale busy recovery |
| `pool_runner.py` | 1 | Terminal put parity |
| `event/bus.py` | 1 | Synthesis non-drop policy |
| `query/engine.py` | 2b, 3 | Optional per-loop budget; HIGH meta for synthesis |
| `server/session.py` | 2, 3 | Per-client stream_delivery; batch tuning |
| `soothe_sdk/.../websocket.py` | 1 | Degradation signal hook |
| `soothe-cli/.../session.py` | 1 | Drain extension; degradation UI |
| `soothe-cli/tui/...` | 1, 3 | `/clear` cancel; render batching |
| `config/daemon.template.yml` | 0–3 | New knobs documented |

---

## 7. Error Handling

| Failure | Detection | User-visible | Recovery |
|---------|-----------|--------------|----------|
| Bridge queue full (chunk) | `put` blocks; metric | None if eventually delivered | Backpressure slows producer |
| Bridge terminal lost | Should not occur post-Phase 1 | N/A | Recovery `done` on stale busy |
| Event bus NORMAL drop | `event_bus_dropped_total` | `stream_degraded` if user-visible | Retry message; `/resume` |
| Client inbound drop-oldest | `_inbound_dropped` | Banner in TUI | Ledger fetch |
| Thread pool saturated | `thread_pool_waiting > 0` | Queue position in status (optional) | Wait or cancel |
| Sender blocked on WS | `send_lock` wait metric | Connection slow warning | Client reconnect |

---

## 8. Testing Strategy

| Level | Coverage |
|-------|----------|
| Unit | `response_bridge` full-queue `done`; per-worker sem; event bus priority promotion |
| Integration | Multi-loop load harness; no leakage (existing) + performance gates (new) |
| Manual | 3 TUI clients, parallel log-grep turns; verify synthesis cards complete |

Run `./scripts/verify_finally.sh` before any commit.

---

## 9. Rollout

1. **Phase 0** — metrics + harness (no behavior change)
2. **Phase 1** — ship remaining B items behind no flags (correctness)
3. **Phase 2a** — per-worker semaphore (config default on)
4. **Phase 2b** — per-loop budget only if harness fails 2a gate
5. **Phase 3** — config tuning + per-client stream_delivery

Rollback: revert per-phase; Phase 1 terminal delivery must not roll back.

---

## 10. Spec / IG Routing

| Artifact | Action |
|----------|--------|
| **RFC-614** | Amend: synthesis priority, per-client `stream_delivery`, degradation interaction with coalescer |
| **RFC-450** | Amend: `stream_degraded` custom event schema; optional `daemon_status` pool metrics |
| **IG-533** | Extend Phase 3.1 (backpressure) with Phase 1–2 items not yet done |
| **IG-534** (new) | Performance isolation implementation guide (Phases 0–3) |
| Load harness | Part of IG-534 or `tests/integration/daemon/` |

---

## 11. Open Questions

1. **Per-loop budget default (2b)** — 80 in-flight vs tied to `response_queue maxsize`?
2. **Degradation on daemon vs client only** — should daemon emit `stream_degraded` when **its** queue drops, or only client when inbound drops?
3. **Worker pool escalation** — document threshold (e.g. N>8 sustained) for ops to switch modes?
4. **Phase 4 prioritization** — which of §5's hidden bottlenecks should be tackled first after Phase 1-3 complete?

---

## 12. Decision Log

| Date | Decision |
|------|----------|
| 2026-07-01 | Priority order locked: **B → A → C** |
| 2026-07-01 | Phase 2a first (per-worker semaphore); 2b conditional on harness |
| 2026-07-01 | Terminal `done` must use blocking put (implemented) |
| 2026-07-01 | Document hidden bottlenecks (§5) for future Phase 4 consideration |