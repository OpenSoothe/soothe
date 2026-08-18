# Design Draft: Process-Scoped SQLite Runtime (Isolation & Performance)

**Status**: Formalized → RFCs; **Implemented** via [IG-647](../impl/IG-647-sqlite-store-runtime.md)  
**Date**: 2026-07-24  
**Scope**: All SQLite durability surfaces under one process-scoped runtime model, Postgres-compatible control-plane shape, cut-over path/layout rename with **no** migration or compatibility shims.  
**Related**: [RFC-801](../specs/RFC-801-sqlite-backend.md), [RFC-802](../specs/RFC-802-persistence-architecture-refactor.md), [RFC-803](../specs/RFC-803-strangeloop-checkpoint-backend.md), AGENTS.md §10 (unified `persistence.default_backend`).

---

## Problem

SQLite mode is the local/default backend, but under concurrent StrangeLoop / daemon load it fails both **correctness** and **parity with PostgreSQL**:

1. **Multiple writers on one file** — `StrangeLoopStateManager` opens a per-loop writer + reader pool on the checkpoints DB while a shared `SQLitePersistenceBackend` also holds connections to the same file.
2. **Reads serialized through the writer** — checkpoint APIs route almost all I/O (including reads) through a single writer lock; reader pools are unused or unsafe.
3. **Unsafe connection sharing** — some reader “pools” return a connection then release the lease semaphore, allowing concurrent use of one `sqlite3.Connection`.
4. **Inconsistent pragmas** — WAL is common; `busy_timeout` and `BEGIN IMMEDIATE` are missing on several stores (manager, cron, identity, nano KV).
5. **Per-manager flush workers** — Postgres uses a process-scoped persistence writer; SQLite starts one flush worker per manager, multiplying write pressure on a single-writer engine.
6. **Scattered, inconsistent DB filenames** under `$SOOTHE_DATA_DIR` (`soothe_checkpoints.db`, `context_engine.db`, `soothe.db`, `vector.db`, …) with no single directory or naming rule.

PostgreSQL already has shared pools and a process-scoped writer. SQLite needs the **same lifecycle shape**, not multi-writer throughput claims.

---

## Goal

1. **Correctness floor** — no shared-connection races; no deferred lock-upgrade `SQLITE_BUSY` storms on write transactions; uniform busy handling.
2. **Postgres parity of control plane** — one process-scoped accessor per logical store; callers do not open private write connections.
3. **All SQLite durability surfaces** use that model: checkpoints, context, display, cron, identity, persist (KV/durability), metadata, vectors.
4. **Unified layout** — all daemon SQLite files live under `$SOOTHE_DATA_DIR/databases/` with a single naming scheme.
5. **Cut change** — new paths and names only; **no** migration, **no** fallback reads of legacy paths, **no** compatibility shims.

---

## Non-Goals

- Multi-process / multi-writer SQLite, or NFS-backed `$SOOTHE_DATA_DIR`.
- Merging multiple purpose files into one DB (multi-file layout stays; maps to RFC-802 / multi-DB Postgres).
- Matching PostgreSQL write QPS.
- Migrating or converting existing `~/.soothe/data/*.db` files.
- User-facing feature flags to “enable” safe mode (safe defaults are mandatory).

---

## Decisions (brainstorm)

| Topic | Decision |
|-------|----------|
| Success bar | Postgres control-plane parity (**C**) with correctness as non-negotiable floor (**A**) |
| Store scope | **All** SQLite durability surfaces |
| Deployment | Single writer daemon; optional **read-only** peekers (CLI/debug) |
| File layout | Keep **multi-file** (one Runtime per file); no cross-file transactions |
| Approach | **Process-scoped `SqliteStoreRuntime` per DB file** (Approach 2) |
| Path root | `$SOOTHE_DATA_DIR/databases/` (default `~/.soothe/data/databases/`) |
| Cutover | **Hard cut** — delete legacy path usage; operators start fresh |
| Naming | Unified `{purpose}.db` under `databases/` (table below) |

---

## Approaches considered

| # | Approach | Outcome |
|---|----------|---------|
| 1 | Per-store surgical fixes | Rejected — drifts from Postgres; easy to miss a store |
| **2** | **Process-scoped SQLite runtime per file** | **Chosen** |
| 3 | Full abstract PersistWriter for every store first | Deferred — apply only where Postgres already has a process writer (checkpoints/CE); wrap other stores onto Runtime first |

---

## Unified database layout

### Root

```text
$SOOTHE_DATA_DIR/databases/          # default: ~/.soothe/data/databases/
```

`SOOTHE_DATA_DIR` remains the data root; **all** SQLite purpose databases are children of `databases/`. Nothing durable is created as a bare `*.db` directly under `$SOOTHE_DATA_DIR` after this change.

### File names (cut rename)

| Purpose | New path | Maps to Postgres | Replaces (deleted; no shim) |
|---------|----------|------------------|----------------------------|
| StrangeLoop / loop checkpoints (+ in-proc LangGraph checkpoint file if co-located) | `databases/checkpoints.db` | `soothe_checkpoints` | `soothe_checkpoints.db`, legacy `loop_checkpoints.db` |
| Context Engine DAG + ledger | `databases/context.db` | host CE tables / checkpoints DSN usage today | `context_engine.db` |
| Display card ledger + goal snapshots | `databases/display.db` | `soothe_metadata` display tables | `$SOOTHE_DATA_DIR/display.db` |
| Cron jobs | `databases/cron.db` | `soothe_metadata` cron tables | `$SOOTHE_DATA_DIR/cron.db` |
| Identity (users, AKSK, tokens) | `databases/identity.db` | `soothe_metadata` identity tables | `$SOOTHE_DATA_DIR/identity.db` |
| ThreadInfo / durability metadata | `databases/metadata.db` | `soothe_metadata` | `$SOOTHE_DATA_DIR/metadata.db` |
| Persist KV (nano namespaces, durability payload) | `databases/persist.db` | JSONB / metadata namespaces | `$SOOTHE_HOME/soothe.db` or `$SOOTHE_DATA_DIR/soothe.db` |
| Vector store (sqlite-vec) | `databases/vectors.db` | `soothe_vectors` | `$SOOTHE_HOME/vector.db` |

**Naming rule:** lowercase English purpose noun (plural only when the domain is inherently plural: `vectors`). No `soothe_` prefix on filenames — the product and `databases/` directory already scope them. Extension always `.db`.

**Resolver API:** single module (host + nano as appropriate) exposing `resolve_databases_dir()` and `resolve_<purpose>_db_path()` returning only the new paths. Grep must find **zero** remaining references to legacy filenames in runtime code after impl.

**Operator note (user-visible):** upgrading requires removing old SQLite files under `$SOOTHE_DATA_DIR` / `$SOOTHE_HOME` and letting the daemon recreate `databases/*.db`. No automatic import.

---

## Architecture

```text
Daemon start (sqlite mode)
  └─ SqliteRuntimeRegistry
        path → SqliteStoreRuntime (refcount)

Each SqliteStoreRuntime (one per databases/*.db):
  • single writer connection
  • serialized write queue / lock
  • leased reader pool (pop / use / return)
  • uniform PRAGMAs
  • optional WAL checkpoint on shutdown

Store adapters (thin):
  checkpoints | context | display | cron | identity | metadata | persist | vectors
       │
       └─ runtime.run_write(fn) / runtime.run_read(fn)

PostgreSQL mode:
  • unchanged shared pools + process-scoped writer
  • same store protocols; no SqliteRuntimeRegistry
```

**Package placement**

| Piece | Package |
|-------|---------|
| `SqliteStoreRuntime`, `SqliteRuntimeRegistry`, path resolvers for host stores | `soothe` |
| Display adapter (daemon-owned store) | `soothe-daemon` (uses host runtime/paths or shared sdk path helpers as appropriate) |
| Nano persist + vectors | `soothe-nano` — standalone mini-runtime with the **same contract**; under daemon, prefer injecting/resolving the same path convention (`databases/persist.db`, `databases/vectors.db`) without reversing the package DAG |

---

## Components

### `SqliteStoreRuntime`

- **`run_write(sync_fn)`** — exclusive writer; `BEGIN IMMEDIATE`; commit/rollback; executed via `asyncio.to_thread` so the event loop stays free.
- **`run_read(sync_fn)`** — lease one reader connection for the duration of `sync_fn` only; never hand out a live connection without a lease.
- **Pragmas (mandatory on every connection):** `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=<config, default 60000>`.
- **No public raw `sqlite3.connect`** for daemon hot paths.

### `SqliteRuntimeRegistry`

- Keyed by resolved absolute path.
- `acquire(path) → Runtime`, `release(path)`, `close_all()` on daemon shutdown.
- Shutdown runs `PRAGMA wal_checkpoint(TRUNCATE)` per open Runtime (replace ad-hoc path lists).

### StrangeLoop / checkpoints

- Remove per-`StrangeLoopStateManager` SQLite writer and reader pools.
- All checkpoint and loop-metadata I/O goes through the **checkpoints** Runtime (shared with `SQLitePersistenceBackend`, or merge into one backend that only uses the Runtime).
- Replace per-manager flush workers with **one coalescing flush worker bound to the checkpoints Runtime** (mirrors Postgres process-scoped writer). Managers only enqueue coalesced state.

### Other stores

- **Context / display / cron / identity / metadata / persist / vectors** — drop private long-lived write connections; adapt to `run_write` / `run_read` on their Runtime.
- **Display** — all access (including reads) under Runtime lease; fix today’s unlocked read vs locked write on one connection.
- **Vectors** — load sqlite-vec only on the `vectors.db` Runtime connections.

### Read-only peekers

- Helper: open `file:…?mode=ro` (or equivalent) against `databases/<purpose>.db` for CLI/debug.
- Must not register as a write Runtime; must not be used by the daemon write path.
- Document snapshot lag under WAL.

---

## Data flow

**Write:** store method → `runtime.run_write` → writer lock → `BEGIN IMMEDIATE` → statements → `COMMIT` → unlock.

**Read:** store method → `runtime.run_read` → lease reader → query → return lease.

**Cross-file lifecycle (e.g. loop purge):** ordered best-effort calls across Runtimes (`checkpoints` → `context` → `display` → …). Same non-atomicity class as multi-database PostgreSQL. No distributed transaction.

**Config (optional, defaults on):**

```yaml
persistence:
  default_backend: sqlite
  sqlite:
    reader_pool_size: 3          # per Runtime; file DB does not need large pools
    busy_timeout_ms: 60000
    wal_checkpoint_on_shutdown: true
```

Paths are **not** configurable per file in v1 (convention only). Cut change avoids path override shims.

---

## Error handling

| Case | Behavior |
|------|----------|
| Runtime closed / registry missing | Fail loud (`RuntimeError`) |
| `SQLITE_BUSY` after busy_timeout | Propagate to caller on durability paths (checkpoints, identity, cron, display writes) |
| Context Engine soft-fail | Prefer metric + warning; do not silently drop if the write was requested for durability — align with store contract during impl |
| Vector extension missing | Existing in-memory fallback |
| Legacy `*.db` still on disk | Ignored; never opened |

---

## Testing

1. **Runtime lease** — concurrent `run_read` never shares one connection; concurrent `run_write` serializes.
2. **Pragma contract** — every Runtime connection has WAL + busy_timeout; writes use `BEGIN IMMEDIATE`.
3. **StrangeLoop** — N managers share one checkpoints Runtime; zero private `sqlite3.connect` to `checkpoints.db` outside Runtime.
4. **Path cut** — unit tests assert resolvers return `$SOOTHE_DATA_DIR/databases/<purpose>.db` only; no legacy basename.
5. **Stress** — concurrent heartbeat + checkpoint + context save + display append without connection errors.
6. **RO peeker** — read during daemon write does not take write ownership.
7. **Postgres smoke** — same store API sequences still pass on `default_backend: postgresql` (unchanged).

---

## Rollout (implementation phases)

Single design; staged IGs / PRs. Each phase is still a **cut** for its stores (no dual-path).

1. **Paths + Runtime + Registry** — resolvers, `databases/` layout, pragma contract; migrate **checkpoints** + remove StrangeLoop private pools / per-manager flush.
2. **context** + **display**
3. **cron** + **identity** + **metadata**
4. **persist** + **vectors** (nano + host wiring)
5. **Cleanse** — delete dead reader-pool code, old path helpers, stale docs/wiki references; document operator wipe of legacy files.

---

## Operator / docs impact

- Quick Start / deployment wiki: SQLite files live under `~/.soothe/data/databases/`.
- Breaking change callout: previous flat `$SOOTHE_DATA_DIR/*.db` and `$SOOTHE_HOME/soothe.db` / `vector.db` are obsolete; delete before restart if upgrading from an older build.
- Production multi-writer / multi-host remains **PostgreSQL**.

---

## Success criteria

- [ ] One `SqliteStoreRuntime` per `databases/*.db` in sqlite mode; no store-owned write connections on the hot path.
- [ ] StrangeLoop checkpoint flush is process-scoped (not per-manager).
- [ ] Grep for legacy basenames (`soothe_checkpoints.db`, `context_engine.db`, `soothe.db`, `vector.db` as data paths) is clean in runtime packages.
- [ ] Concurrent multi-loop stress test passes without `database is locked` / connection race failures under default timeouts.
- [ ] PostgreSQL mode behavior and tests remain green with no required SQLite Runtime.
)
