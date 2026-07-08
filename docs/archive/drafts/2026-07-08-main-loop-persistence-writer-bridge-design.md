# Draft: Main-Loop Persistence Writer Bridge

**Created**: 2026-07-08  
**Status**: Draft (feeds RFC-803 amendment + IG-571)  
**Authors**: Design review from production log forensics  
**Related**: [IG-550](../impl/IG-550-high-performance-persistence.md), [IG-561](../impl/IG-561-global-postgres-pool-registry.md), [RFC-803](../specs/RFC-803-strangeloop-checkpoint-backend.md)

---

## Context

IG-550 introduced `LoopPersistenceWriter` — a process-scoped singleton that coalesces checkpoint and ContextEngine writes onto the shared PostgreSQL pool (`SharedPostgreSQLPool` / `PostgresPoolRegistry`). The design is correct for high-concurrency thread_pool mode, but the first implementation binds `asyncio.Lock`, `asyncio.Event`, and the flush `Task` to whichever event loop first initializes the writer (typically the daemon main loop).

Thread pool workers each run a **dedicated asyncio event loop**. When multiple autopilot goals execute concurrently (`autopilot__w006`, `autopilot__w007`, …), workers call `writer.enqueue_checkpoint()` from their own loops and hit:

```
RuntimeError: <asyncio.locks.Lock …> is bound to a different event loop
```

This is not a PostgreSQL pool problem. The shared pool can be used from any loop via `psycopg` async connections; the failure is in **write orchestration primitives**, not connection sharing.

---

## Design Question

Should persistence writes move back into per-loop `StrangeLoopStateManager` instances?

| Approach | Verdict |
|----------|---------|
| Revert to per-manager flush workers for PostgreSQL | Rejects IG-550 benefits (process coalescing, single goal-boundary transaction, connection write budget) |
| Keep unified writer, fix execution model | **Recommended** — correct long-term shape |

**Separation of concerns (target)**:

| Layer | Owner | Responsibility |
|-------|-------|----------------|
| Domain | `StrangeLoopStateManager` | Checkpoint model, in-memory truth, load/merge, finalize semantics |
| Write pipeline | `LoopPersistenceWriter` | Coalesce, durable flush, goal-boundary transaction, CE dag/ledger |
| Connections | `SharedPostgreSQLPool` | Borrow `AsyncConnectionPool`; no per-loop pool proliferation |

Managers decide **what** to persist; the writer decides **how and when**; the pool provides **connections**.

---

## Recommended Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│ Daemon main event loop                                          │
│  LoopPersistenceWriter                                          │
│    threading.Lock → pending map (loop_id → latest snapshot)       │
│    asyncio.Lock   → flush worker + DB serialization only        │
│    _flush_worker_loop Task                                      │
│         │                                                       │
│         ▼                                                       │
│  SharedPostgreSQLPool.get_pool() → psycopg connections          │
└─────────────────────────────────────────────────────────────────┘
         ▲
         │ submit (thread-safe)
         │
┌────────┴────────┐   ┌────────────────┐   ┌────────────────┐
│ thread-worker-0 │   │ thread-worker-1│   │ thread-worker-N│
│ StrangeLoop     │   │ StrangeLoop    │   │ StrangeLoop    │
│ StateManager    │   │ StateManager   │   │ StateManager   │
│ ContextEngine   │   │ ContextEngine  │   │ ContextEngine  │
└─────────────────┘   └────────────────┘   └────────────────┘
```

### Submission API (conceptual)

Worker loops never await writer internals directly. They call a thread-safe submit surface:

```python
# Called from any thread / event loop
await writer.submit_enqueue(loop_id, checkpoint, *, durable=False, write_mode=...)
await writer.submit_flush_durable(loop_id, timeout=...)
await writer.submit_persist_goal_boundary(loop_id, checkpoint, dag=..., ledger=...)
await writer.submit_release_loop(loop_id, timeout=...)
```

Implementation options (pick one in IG-571):

1. **`asyncio.run_coroutine_threadsafe(coro, main_loop)`** — minimal change; callers `await` a future bridged back to their loop.
2. **`queue.SimpleQueue` + main-loop drain task** — producers never touch asyncio primitives on worker loops; main loop polls/subscribes.

Both require registering `main_loop` at daemon startup (`preopen_shared_postgres_pools` or `ThreadPool.start`).

### Lock strategy

| Primitive | Scope | Type | Reason |
|-----------|-------|------|--------|
| Pending map mutations | cross-thread | `threading.Lock` | Safe from worker threads without loop binding |
| DB write serialization | main loop only | `asyncio.Lock` | Protects single-flight flush + transactions |
| Durable signal | main loop only | `asyncio.Event` | Wakes flush worker on main loop |

Remove module-level `_writer_lock = asyncio.Lock()` for singleton init; use `threading.Lock` for double-checked singleton creation, then bind asyncio objects only after main loop is known.

### Read path (unchanged)

Loads stay on the caller's loop via `PostgreSQLPersistenceBackend` + shared pool connections. Reads do not need the writer bridge. Asymmetry is intentional: many readers, one write pipeline.

### Failure handling (no PostgreSQL fallback)

When the unified writer is active, **do not** fall back to `StrangeLoopStateManager._do_save_checkpoint()` on writer or bridge failure.

| Failure | Response |
|---------|----------|
| `PersistResult.ok=False` (timeout, PG error) | `mark_persist_degraded(checkpoint)` — same as today’s `force_flush` path |
| Bridge not bound at startup | Fail fast in daemon init (`bind_main_loop` required before workers run) |
| Unhandled `submit_*` exception | Propagate; do not write around the writer |

Rationale: a direct backend write races the writer’s coalesced pending entry, skips goal-boundary transactions (checkpoint + CE), and hides bridge defects.

**SQLite unchanged**: per-manager flush worker and `_do_save_checkpoint()` remain the primary path when `writer is None`.

---

## worker_pool vs thread_pool

| Runtime | Writer placement | Notes |
|---------|------------------|-------|
| **thread_pool** | One writer on daemon main loop + submit bridge | Many event loops per process — bridge required |
| **worker_pool** | One writer per subprocess (natural loop affinity) | Subprocess has one event loop; current asyncio locks OK if init happens on that loop |

IG-571 focuses on thread_pool; document worker_pool parity in IG-571 verification.

---

## Alternatives Considered

### A. Per-loop PostgreSQL flush workers (revert IG-550 writer)

- **Pro**: Loop-local asyncio affinity, simple mental model.
- **Con**: N concurrent loops ⇒ N flush timers, duplicated durable policy, no single goal-boundary transaction across checkpoint + CE tables, write amplification under autopilot.

### B. Shared writer without bridge (status quo)

- **Pro**: Already shipped.
- **Con**: Production failures under concurrent autopilot; thread workers die; goal init/close hard-fail.

### C. Main-loop writer + submit bridge (recommended)

- **Pro**: Keeps IG-550 goals; fixes root cause; shared pool unchanged.
- **Con**: Requires explicit main-loop registration and cross-thread testing.

---

## Success Criteria

1. No `bound to a different event loop` from `loop_writer.py` under N concurrent thread-pool workers.
2. Autopilot dispatch of 8+ simultaneous goals: all `initialize()` checkpoint enqueues succeed.
3. Goal-boundary `persist_goal_boundary` durable commit still ≤ 1 transaction.
4. `SharedPostgreSQLPool` / `PostgresPoolRegistry` config unchanged.
5. Integration test: 3+ `asyncio.to_thread` workers each enqueue concurrently (extends `test_thread_pool_postgres_pools.py` pattern).

---

## Open Questions

1. Should `submit_*` block worker threads on durable flush, or return a future immediately for background-only enqueues? **→ IG-571 Phase A: block on durable/close; background enqueue returns after main-loop schedule.**
2. On daemon shutdown, drain order: `LoopPersistenceWriter.shutdown()` before or after `ThreadPool.shutdown()`?
3. Expose writer queue depth on daemon health endpoint?
4. **PostgreSQL fallback to `_do_save_checkpoint()` when writer fails?** **→ No.** Degraded marker + reconciler only; see IG-571 §Failure Handling.

---

## Next Steps

1. Land RFC-803 amendment (unified write pipeline + execution model).
2. Implement IG-571 Phase A (bridge + regression test).
3. Update IG-550 follow-up section; close manual verification gap item “No attached to a different loop in logs”.
