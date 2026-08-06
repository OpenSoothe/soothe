# IG-647: SQLite Store Runtime (Isolation, Performance, Layout Cut)

**Status**: Implemented  
**Date**: 2026-07-24  
**Guide**: IG-647  
**Source**: [RFC-801](../specs/RFC-801-sqlite-backend.md), [RFC-802](../specs/RFC-802-persistence-architecture-refactor.md), [RFC-803](../specs/RFC-803-strangeloop-checkpoint-backend.md)  
**Design draft**: [2026-07-24-sqlite-runtime-isolation-performance-design.md](../drafts/2026-07-24-sqlite-runtime-isolation-performance-design.md)  
**Packages**: `soothe` (Runtime + host stores), `soothe-daemon` (display), `soothe-nano` (persist + vectors; same contract, no host imports)  
**Language**: Python ≥3.11  

---

## Goal

Replace ad-hoc per-store / per-manager SQLite connections with a **process-scoped `SqliteStoreRuntime` per DB file**, move all purpose databases to `$SOOTHE_DATA_DIR/databases/{purpose}.db`, and give SQLite the same control-plane shape as PostgreSQL shared pools / process writers. **Hard cut** — no migration or legacy path shims.

---

## Non-Goals

- Multi-process / multi-writer SQLite  
- Merging purpose files into one DB  
- Matching PostgreSQL write QPS  
- Migrating existing flat `$SOOTHE_DATA_DIR/*.db` files  
- Changing PostgreSQL pool / `LoopPersistenceWriter` behavior (except ensuring SQLite no longer bypasses via private connections)

---

## Normative requirements (from RFCs)

| ID | Requirement |
|----|-------------|
| R1 | One `SqliteStoreRuntime` per absolute DB path; registry refcount + shutdown WAL checkpoint |
| R2 | Writes: serialized + `BEGIN IMMEDIATE` + commit/rollback; `busy_timeout` default 60s; WAL + FK on |
| R3 | Reads: leased pop/use/return; never share one connection across concurrent tasks |
| R4 | Layout: only `$SOOTHE_DATA_DIR/databases/{purpose}.db` (table below) |
| R5 | StrangeLoop: no private writer/reader pools; process-scoped coalesce flush on checkpoints Runtime |
| R6 | All stores (checkpoints, context, display, cron, identity, metadata, persist, vectors) use Runtime |
| R7 | Grep-clean: no runtime opens of legacy basenames |
| R8 | Postgres mode unchanged; no SqliteRuntimeRegistry when `default_backend=postgresql` |

### Purpose files

| Purpose | Path |
|---------|------|
| checkpoints | `databases/checkpoints.db` |
| context | `databases/context.db` |
| display | `databases/display.db` |
| cron | `databases/cron.db` |
| identity | `databases/identity.db` |
| metadata | `databases/metadata.db` |
| persist | `databases/persist.db` |
| vectors | `databases/vectors.db` |
| memory (optional) | `databases/memory.db` |

---

## Architecture

```text
soothe.persistence.sqlite_runtime
  SqliteStoreRuntime
  SqliteRuntimeRegistry
  SqliteRuntimeConfig (optional; from PersistenceConfig.sqlite)

soothe.sloop.checkpoints.runtime_paths  (and nano paths mirror)
  resolve_databases_dir()
  resolve_checkpoints_db_path() …
```

```text
Daemon (sqlite) → Registry.acquire(path) → Runtime
Store adapters → run_write / run_read
Shutdown → Registry.close_all → wal_checkpoint(TRUNCATE)
```

---

## Module layout

```text
packages/soothe/src/soothe/persistence/
  sqlite_runtime.py          # NEW: Runtime + Registry + config model helpers
  … (existing postgres_* unchanged)

packages/soothe/src/soothe/sloop/checkpoints/
  runtime_paths.py           # CUT: databases/ resolvers only
  sqlite_backend.py          # Adapt to Runtime; delete dead reader pool
  shared_pool.py             # Shared SQLite backend uses Registry

packages/soothe/src/soothe/sloop/state/
  sloop_manager.py           # Remove private sqlite pools; enqueue to process flush

packages/soothe/src/soothe/context/
  store_sqlite.py            # Runtime for context.db

packages/soothe/src/soothe/cron/
  store.py                   # Runtime for cron.db

packages/soothe/src/soothe/identity/
  db.py / identity_service.py  # Runtime for identity.db

packages/soothe-daemon/src/soothe_daemon/display/
  display_store.py           # Runtime for display.db; lock all access via Runtime

packages/soothe-nano/src/soothe_nano/
  paths/sqlite_paths.py      # databases/persist.db, metadata.db, vectors.db
  backends/persistence/sqlite_store.py
  backends/vector_store/sqlite_vec.py
  backends/durability/sqlite.py
```

**Package boundary**: nano implements a local Runtime (or thin duplicate of the contract) under `soothe_nano`; host must not be imported by nano. Prefer shared path constants via `soothe_sdk.paths` if needed (`SOOTHE_DATA_DIR` + `databases/` join).

---

## Core types (concrete)

```python
@dataclass(frozen=True)
class SqliteRuntimeConfig:
    reader_pool_size: int = 3
    busy_timeout_ms: int = 60_000
    wal_checkpoint_on_shutdown: bool = True


class SqliteStoreRuntime:
    def __init__(self, db_path: Path, config: SqliteRuntimeConfig | None = None) -> None: ...

    async def run_write(self, sync_fn: Callable[[sqlite3.Connection], T]) -> T:
        """BEGIN IMMEDIATE; sync_fn(conn); COMMIT | ROLLBACK. Thread-serialized."""

    async def run_read(self, sync_fn: Callable[[sqlite3.Connection], T]) -> T:
        """Lease reader for sync_fn only; return to pool after."""

    async def close(self) -> None:
        """Optional wal_checkpoint(TRUNCATE); close all conns."""


class SqliteRuntimeRegistry:
    @classmethod
    def acquire(cls, db_path: Path, config: SqliteRuntimeConfig | None = None) -> SqliteStoreRuntime: ...

    @classmethod
    async def release(cls, db_path: Path) -> None: ...

    @classmethod
    async def close_all(cls) -> None: ...
```

Wire `PersistenceConfig.sqlite: SqliteRuntimeConfig | None` in host (+ nano mirror if applicable). **No** per-file path overrides.

---

## Path resolvers (cut)

```python
def resolve_databases_dir() -> Path:
    return Path(SOOTHE_DATA_DIR) / "databases"

def resolve_checkpoints_db_path() -> Path:
    return resolve_databases_dir() / "checkpoints.db"
# … context, display, cron, identity, metadata, persist, vectors
```

Delete / stop using: `soothe_checkpoints.db`, `context_engine.db`, flat `display.db` / `cron.db` / `identity.db` / `metadata.db`, `soothe.db`, `vector.db`.

---

## StrangeLoop / checkpoints (Phase 1 — critical)

1. `SQLitePersistenceBackend` holds a Registry-acquired Runtime (or is thin over it).  
2. Remove `StrangeLoopStateManager._writer_conn` / `_reader_pool` / `_init_writer_connection_sync` for sqlite.  
3. Replace per-manager `_flush_worker` with **one process-scoped coalesce flush** bound to the checkpoints Runtime (mirror `LoopPersistenceWriter` shape: managers enqueue; one worker drains). Reuse or extend existing writer abstractions where practical without forcing Postgres-only APIs onto SQLite incorrectly.  
4. All backend methods use `runtime.run_write` / `run_read` (reads must not go through the writer lock unless a read-your-writes edge requires it — prefer true reader leases).  

---

## Phased rollout

| Phase | Scope | Exit criteria |
|-------|--------|----------------|
| **P0** | `sqlite_runtime.py` + Registry + path resolvers + config field + unit tests | Runtime lease/serialize/pragma tests green |
| **P1** | checkpoints + StrangeLoopStateManager + shared_pool + daemon WAL shutdown | No private checkpoint connects; multi-manager stress OK |
| **P2** | context + display | CE + display via Runtime; display read/write leased |
| **P3** | cron + identity + metadata | Same |
| **P4** | nano persist + vectors (+ durability) | Paths under `databases/`; Runtime contract |
| **P5** | Cleanse dead code, wiki Quick Start / deployment paths, draft status → Implemented | `rg` legacy basenames clean in runtime pkgs; `verify_finally.sh` green |

Each phase is still a **cut** for its stores (no dual-path).

---

## Error handling

| Case | Behavior |
|------|----------|
| Registry closed | `RuntimeError` |
| `SQLITE_BUSY` after timeout | Propagate on durability writes |
| Vector extension missing | Existing in-memory fallback |
| Legacy files present | Ignored |

---

## Testing

| Test | Location (suggested) |
|------|----------------------|
| Runtime concurrent read lease uniqueness | `packages/soothe/tests/unit/persistence/test_sqlite_runtime.py` |
| `BEGIN IMMEDIATE` + busy_timeout pragmas | same |
| Registry refcount close | same |
| Resolvers → `databases/<purpose>.db` only | `test_sqlite_paths.py` |
| N managers share one checkpoints Runtime | `test_shared_sqlite_backend.py` (extend) |
| Display concurrent list/append | daemon display tests |
| Multi-loop stress smoke | integration under daemon or soothe (optional P1+) |
| Postgres path regression | existing unified persistence / checkpoint tests |

---

## Verification

After each phase and before commit:

```bash
./scripts/verify_finally.sh
```

Targeted while iterating:

```bash
cd packages/soothe && python -m pytest \
  tests/unit/persistence/test_sqlite_runtime.py \
  tests/unit/core/loop/state/persistence/ -q

cd packages/soothe-daemon && python -m pytest \
  tests/unit/display/ -q
```

Legacy basename guard (add to verify or run manually in P5):

```bash
rg -n 'soothe_checkpoints\.db|context_engine\.db|(^|/)soothe\.db|(^|/)vector\.db' \
  packages/soothe/src packages/soothe-daemon/src packages/soothe-nano/src \
  --glob '!**/tests/**' || true
```

---

## Operator note (docs)

Wiki Quick Start / deployment: SQLite files live under `~/.soothe/data/databases/`. Upgrading from older builds requires deleting obsolete flat `*.db` files; no automatic import.

---

## Progress checklist

- [x] P0 Runtime + paths + config  
- [x] P1 checkpoints + StrangeLoop use Runtime (per-manager private pools removed)  
- [x] P1b process-scoped coalesce flush for SQLite (`SqliteLoopFlushCoordinator`, parity with `LoopPersistenceWriter`)  
- [x] P2 context + display on Runtime  
- [x] P3 cron + identity + metadata on Runtime (metadata via durability → `databases/metadata.db` + PersistStore Runtime)  
- [x] P4 persist + vectors on Runtime  
- [x] P5 cleanse + docs + verify green  

---

## Related

- RFC-801 / RFC-802 / RFC-803 (2026-07-24 amendments)  
- IG-624 (unified backend xor — already done; do not reopen)  
- IG-550 / IG-571 (Postgres process writer — shape reference for P1)  
)
