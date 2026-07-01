# IG-529: SOOTHE_HOME Data-Path Persistence Consolidation

**Guide**: IG-529  
**Title**: SOOTHE_HOME Data-Path Persistence Consolidation  
**Created**: 2026-06-30  
**Status**: Draft  
**Related RFCs**: RFC-413 (display card ledger), RFC-803 (StrangeLoop checkpoint backend), RFC-624 (ContextEngine lifecycle)  
**Proposed RFC**: RFC-631 — *Unified Runtime Persistence Layout* (to be drafted; amends RFC-413 §7 storage and RFC-803 §4 layout)  
**Dependencies**: IG-055 (unified SQLite checkpoints), IG-430/IG-466 (loop GC), IG-523 (async checkpoint writes)

---

## Summary

Consolidate fragmented file-backed runtime data under `$SOOTHE_HOME/data/` into shared SQLite stores, fix retention/GC gaps, and delete redundant mirrors and legacy file backends.

**No production history — clean break.** No import from old layouts, no dual-write, no feature flags to read `cards.jsonl` / per-loop `ce_state.db` / `metadata.json`. Developers with stale local trees wipe `~/.soothe/data` (or rely on loop GC + orphan reconciler).

**End state:**

| Artifact | Today | Target |
|----------|-------|--------|
| Loop metadata mirror | `loops/{id}/metadata.json` | **Deleted** — `agentloop_loops` in `soothe_checkpoints.db` only |
| ContextEngine state | `loops/{id}/ce_state.db` (per loop) | **`$SOOTHE_DATA_DIR/context_engine.db`** (shared, keyed by `loop_id`) |
| Display card ledger | `loops/{id}/cards.jsonl` | **`display.db`** — `display_card_mutations` table only |
| Card derivation | Lazy backfill from checkpoint + `conversation.jsonl` on RPC | **Real-time binding** during execution only |
| Thread audit logs | `threads/{id}/logs/conversation.jsonl` | Retained (bounded); **global retention sweep fixed** |
| Orphan loop dirs | No reconciler | **Periodic reconcile** `data/loops/` ↔ `agentloop_loops` |

---

## Background

### Measured symptoms (representative dev `~/.soothe/data`)

| Component | Size | Issue |
|-----------|------|-------|
| `data/loops/` | ~157 MB | 427/611 dirs have ≤1 file; many test/ephemeral stubs |
| `runner.log` | ~40 MB | Not rotated; only deleted when loop dir purged |
| `conversation.jsonl` | ~40 MB | Retention not applied globally |
| per-loop `ce_state.db` WAL/SHM | ~25 MB | Per-loop SQLite files + WAL bloat |
| `soothe_checkpoints.db` | ~11 MB | Canonical loop/checkpoint store |
| `cards.jsonl` (all) | ~3.3 MB | Full-file load; lazy derivation on RPC |

### Known gaps

1. **`ThreadLogger.cleanup_old_threads()`** scans only the *current* thread's `logs/` dir (`thread_logger.py:326`), not all of `data/threads/`.
2. **`max_size_mb`** on thread logging is not enforced (`thread_logger.py:56`).
3. **Loop GC** purges DB-known idle loops but does not delete orphan filesystem dirs.
4. **`metadata.json`** is a denormalized cache; SQLite is source of truth (`sloop_manager.py:1223`).
5. **`LoopCardManager`** lazy-derives cards from checkpoint + activity log on RPC (`loop_card_manager.py:13-16`).
6. **Per-loop `ce_state.db`** duplicates WAL/connection overhead; schema already keys by `loop_id`.

---

## Scope

### In scope

- Phase 0–1: Config tuning, WAL maintenance, global thread-log cleanup, orphan reconciler, `runner.log` rotation
- Phase 2: Remove `metadata.json` writes and all readers/paths
- Phase 3: Shared `context_engine.db` only (delete per-loop CE file backend)
- Phase 4: `display.db` + `SqliteCardLedger` only (delete `cards.jsonl` / `LoopCardLedger` file backend)
- Phase 5: Real-time card binding only (delete lazy `_derive_into` / checkpoint+log backfill)
- Tests, config template sync, RFC-631 draft

### Out of scope

- Import/migration from `ce_state.db`, `cards.jsonl`, or `metadata.json`
- Dual backends, rollback flags, `SOOTHE_SKIP_DATA_MIGRATIONS`
- PostgreSQL backends for cards/CE (later; IG-055 patterns)
- Removing `conversation.jsonl` (audit; bounded retention only)
- MemU `memory/` file store
- `data/workspaces/` layout (RFC-621)

### Breaking change notice

After this lands, **old loop display state and per-loop CE files are not readable**. Wipe local data:

```bash
rm -rf ~/.soothe/data/loops ~/.soothe/data/threads
# or full reset:
rm -rf ~/.soothe/data
```

Document in RFC-631 and release notes (internal wiki only; no user-facing IG/RFC ids).

---

## Design

### Target layout (`$SOOTHE_DATA_DIR`)

```
data/
  metadata.db              # ThreadInfo / durability
  soothe_checkpoints.db    # agentloop_loops, checkpoints, goal_records, …
  context_engine.db        # ce_dag, ce_ledger (loop_id PK)
  display.db               # display_card_mutations (append-only)
  history.jsonl            # CLI input history
  threads/{id}/logs/conversation.jsonl
  loops/{id}/runner.log    # only residual per-loop file (rotated)
  workspaces/{user}/ws_*/
  archived_loops/
```

**Not created anymore:** `loops/{id}/metadata.json`, `loops/{id}/cards.jsonl`, `loops/{id}/ce_state.db`.

### Schema: `display.db`

```sql
CREATE TABLE display_card_mutations (
    loop_id     TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    ts          TEXT NOT NULL,
    op          TEXT NOT NULL,
    card_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    data_json   TEXT NOT NULL,
    PRIMARY KEY (loop_id, seq)
);
CREATE INDEX idx_display_cards_loop ON display_card_mutations(loop_id, seq);
```

Wire shape unchanged (`CardMutation` in `soothe_sdk.display.card_ledger`).

### Schema: `context_engine.db`

Reuse `SqliteContextPersistence._ensure_schema` (`sqlite_backend.py:59-71`). Single path: `$SOOTHE_DATA_DIR/context_engine.db`. Factory: `resolve_context_engine_db_path()`.

### Real-time card binding (only path)

| Event source | Binder action |
|--------------|---------------|
| User input accepted | `create` user card → `display.db` |
| Stream / cognition events | `create` / `update` cognition cards |
| Step start/complete | step card lifecycle |
| Tool call rows | `update` parent step card |

`LoopCardManager.ensure_for_loop` → load mutations from `display.db` and replay into memory. **No** `_derive_cards`, **no** `refresh()` on default RPC paths.

Delete: `loop_card_ledger.py` file I/O, `loop_history_probe` derivation helpers used only for backfill, RFC-413 “backfill, don't migrate” lazy path.

---

## Implementation Plan

### Phase 0 — Ops & config

**Files:** `config/daemon.template.yml`, `config/develop/*`, `config/config.template.yml`

```yaml
loop_gc:
  enabled: true
  interval_seconds: 1800
  ephemeral_idle_hours: 6
  empty_idle_hours: 6
  batch_size: 200
```

**WAL maintenance** — `wal_maintenance.py`; checkpoint on daemon `stop()` and each `_periodic_loop_gc` tick for `soothe_checkpoints.db`, `context_engine.db`, `display.db`.

---

### Phase 1 — Housekeeping

#### 1a. Global thread-log retention

- `cleanup_stale_thread_logs(data/threads/, retention_days, max_size_mb)` — walk all `conversation.jsonl`
- Wire into `_periodic_cleanup` in `core.py`
- Remove or narrow `ThreadLogger.cleanup_old_threads()` (instance-scoped bug)

#### 1b. Orphan loop-directory reconciler

- `loop_reconcile.py`: delete `data/loops/{id}/` when `id ∉ agentloop_loops`
- Run from `_periodic_loop_gc`

#### 1c. `runner.log` rotation

- `RotatingFileHandler` in `worker_logging.py` (5 MB × 2)

---

### Phase 2 — Remove `metadata.json`

**Delete / stop using:**

- `sloop_manager._sync_metadata_to_disk()` and call site
- `PersistenceDirectoryManager.get_loop_metadata_path()`
- `archive_backend.py` reads of `metadata.json` → `PersistenceManager.get_loop_metadata()` only
- Stale docstrings in CLI (`sessions.py`), RFC-504 examples (update in RFC-631 pass)

**No** optional mirror flag, **no** prune script.

---

### Phase 3 — `context_engine.db` only

**Changes:**

- `resolve_context_engine_db_path()` → `$SOOTHE_DATA_DIR/context_engine.db`
- `strange_loop.py`: pass shared path to `SqliteContextPersistence`; stop creating `loop_dir / "ce_state.db"`
- `persistence.context_engine_sqlite_path` in config models + templates
- Loop GC: delete CE rows `DELETE FROM ce_dag/ce_ledger WHERE loop_id = ?` (or shared purge helper); loop dir no longer holds CE files

**Delete:** any `per_loop` CE path logic. **No** `migrate_context_engine.py`.

**Tests:** `test_context_engine_lifecycle.py` against shared DB path.

---

### Phase 4 — `display.db` only

**Add:**

- `display_store.py` — CRUD for `display_card_mutations`
- `SqliteCardLedger` in `loop_card_ledger.py` (replace file-backed `LoopCardLedger`)

**Delete:**

- `_CARDS_FILENAME = "cards.jsonl"` and all JSONL read/write in `loop_card_ledger.py`
- `router.py` peek of `cards.jsonl` → query `display.db` (first user card or loop metadata)
- `display_backend` config knob (SQLite is the only backend)
- Tests that assert `cards.jsonl` on disk → assert DB rows instead

**Loop GC / purge:** `DELETE FROM display_card_mutations WHERE loop_id = ?`

**No** `migrate_cards_jsonl.py`, **no** JSONL import on read.

---

### Phase 5 — Real-time binding only

**Changes:**

- `LoopCardManager.on_event(loop_id, event)` from execution/stream path (`query/engine.py` or event bus)
- `ensure_for_loop`: open `SqliteCardLedger`, load from DB — empty ledger means empty transcript (new loop)
- Remove: `_derive_into`, `_derive_cards`, `_fetch_derivable_log_events` (if only used for backfill), `refresh()` from hot paths, `is_display_empty` checkpoint+log probe (replace with `display.db` row count if needed)

**Tests:**

- Loop run → cards in `display.db` without derivation
- Reattach replays from DB only

---

### Phase 6 — RFC & docs

- RFC-631: canonical layout (no legacy filenames)
- Amend RFC-413 §7: SQLite `display.db`, not JSONL
- Amend RFC-803: no `metadata.json`
- `howto_debug.md`: paths for `context_engine.db`, `display.db`

---

## Testing Plan

1. Unit: thread sweeper, orphan reconciler, `SqliteCardLedger`, shared CE persistence
2. Integration: ephemeral loop GC purges `display.db` + CE rows + loop dir
3. Integration: loop execute → reattach → card replay from DB
4. `./scripts/verify_finally.sh`

---

## Acceptance Criteria

- [ ] No code paths create or read `metadata.json`, `cards.jsonl`, or per-loop `ce_state.db`
- [ ] `context_engine.db` and `display.db` are sole CE/display stores
- [ ] Real-time binding only; `_derive_cards` removed
- [ ] Global thread-log retention works across all `data/threads/`
- [ ] Orphan `data/loops/{id}/` dirs removed when absent from `agentloop_loops`
- [ ] Loop GC deletes CE + display rows for purged loops
- [ ] WAL checkpoint on shutdown
- [ ] RFC-631 drafted; RFC-413/803 updated

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Missed card event → empty transcript | Parity tests for all event types; binder unit tests |
| Shared DB lock contention | WAL + `busy_timeout`; separate `display.db` |
| Orphan reconciler deletes wanted dir | Only delete when `loop_id` missing from DB |
| Local dev stale data | Document wipe; reconciler cleans orphan dirs |

---

## Task Breakdown

| # | Task | Phase |
|---|------|-------|
| 1 | loop_gc + WAL + develop observability config | 0 |
| 2 | Global thread-log cleanup + max_size_mb | 1 |
| 3 | Orphan loop-dir reconciler | 1 |
| 4 | runner.log rotation | 1 |
| 5 | Remove metadata.json (write + read paths) | 2 |
| 6 | Shared `context_engine.db`; delete per-loop CE files | 3 |
| 7 | `display.db` + `SqliteCardLedger`; delete JSONL ledger | 4 |
| 8 | Real-time binding; delete lazy derivation | 5 |
| 9 | RFC-631 + doc updates | 6 |
| 10 | Tests + verify_finally | all |

---

## References

- `packages/soothe/src/soothe/foundation/sloop/state/persistence/directory_manager.py`
- `packages/soothe-daemon/src/soothe_daemon/display/loop_card_manager.py`
- `packages/soothe-daemon/src/soothe_daemon/display/loop_card_ledger.py`
- `packages/soothe/src/soothe/foundation/context/persistence/sqlite_backend.py`
- `docs/specs/RFC-413-server-owned-display-card-ledger.md`
- `docs/specs/RFC-803-strangeloop-checkpoint-backend.md`
