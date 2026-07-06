# IG-550: High-Performance Persistence Optimization

**Guide**: IG-550  
**Title**: High-Performance StrangeLoop + ContextEngine Persistence  
**Created**: 2026-07-06  
**Status**: Complete  
**Related RFCs**: RFC-803 (StrangeLoop checkpoint backend), RFC-624 (ContextEngine lifecycle), RFC-225 (loop continuity)  
**Related IGs**: [IG-523](IG-523-async-checkpoint-writing.md), [IG-529](IG-529-soothe-home-persistence-consolidation.md), [IG-549](IG-549-loop-worker-goal-boundary-hardening.md)  
**Incident loops**: `0b37` (`019f3543-de29-7bb1-9e6a-487262690b37`)  
**Logs**: `~/.soothe/logs/soothe.log`, `~/.soothe/logs/daemon.log`, `~/.soothe/data/loops/<loop_id>/runner.log`

---

## Executive Summary

RFC-803 Phase 6 async checkpoint writes reduced **iteration-boundary** latency, but persistence is still **not high-throughput or non-blocking at goal boundaries and worker shutdown** — the paths where durability matters most.

Loop `0b37` demonstrated the gap:

| Layer | Observed | Expected for “high-perf persist” |
|-------|----------|----------------------------------|
| Goal completion report | Generated + CE ledger saved | ✓ |
| Checkpoint index (`agentloop_checkpoints`) | `goal_4` stuck `running` | Should be `completed` + `idle` |
| Worker request | Hung **84 min** in `close()` after graph finished | Should return within seconds |
| Daemon | `RuntimeError: Request exceeded 7200s timeout` | Should not depend on outer timeout |

**Goal**: Make persistence **fast on the hot path**, **durable on goal boundaries**, and **bounded on shutdown** — without multiplying PostgreSQL connections or rewriting full JSON blobs on every flush.

---

## Problem Statement

### 1. “Async” only applies to non-critical writes

| Call site | Current behavior |
|-----------|------------------|
| `record_iteration()` | `save()` → enqueue, returns fast |
| `finalize_goal()` | `save()` + **`force_flush()`** → sync write under global lock |
| `close()` | drain queue synchronously + **`force_flush()`** — **no timeout** |

Critical operations still block on PostgreSQL. Async mode optimizes iteration checkpoints but not goal finalize or worker teardown.

**Files**: `sloop_manager.py` (`save`, `force_flush`, `finalize_goal`, `close`)

### 2. Full-document rewrite on every flush

Each checkpoint write:

1. `model_dump()` entire `StrangeLoopCheckpoint`
2. `json.dumps()` full blob
3. `UPSERT` whole `checkpoint_data` JSONB row

CE persistence mirrors this: full DAG + full ledger UPSERT on every `ce.save()`.

Cost grows with `goal_history` and ledger size (~91 KB ledger for loop `0b37` with 5 goals). No delta writes, no latest-wins coalescing in the queue.

**Files**: `postgres_backend.py`, `pgsql_backend.py`, `context/engine.py`

### 3. Three independent write pipelines, one database

All target `soothe_checkpoints`:

| Pipeline | Driver | Pool model |
|----------|--------|------------|
| StrangeLoop checkpoint | psycopg | Shared `sloop_pool_size` (default 24) |
| ContextEngine DAG + ledger | asyncpg | **Per-loop pool** min 2 / max 10 |
| LangGraph checkpointer | psycopg | `checkpointer_pool_size` (default 24) |

At goal completion, tail persistence runs **sequentially**:

```
ce.save()           → 2 UPSERTs (dag + ledger)
finalize_goal()     → checkpoint UPSERT + force_flush
```

Connection contention and pool exhaustion (`PoolTimeout` after `DiskFull` in `0b37`) are predictable under load.

**Files**: `shared_pool.py`, `context/persistence/factory.py`, `context/persistence/pgsql_backend.py`

### 4. Per-request flush worker churn

Each daemon request (one user goal) in thread-pool mode:

1. Starts async flush worker
2. Enqueues iteration saves during graph run
3. **`close()`** stops worker + sync-drains queue + force_flush

Five goals on loop `0b37` ⇒ five start/stop cycles. This is buffer churn, not sustained pipelined throughput.

**Files**: `strange_loop.py`, `sloop_manager.py`

### 5. Unbounded shutdown blocking

`_stop_flush_worker()` drains the queue with `await _do_save_checkpoint(queued)` per item — **no timeout**. When PostgreSQL is unhealthy (`DiskFull`, closed pool), `close()` can block until the daemon’s **7200s request timeout**.

In `0b37`: graph finished 12:17:23, worker released 13:41:38 (exactly 7200s from request start).

**Files**: `sloop_manager.py`, `thread_runner.py`

### 6. Pool reset races active flush worker

`SharedPostgreSQLPool.reset_pool()` closes the old pool while a flush worker may hold connections or be mid-write. Loop `0b37` logged:

```
RuntimeError: Task ..._flush_worker_loop()... attached to a different loop
```

**Files**: `shared_pool.py`, `retry_utils.py`, `sloop_manager.py`

### 7. Duplicate finalize at goal boundary

Goal completion:

1. Emits `completed` (user-visible)
2. Background tail: `ce.save()` + `state_manager.finalize_goal()`
3. Graph `finally`: `await tail_persistence` + `state_manager.close()`

Tail `finalize_goal` and `close()` race on the same pool and flush worker. In `0b37`, in-memory finalize succeeded but `force_flush` failed (`pool closed`); DB never reflected completion.

**Files**: `goal_completion.py`, `strange_loop.py`

---

## Design Goals

| Goal | Metric target |
|------|---------------|
| Hot path non-blocking | `record_iteration` persist enqueue ≤ 1 ms p99 |
| Goal boundary durable | Checkpoint + CE consistent within **1 s** of `completed` wire event |
| Shutdown bounded | `close()` completes ≤ **30 s** or marks persist incomplete explicitly |
| Write efficiency | ≤ **1** PostgreSQL round-trip per goal boundary (not 3–4) |
| Connection budget | Bounded total connections to `soothe_checkpoints` per process |
| Crash window | Configurable; default ≤ **5 s** for non-critical iteration state |

## Non-Goals (this IG)

- Cross-process replication or read replicas
- Checkpoint compression / encryption
- Migrating LangGraph checkpointer off PostgreSQL
- Full status vocabulary unification (deferred from IG-549 P3.15b)
- SQLite path optimization beyond parity hooks (PostgreSQL is primary for this IG)

---

## Proposed Architecture

### A. Unified persistence writer (single pipeline)

Introduce a **`LoopPersistenceWriter`** (daemon-scoped singleton per process) that owns all writes for a `loop_id`:

```
StrangeLoopStateManager ──┐
ContextEngine ────────────┼──► LoopPersistenceWriter ──► PostgreSQL (soothe_checkpoints)
Goal tail persist ────────┘         │
                                    ├─ coalesce queue (latest-wins per loop_id)
                                    ├─ single psycopg pool (shared budget)
                                    └─ bounded flush worker(s)
```

**Changes**:

- CE PostgreSQL backend **drops per-loop asyncpg pool**; submits dag/ledger bytes to the shared writer (or shares the sloop psycopg pool via adapter).
- One coalescing queue keyed by `loop_id`: intermediate checkpoints replace pending entry; only latest snapshot is written per flush tick.
- Goal-boundary writes tagged **`durability=required`**: bypass coalesce delay, flush immediately, but still one combined transaction where possible.

**New module (proposed)**: `packages/soothe/src/soothe/foundation/persistence/loop_writer.py`

### B. Split hot index from cold blob

Replace monolithic `checkpoint_data` UPSERT with two logical layers:

| Table / column | Content | Update frequency |
|----------------|---------|----------------|
| `agentloop_checkpoints` (existing) | **Hot index**: `status`, `current_goal_index`, `total_goals_completed`, `current_thread_id`, small execution_checkpoint | Every iteration (coalesced) |
| `agentloop_checkpoint_blobs` (new) or JSONB sub-key | **Cold blob**: full `goal_history`, working_memory, thread_health | Goal boundary + close only |

Iteration hot path writes ~500 B index row. Full blob rewrite only when goal history changes.

**Alternative (lighter Phase 1)**: Keep one table but add `checkpoint_index JSONB` column updated separately from `checkpoint_data` via two UPSERTs in one transaction — avoids migration of consumers that read full blob.

### C. Latest-wins coalescing flush worker

Replace FIFO queue drain with:

```python
# Conceptual API
writer.enqueue(loop_id, snapshot, priority=BACKGROUND)   # coalesce: replace pending
writer.enqueue(loop_id, snapshot, priority=DURABLE)        # flush ASAP, single flight
```

Worker loop (per process, not per request):

1. Wait `flush_interval` or durable signal
2. For each dirty `loop_id`, write **one** coalesced snapshot
3. On pool error: circuit-breaker; do not block caller indefinitely

Remove per-request `_start_flush_worker` / `_stop_flush_worker` lifecycle. Worker lifetime = daemon lifetime (thread pool) or worker process lifetime (subprocess pool).

**Config** (extend `LoopCheckpointAsyncConfig`):

```yaml
agent:
  loop:
    checkpoint:
      async_write: true
      flush_interval: 5.0
      coalesce: true              # new: latest-wins per loop_id
      close_timeout_seconds: 30   # new: bounded shutdown
      durable_flush_timeout: 10   # new: goal-boundary flush cap
```

Sync to `config/develop/config.yml` when implemented.

### D. Single goal-boundary persist transaction

Collapse tail persistence into **one durable operation**:

```
BEGIN;
  UPSERT agentloop_checkpoints (hot index);
  UPSERT agentloop_checkpoint_blobs (if changed);
  UPSERT ce_dag;
  UPSERT ce_ledger;
COMMIT;
```

Eliminate duplicate `finalize_goal` in tail + implicit flush in `close()`. Goal completion node calls **`writer.persist_goal_boundary(loop_id, ...)`** once; `close()` only releases references.

**Files to refactor**: `goal_completion.py`, `sloop_manager.py` (`finalize_goal` becomes index update + enqueue durable)

### E. Bounded shutdown

```python
async def close(self) -> None:
    try:
        await asyncio.wait_for(self._writer.release_loop(self.loop_id), timeout=close_timeout)
    except TimeoutError:
        logger.warning("Persist close timed out loop=%s; marking persist_incomplete", self.loop_id)
        # optional: write hot index status=persist_incomplete for reconciler
```

Never hold the daemon worker hostage until 7200s outer timeout.

### F. Pool reset protocol

Before `reset_pool()`:

1. Pause writer accepts new durable ops (fail fast with retryable error)
2. Await in-flight writes (with timeout)
3. Stop / detach flush workers from old pool
4. Close old pool
5. Open new pool; resume writer

Never close pool while a flush worker task created on that loop is still `await`ing pool connections.

**Files**: `shared_pool.py`, `loop_writer.py`, `retry_utils.py`

---

## Phased Implementation Plan

### Phase 0 — Instrumentation & baselines (1–2 days)

**Purpose**: Measure before optimizing.

| Task | Deliverable |
|------|-------------|
| Persist latency histograms | `soothe.persist.enqueue_ms`, `flush_ms`, `goal_boundary_ms`, `close_ms` |
| Queue depth gauge | `soothe.persist.pending_loops` |
| Pool metrics | reuse IG-406 logging; add `requests_waiting` alert threshold |
| Regression fixture | Replay loop `0b37` timeline as integration test stub (mock PG fault injection) |

**Files**: `sloop_manager.py`, `goal_completion.py`, `pgsql_backend.py`, optional `middleware/` metric helper

**Exit criteria**:

- [ ] Dashboard/log query can answer: “how long did goal boundary persist take?”
- [ ] Test: simulate `DiskFull` → `close()` returns within `close_timeout_seconds`

---

### Phase 1 — Coalescing + bounded close (P0, ~3–5 days)

**Highest ROI; fixes `0b37`-class hangs without schema migration.**

| # | Change | Files |
|---|--------|-------|
| 1.1 | Latest-wins queue: replace FIFO drain with “keep newest per loop_id” | `sloop_manager.py` |
| 1.2 | `close_timeout_seconds` on `_stop_flush_worker` + `force_flush` | `sloop_manager.py`, `config/models.py` |
| 1.3 | Remove duplicate `finalize_goal` from tail when sync path already finalized | `goal_completion.py` |
| 1.4 | Pool reset: stop writer / flush worker before `old_pool.close()` | `shared_pool.py`, `sloop_manager.py` |
| 1.5 | On durable flush failure: set hot index `persist_status=degraded` (new optional field in execution_checkpoint) | `sloop_manager.py`, reconciler hook |

**Exit criteria**:

- [ ] Loop with injected PG failure: worker returns ≤ 30 s; CLI gets error, not 7200 s hang
- [ ] Rapid `record_iteration` bursts: ≤ 1 PG write per `flush_interval` per loop
- [ ] Unit tests: coalesce, close timeout, pool reset ordering

---

### Phase 2 — Unified writer + connection budget (P1, ~1 week)

| # | Change | Files |
|---|--------|-------|
| 2.1 | `LoopPersistenceWriter` singleton | new `foundation/persistence/loop_writer.py` |
| 2.2 | Route CE `pgsql_backend` through writer (drop per-loop asyncpg pool) | `pgsql_backend.py`, `factory.py` |
| 2.3 | Single-transaction goal boundary persist | `loop_writer.py`, `goal_completion.py` |
| 2.4 | Config: `persistence.total_checkpoints_connections` cap shared by sloop + CE + writer | `config/models.py`, `shared_pool.py` |
| 2.5 | Daemon-lifetime flush worker (thread pool mode) | `strange_loop.py`, daemon bootstrap |

**Exit criteria**:

- [ ] Goal boundary: 1 transaction, ≤ 10 s p99 under normal PG
- [ ] Process connection count to `soothe_checkpoints` ≤ configured cap under N concurrent loops
- [ ] Integration: 5 sequential goals on one loop — no pool timeout at goal 5

---

### Phase 3 — Hot/cold checkpoint split (P2, ~1 week)

| # | Change | Files |
|---|--------|-------|
| 3.1 | Schema: `checkpoint_index` column or `agentloop_checkpoint_blobs` table | `postgres_schema.py` |
| 3.2 | Iteration saves: index only | `postgres_backend.py`, `sloop_manager.py` |
| 3.3 | Goal boundary: index + full blob | `loop_writer.py` |
| 3.4 | Load path: merge index + blob on read | `postgres_backend.py` |
| 3.5 | Reconciler for `persist_status=degraded` | daemon maintenance task |

**Exit criteria**:

- [ ] Iteration flush payload ≤ 2 KB typical (vs full blob)
- [ ] Resume after crash: index + blob consistent or reconciler repairs
- [ ] Migration: existing rows backfill index from `checkpoint_data`

---

### Phase 4 — Cross-cutting efficiency (P3, deferred)

Picked up from IG-549 deferred items:

| # | Opportunity | Notes |
|---|-------------|-------|
| 4.1 | Incremental CE ledger append | Append-only ledger segments vs full JSON rewrite |
| 4.2 | LangGraph checkpointer pool sharing audit | Separate pool today; evaluate shared budget |
| 4.3 | Background reconciler for stale `running` goals | Fix DB when durable flush failed but CE completed |
| 4.4 | `prepare_for_request()` persist warm path | Skip reload when same loop_id consecutive request |

---

## API Sketch (Phase 2)

```python
class LoopPersistenceWriter:
    async def enqueue_checkpoint(
        self,
        loop_id: str,
        checkpoint: StrangeLoopCheckpoint,
        *,
        durable: bool = False,
    ) -> None: ...

    async def persist_goal_boundary(
        self,
        loop_id: str,
        *,
        checkpoint: StrangeLoopCheckpoint,
        dag: GoalStepDAG,
        ledger: list[dict[str, Any]],
    ) -> PersistResult: ...

    async def release_loop(self, loop_id: str, *, timeout: float) -> None: ...


@dataclass
class PersistResult:
    ok: bool
    failures: list[str]  # e.g. checkpoint_index, ce_ledger
    duration_ms: int
```

`PersistResult` surfaces failures to logs and optional daemon events (user-visible: “saved locally; sync pending” — no IG/RFC ids in runtime strings).

---

## Verification Plan

### Unit tests

| Test | Phase |
|------|-------|
| Coalescing: 100 enqueues → 1 write per interval | 1 |
| `close()` returns on timeout when PG hung | 1 |
| Pool reset ordering (no cross-loop worker error) | 1 |
| Single-transaction goal boundary (mock conn) | 2 |
| Hot-only iteration write size bound | 3 |

**Location**: `packages/soothe/tests/unit/foundation/persistence/`

### Integration tests

| Scenario | Phase |
|----------|-------|
| 5 sequential goals, one loop, PostgreSQL | 2 |
| PG `DiskFull` injection → bounded close | 1 |
| Crash after coalesced enqueue → loss window ≤ flush_interval | 1 |
| Resume: checkpoint index matches CE goal status | 3 |

**Location**: `packages/soothe/tests/integration/core/persistence/`

### Manual / log verification

Re-run loop `0b37`-style workload (long execute step + goal completion):

- [ ] Goal completion report visible ≤ prior latency
- [ ] `agentloop_checkpoints.goal_history[-1].status == completed` within 1 s
- [ ] Worker request completes ≤ 30 s after graph sentinel (not 7200 s)
- [ ] No `attached to a different loop` in logs

Run `./scripts/verify_finally.sh` before merge.

---

## Rollback Strategy

| Phase | Rollback |
|-------|----------|
| 1 | `coalesce: false`, increase `close_timeout_seconds`; revert pool reset ordering |
| 2 | Feature flag `persistence.unified_writer: false` → legacy CE pool + separate flushes |
| 3 | Dual-read: load blob-only if index missing; disable index-only writes |

All flags in config template + `config/develop/config.yml`.

---

## Open Questions

1. **Subprocess pool mode**: Is flush worker daemon-scoped or per worker process? (Each worker process has its own singleton today — document and test both.)
2. **CE asyncpg removal**: Accept psycopg-only for CE PG backend, or shared asyncpg pool at daemon level?
3. **Reconciler UX**: When durable flush fails, should daemon expose `persist_degraded` on loop status for TUI badge?
4. **Blob storage**: Separate table vs partitioned JSONB — preference for ops (VACUUM, backup size)?

---

## File Map (expected touch set)

```
packages/soothe/src/soothe/
├── config/models.py                          # new timeout/coalesce flags
├── foundation/
│   ├── persistence/
│   │   └── loop_writer.py                    # Phase 2 (new)
│   ├── context/
│   │   ├── engine.py                         # defer_save integration
│   │   └── persistence/
│   │       ├── pgsql_backend.py              # route through writer
│   │       └── factory.py
│   └── sloop/
│       ├── engine/strange_loop.py            # daemon-lifetime writer; bounded close
│       ├── orchestrator/nodes/goal_completion.py  # single boundary persist
│       └── state/
│           ├── sloop_manager.py              # coalesce, timeouts
│           └── persistence/
│               ├── postgres_backend.py       # hot/cold split Phase 3
│               ├── postgres_schema.py
│               ├── shared_pool.py            # reset protocol
│               └── retry_utils.py

packages/soothe-daemon/src/soothe_daemon/
└── runner/thread_runner.py                   # optional: persist metrics on worker done

config/config.template.yml                    # sync structure
config/develop/config.yml

packages/soothe/tests/unit/foundation/persistence/
packages/soothe/tests/integration/core/persistence/
```

---

## References

- [IG-523](IG-523-async-checkpoint-writing.md) — RFC-803 Phase 6 async queue (implemented; gaps documented here)
- [IG-549](IG-549-loop-worker-goal-boundary-hardening.md) — goal boundary races; deferred pool consolidation (item 11)
- [IG-529](IG-529-soothe-home-persistence-consolidation.md) — file/SQLite consolidation (orthogonal; PG path is this IG)
- Loop `0b37` analysis (2026-07-06): command timeout on e2e step, goal completion OK, checkpoint stale, 7200 s worker timeout
- Code: `sloop_manager.py`, `goal_completion.py`, `shared_pool.py`, `pgsql_backend.py`, `postgres_backend.py`
