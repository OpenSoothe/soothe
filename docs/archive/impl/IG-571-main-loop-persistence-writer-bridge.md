# IG-571: Main-Loop Persistence Writer Bridge

**Guide**: IG-571  
**Title**: Cross-Event-Loop Bridge for LoopPersistenceWriter (thread_pool)  
**Created**: 2026-07-08  
**Status**: Implemented  
**Related RFCs**: [RFC-803](../specs/RFC-803-strangeloop-checkpoint-backend.md) (amendment §Unified Write Pipeline)  
**Related IGs**: [IG-550](IG-550-high-performance-persistence.md), [IG-549](IG-549-loop-worker-goal-boundary-hardening.md), [IG-561](IG-561-global-postgres-pool-registry.md), [IG-553](IG-553-soothe-log-stability-fixes.md)  
**Design draft**: [2026-07-08-main-loop-persistence-writer-bridge-design.md](../archive/drafts/2026-07-08-main-loop-persistence-writer-bridge-design.md)  
**Logs**: `~/.soothe/logs/soothe.log*`, `~/.soothe/logs/daemon.log*` (2026-07-08 sessions)

---

## Executive Summary

IG-550 shipped `LoopPersistenceWriter` as the correct **long-term write pipeline** atop `SharedPostgreSQLPool`, but the implementation uses loop-bound `asyncio` synchronization on a process singleton. In **thread_pool** mode each worker thread owns a dedicated event loop; concurrent autopilot goals fail with:

`RuntimeError: <asyncio.locks.Lock …> is bound to a different event loop`

IG-571 fixes the **execution model**, not the architecture: keep the unified writer and shared pool; run the writer on the **daemon main loop** and expose a **thread-safe submit API** for worker threads. `StrangeLoopStateManager` remains the per-loop domain owner (checkpoint semantics, in-memory state, load path).

---

## Problem Statement

### Observed failures

| Symptom | Call site | Log tag |
|---------|-----------|---------|
| Goal fails at init | `state_manager.initialize()` → `enqueue_checkpoint()` | `[w006]`, `[w012]` |
| Goal fails at close | `state_manager.close()` → `release_loop()` | `[w010]` |
| Goal-boundary persist degraded | `persist_goal_boundary()` → `_write_lock` | `[w010]` |
| Thread worker death | Uncaught `RuntimeError` in worker thread | `daemon.log` `thread-worker-4` |

Traceback anchor: `loop_writer.py` line `async with self._pending_lock` (or `_write_lock`).

### Root cause

1. `preopen_shared_postgres_pools()` initializes `LoopPersistenceWriter` on the **daemon main loop** (`pools.py`).
2. Thread pool workers run StrangeLoop on **per-thread event loops** (`thread_runner.py`).
3. `asyncio.Lock` / `Event` / `Task` created on loop A cannot be used on loop B (Python 3.10+).
4. `_writer_lock` at module scope has the same defect for lazy init races across loops.

### Non-goals

- Replacing `SharedPostgreSQLPool` or `PostgresPoolRegistry` (IG-561 stays).
- Moving checkpoint domain logic out of `StrangeLoopStateManager`.
- Reverting IG-550 unified writer for PostgreSQL (per-loop flush workers).

---

## Design Goals

| Goal | Target |
|------|--------|
| Cross-loop safety | Zero `bound to a different event loop` from writer under max thread_pool concurrency |
| Preserve IG-550 wins | Process coalescing, durable goal-boundary single transaction, bounded `release_loop` |
| Shared pool unchanged | Writer continues `shared_pool.get_pool()`; no new per-loop pools |
| Thin manager client | StateManager: in-memory update + `submit_*`; no PG flush worker for PostgreSQL |
| Single PG write path | When writer is active, **no** `_do_save_checkpoint()` bypass on writer failure |
| Safe failure | `PersistResult.ok=False` or bounded timeout → `mark_persist_degraded()`; reconciler hook (IG-550 Phase 4) |

---

## Failure Handling (No PostgreSQL Fallback)

When `LoopPersistenceWriter` is active (`writer is not None`), `StrangeLoopStateManager` **must not** call `_do_save_checkpoint()` as a fallback for writer or bridge errors.

| Outcome | Behavior |
|---------|----------|
| Background `submit_enqueue` succeeds | Coalesced; in-memory cache already updated |
| Durable / goal boundary `PersistResult.ok=False` | `mark_persist_degraded(checkpoint)`; log failures; goal may complete in memory |
| `submit_*` timeout | Same as durable failure; bounded by `durable_flush_timeout` / `close_timeout_seconds` |
| Unhandled exception from bridge | Propagate — goal fails loudly; fix bridge or shutdown ordering |

**Why no fallback**

- Dual pipelines race (writer pending entry + direct backend write on same `loop_id`).
- `_do_save_checkpoint()` is checkpoint-only; bypasses single-transaction goal boundary (checkpoint + CE).
- Masks bridge bugs instead of failing fast at daemon init (`bind_main_loop` required).

**What stays**

| Path | When |
|------|------|
| `_do_save_checkpoint()` | SQLite backend only (`writer is None`) |
| SQLite `_flush_worker_loop` | Per-loop worker on same event loop as manager |
| `_is_async_loop_runtime_error` in SQLite worker | Stop loop-local flush worker only — not a PG fallback |

**Audit on implementation** (Phase A.5): Remove or guard the `_closed` → `_do_save_checkpoint()` branch so PostgreSQL never bypasses the writer after `close()` sets `_closed=True` mid-drain.

---

## Target Architecture

```text
StrangeLoopStateManager ──┐
ContextEngine PG backend ─┼──► submit_* (thread-safe) ──► LoopPersistenceWriter (main loop only)
Goal completion tail ─────┘                                      │
                                                                 ▼
                                                    SharedPostgreSQLPool
```

### Responsibility split

| Component | Keeps | Drops / defers |
|-----------|-------|----------------|
| `StrangeLoopStateManager` | `_checkpoint` cache, load/merge, `finalize_goal` memory, `close` lifecycle | Direct `await writer.enqueue_*` from worker loops |
| `LoopPersistenceWriter` | Coalesce map, flush worker, `persist_goal_boundary`, `release_loop` | Loop-bound locks reachable from worker threads |
| `SharedPostgreSQLPool` | Connection pool, registry binding, `reset_pool` protocol | N/A |

---

## Implementation Plan

### Phase A — Main-loop binding + submit bridge (P0)

| # | Task | Files |
|---|------|-------|
| A.1 | `LoopPersistenceWriter.bind_main_loop(loop)` called from daemon startup after pool preopen | `loop_writer.py`, `pools.py`, `thread_runner.py` or `server/core.py` |
| A.2 | Replace cross-thread `asyncio.Lock` with `threading.Lock` for `_pending` map and singleton init | `loop_writer.py` |
| A.3 | Add `submit_enqueue`, `submit_flush_durable`, `submit_persist_goal_boundary`, `submit_release_loop` using `run_coroutine_threadsafe` + awaitable bridge | `loop_writer.py` |
| A.4 | Route `StrangeLoopStateManager` + CE `pgsql_backend` through `submit_*` | `sloop_manager.py`, `pgsql_backend.py` |
| A.5 | Audit PG paths: no `_do_save_checkpoint()` when writer active; fix `_closed` bypass if it skips writer | `sloop_manager.py` |
| A.6 | Fail-safe only: `PersistResult` / timeout → `mark_persist_degraded()` (match existing `force_flush` behavior) | `sloop_manager.py`, `goal_completion.py` |

**Exit criteria**:

- [ ] Integration: 3 concurrent `asyncio.to_thread` workers enqueue without error (extend `test_thread_pool_postgres_pools.py`)
- [ ] Unit: submit from non-main loop mocked; flush worker runs only on main loop
- [ ] Manual: 8 concurrent autopilot goals — no writer `RuntimeError` in `soothe.log`

### Phase B — Shutdown ordering + observability (P1)

| # | Task | Files |
|---|------|-------|
| B.1 | Document and enforce shutdown: pause writer → drain pending → `ThreadPool.shutdown()` | `pools.py`, `server/core.py` |
| B.2 | Log `persist.pending_loops` + submit latency on durable path | `loop_writer.py`, `persist_metrics.py` |
| B.3 | `ThreadPool` health: surface writer bridge errors in `_worker_last_errors` classification | `thread_runner.py` |

### Phase C — worker_pool parity doc + test (P2)

| # | Task | Files |
|---|------|-------|
| C.1 | Document: subprocess mode = one loop per process; writer init on worker loop is OK | RFC-803, this IG |
| C.2 | Integration test in worker_pool mode (if CI supports) | `packages/soothe-daemon/tests/integration/` |

---

## API Sketch

```python
class LoopPersistenceWriter:
    _main_loop: asyncio.AbstractEventLoop | None = None
    _pending_guard: threading.Lock  # protects _pending dict

    @classmethod
    def bind_main_loop(cls, loop: asyncio.AbstractEventLoop) -> None: ...

    async def _enqueue_checkpoint_impl(...) -> None:
        """Main loop only — existing enqueue logic."""

    async def submit_enqueue(
        self,
        loop_id: str,
        checkpoint: StrangeLoopCheckpoint,
        *,
        durable: bool = False,
        write_mode: PersistWriteMode = PersistWriteMode.INDEX_ONLY,
    ) -> None:
        """Callable from any thread; schedules _enqueue_checkpoint_impl on main loop."""
```

`StrangeLoopStateManager._save_checkpoint_to_db` becomes:

```python
self._checkpoint = checkpoint
self._last_save_checkpoint = checkpoint
writer = await self._ensure_loop_writer()
if writer is not None and not self._closed:
    await writer.submit_enqueue(self.loop_id, checkpoint, write_mode=write_mode)
    return
# SQLite only — writer is None
```

On writer failure, do **not** fall through to `_do_save_checkpoint()`:

```python
result = await writer.submit_flush_durable(self.loop_id, timeout=timeout)
if not result.ok:
    mark_persist_degraded(self._last_save_checkpoint)
```

---

## Verification Plan

### Unit tests

| Test | Location |
|------|----------|
| `submit_enqueue` from secondary loop (mocked main loop) | `tests/unit/foundation/persistence/test_loop_writer_bridge.py` |
| Coalescing still latest-wins after bridge | `test_loop_writer_coalesce.py` |
| Writer `PersistResult.ok=False` → degraded marker, no `_do_save_checkpoint` call | `tests/unit/core/loop/state/test_checkpoint_writer_no_pg_fallback.py` |

### Integration tests

| Test | Location |
|------|----------|
| Concurrent thread workers + writer enqueue | `packages/soothe-daemon/tests/integration/runner/test_thread_pool_postgres_pools.py` |
| Goal boundary transaction after bridge | `packages/soothe/tests/integration/core/persistence/` |

Run `./scripts/verify_finally.sh` before merge.

### Log verification

- [ ] No `bound to a different event loop` in `soothe.log*` / `daemon.log*` under concurrent autopilot load
- [ ] IG-550 manual item satisfied: no `attached to a different loop` / cross-loop writer errors

---

## Rollback

| Flag / action | Effect |
|---------------|--------|
| `persistence.unified_writer: false` (if present) | Legacy per-manager PG writes via `_do_save_checkpoint` (SQLite-style path) |

No runtime “silent bypass” of the writer while unified writer is enabled.

Sync config template + `config/develop/config.yml` if a feature flag is added.

---

## File Map

```text
packages/soothe/src/soothe/persistence/loop_writer.py   # bridge + threading locks
packages/soothe/src/soothe/sloop/state/sloop_manager.py # submit_* client; no PG fallback
packages/soothe/src/soothe/context/pgsql_backend.py
packages/soothe-daemon/src/soothe_daemon/persistence/pools.py      # bind_main_loop at preopen
packages/soothe-daemon/src/soothe_daemon/runner/thread_runner.py   # optional: pass main_loop ref
packages/soothe-daemon/tests/integration/runner/test_thread_pool_postgres_pools.py
packages/soothe/tests/unit/foundation/persistence/test_loop_writer_bridge.py
docs/specs/RFC-803-strangeloop-checkpoint-backend.md               # amendment
docs/impl/IG-550-high-performance-persistence.md                   # follow-up note
```

---

## References

- [IG-550](IG-550-high-performance-persistence.md) — unified writer (complete; bridge gap)
- [IG-561](IG-561-global-postgres-pool-registry.md) — shared pool registry (orthogonal)
- [RFC-803 §Unified Write Pipeline](../specs/RFC-803-strangeloop-checkpoint-backend.md) — normative amendment
- Design draft: [2026-07-08-main-loop-persistence-writer-bridge-design.md](../archive/drafts/2026-07-08-main-loop-persistence-writer-bridge-design.md)
