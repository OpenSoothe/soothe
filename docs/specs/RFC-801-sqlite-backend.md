# RFC-801: SQLite Backend Specification

**RFC**: 801  
**Title**: SQLite Backend for Persistence, Durability, and Vector Store  
**Status**: Draft  
**Kind**: Architecture Design + Implementation Interface Design  
**Created**: 2026-04-04  
**Updated**: 2026-07-24  
**Dependencies**: RFC-000, RFC-001, RFC-302, RFC-303, RFC-802  
**Related**: RFC-803, RFC-229, RFC-307, RFC-413, RFC-624  
**Note**: Moved from 6xx (RFC-801) per RFC-900 reclassification  
**Design draft**: [2026-07-24-sqlite-runtime-isolation-performance-design.md](../drafts/2026-07-24-sqlite-runtime-isolation-performance-design.md)

## Abstract

This RFC specifies SQLite as the local/development persistence backend across Soothe durability surfaces, and defines the **process-scoped `SqliteStoreRuntime`** control plane that mirrors PostgreSQL shared-pool / process-writer lifecycle shape. SQLite remains a single-writer, multi-reader (WAL) engine: correctness and isolation come from one Runtime per database file, not from multi-writer throughput. All purpose databases live under `$SOOTHE_DATA_DIR/databases/` with unified `{purpose}.db` names. Layout changes are a **hard cut** — no migration or legacy path shims.

## Problem Statement

SQLite is the default local backend, but concurrent StrangeLoop / daemon load exposed:

1. Multiple independent writers (and unsafe reader pools) on the same checkpoint file  
2. Reads serialized through a single writer lock, defeating WAL reader concurrency  
3. Inconsistent `busy_timeout` / missing `BEGIN IMMEDIATE` (lock-upgrade `SQLITE_BUSY`)  
4. Per-manager flush workers vs PostgreSQL’s process-scoped writer  
5. Scattered filenames (`soothe_checkpoints.db`, `context_engine.db`, `soothe.db`, `vector.db`, …)

PostgreSQL already provides shared pools and a process-scoped write pipeline (RFC-802, RFC-803). SQLite needs the same **control-plane shape**.

## Design Goals

1. **Protocol parity** — SQLite adapters implement the same store protocols as PostgreSQL  
2. **Process-scoped Runtime** — one `SqliteStoreRuntime` per DB file; no store-owned write connections on the hot path  
3. **Correctness floor** — leased readers, serialized writes, WAL + `busy_timeout` + `BEGIN IMMEDIATE`  
4. **Postgres-shaped lifecycle** — registry / acquire / release / shutdown checkpoint, analogous to shared pools  
5. **Unified layout** — `$SOOTHE_DATA_DIR/databases/{purpose}.db` only  
6. **Hard cut** — no reading legacy paths; operators wipe old files on upgrade  
7. **Graceful vector fallback** — if sqlite-vec is unavailable, fall back to in-memory vector store  

## Guiding Principles

1. **Protocol-First** — stores stay thin; Runtime owns connections  
2. **Stdlib-First** — `sqlite3` for all non-vector DBs; sqlite-vec only on `vectors.db`  
3. **WAL Mode** — concurrent readers with a single writer  
4. **Single writer daemon** — optional read-only peekers (CLI/debug); multi-writer deployments use PostgreSQL  
5. **Multi-file by purpose** — same logical separation as RFC-802 multi-database Postgres; no cross-file transactions  
6. **Composition** — `SQLiteDurability` wraps persist KV via namespace  

---

## Architecture

### Control plane

```text
Daemon start (persistence.default_backend=sqlite)
  └─ SqliteRuntimeRegistry
        absolute path → SqliteStoreRuntime (refcount)

SqliteStoreRuntime (one per databases/*.db):
  • single writer connection + serialized write path
  • leased reader pool (pop / use / return; never share across tasks)
  • PRAGMA journal_mode=WAL; foreign_keys=ON; busy_timeout=<ms>
  • run_write: BEGIN IMMEDIATE → fn(conn) → COMMIT | ROLLBACK
  • run_read: lease reader → fn(conn) → return lease
  • shutdown: PRAGMA wal_checkpoint(TRUNCATE)

Store adapters (checkpoints, context, display, cron, identity,
metadata, persist, vectors) call Runtime APIs only.
```

PostgreSQL mode does **not** construct `SqliteRuntimeRegistry`. Host protocols and store APIs stay backend-agnostic.

### Package placement

| Piece | Package |
|-------|---------|
| `SqliteStoreRuntime`, `SqliteRuntimeRegistry`, host path resolvers | `soothe` |
| Display store adapter | `soothe-daemon` |
| Persist KV + vectors (+ nano path resolvers) | `soothe-nano` — same Runtime **contract**; standalone mini-runtime; under daemon resolve `databases/persist.db` / `databases/vectors.db` without reversing the package DAG |

### Database file layout (normative)

Root: `$SOOTHE_DATA_DIR/databases/` (default `~/.soothe/data/databases/`).

| Purpose | File | PostgreSQL mapping (RFC-802) |
|---------|------|------------------------------|
| StrangeLoop / loop checkpoints | `checkpoints.db` | `soothe_checkpoints` |
| Context Engine DAG + ledger | `context.db` | host CE (checkpoints/metadata DSN usage) |
| Display card ledger + goal snapshots | `display.db` | `soothe_metadata` display tables |
| Cron jobs | `cron.db` | `soothe_metadata` cron tables |
| Identity | `identity.db` | `soothe_metadata` identity tables |
| ThreadInfo / durability metadata | `metadata.db` | `soothe_metadata` |
| Persist KV (namespaces) | `persist.db` | metadata / JSONB namespaces |
| Vectors (sqlite-vec) | `vectors.db` | `soothe_vectors` |

**Naming rule:** lowercase purpose noun; plural only for inherently plural domains (`vectors`); no `soothe_` filename prefix; always `.db`.

**Cut change:** the following legacy basenames MUST NOT be opened by runtime code: `soothe_checkpoints.db`, `loop_checkpoints.db`, `langgraph_checkpoints.db`, `context_engine.db`, `soothe.db`, `vector.db`, and any purpose `.db` placed directly under `$SOOTHE_DATA_DIR` (not under `databases/`). No migration, no fallback shim.

**Rationale for separate files:** purpose lifecycle / backup granularity (RFC-802); sqlite-vec extension load only on `vectors.db`.

---

## Component Responsibilities

### `SqliteStoreRuntime` / `SqliteRuntimeRegistry`

**Responsibilities:**
- Own all connections for one absolute DB path  
- Serialize writes; lease readers  
- Apply mandatory pragmas on every connection  
- Refcount via registry; `close_all` on daemon shutdown  

**Config (optional; defaults mandatory-safe):**

```yaml
persistence:
  default_backend: sqlite
  sqlite:
    reader_pool_size: 3
    busy_timeout_ms: 60000
    wal_checkpoint_on_shutdown: true
```

Per-file path overrides are **out of scope** for v1 (convention only — avoids shim surface).

### Store adapters

Each adapter implements its existing protocol and delegates I/O to its Runtime:

| Adapter | DB file | Notes |
|---------|---------|--------|
| StrangeLoop / checkpoint backend | `checkpoints.db` | No per-manager `sqlite3.connect`; see RFC-803 flush amendment |
| Context Engine persistence | `context.db` | Shared Runtime across loop_ids |
| Display card store | `display.db` | Reads and writes under Runtime lease |
| Cron job store | `cron.db` | |
| Identity service | `identity.db` | |
| ThreadInfo / durability metadata | `metadata.db` | |
| `SQLitePersistStore` | `persist.db` | Namespace isolation |
| `SQLiteVecStore` | `vectors.db` | Load extension only here |

### `SQLitePersistStore`

- Implements `PersistStore` (`save`, `load`, `delete`, `close` / list)  
- Table `soothe_kv` with `(namespace, key)` primary key  
- JSON serialization via `json.dumps` / `json.loads`  
- Default path: `$SOOTHE_DATA_DIR/databases/persist.db`  

### `SQLiteDurability`

- Wraps `SQLitePersistStore` via `BasePersistStoreDurability` with `namespace="durability"` (or equivalent)  
- No private connection logic  

### `SQLiteVecStore`

- Implements `VectorStoreProtocol`  
- Default path: `$SOOTHE_DATA_DIR/databases/vectors.db`  
- Async via Runtime / `asyncio.to_thread`  
- Fallback to in-memory if sqlite-vec unavailable  

### Read-only peekers

CLI/debug MAY open `file:<path>?mode=ro` (or equivalent) against `databases/*.db`. Peekers MUST NOT register as write Runtimes and MUST NOT be used by the daemon write path. Snapshot lag under WAL is expected.

---

## Cross-file operations

Loop purge and similar lifecycle ops issue ordered best-effort calls across Runtimes (e.g. `checkpoints` → `context` → `display` → …). There is **no** cross-file atomic transaction — same class of guarantee as multi-database PostgreSQL (RFC-802).

---

## Error Handling

1. **Runtime closed / missing** — `RuntimeError`  
2. **`SQLITE_BUSY` after busy_timeout** — propagate on durability paths (checkpoints, identity, cron, display writes)  
3. **sqlite-vec missing** — factory falls back to in-memory with clear log  
4. **DB path not writable** — fail startup / first open with path detail  
5. **Legacy files on disk** — ignored; never opened  

---

## Naming Conventions

| Pattern | Value |
|---------|-------|
| PersistStore backend | `"sqlite"` |
| Durability / checkpointer inherit | `persistence.default_backend` |
| Vector provider | `"sqlite_vec"` |
| Databases directory | `$SOOTHE_DATA_DIR/databases/` |
| Purpose files | `checkpoints.db`, `context.db`, `display.db`, `cron.db`, `identity.db`, `metadata.db`, `persist.db`, `vectors.db` |
| Runtime types | `SqliteStoreRuntime`, `SqliteRuntimeRegistry` |

---

## Examples

### Minimal local config

```yaml
persistence:
  default_backend: sqlite
```

Creates files under `~/.soothe/data/databases/` on first use.

### Explicit sqlite Runtime tuning

```yaml
persistence:
  default_backend: sqlite
  sqlite:
    reader_pool_size: 3
    busy_timeout_ms: 60000
```

### Production

Use `persistence.default_backend: postgresql` (RFC-802). SQLite is not a multi-writer / multi-host backend.

---

## Operator cutover

Upgrading from pre-Runtime builds:

1. Stop the daemon  
2. Delete obsolete flat `$SOOTHE_DATA_DIR/*.db` and `$SOOTHE_HOME/soothe.db` / `vector.db` (or archive offline)  
3. Start daemon — recreates `databases/*.db`  

No automatic import.

---

## Testing (normative expectations)

1. Concurrent `run_read` never shares one connection; concurrent `run_write` serializes  
2. Every Runtime connection has WAL + busy_timeout; writes use `BEGIN IMMEDIATE`  
3. N StrangeLoop managers share one `checkpoints` Runtime; zero private writer pools  
4. Resolvers return only `$SOOTHE_DATA_DIR/databases/<purpose>.db`  
5. Multi-loop stress (heartbeat + checkpoint + context + display) without connection races  
6. RO peeker does not take write ownership  
7. PostgreSQL mode tests remain green without SqliteRuntime  

---

## Implementation phases

See [IG-647](../impl/IG-647-sqlite-store-runtime.md) for concrete module layout, types, phased rollout, and verify commands.

1. Paths + Runtime + Registry; migrate checkpoints; remove StrangeLoop private pools / per-manager SQLite flush  
2. `context` + `display`  
3. `cron` + `identity` + `metadata`  
4. `persist` + `vectors`  
5. Cleanse dead code and docs; operator wipe note in wiki  

---

## Change History

| Date | Change |
|------|--------|
| 2026-04-04 | Initial Draft — PersistStore / Durability / VecStore |
| 2026-07-24 | Process-scoped `SqliteStoreRuntime`; `$SOOTHE_DATA_DIR/databases/` unified names; hard cut (no shims); Postgres control-plane parity |

---

## Related Documents

- [RFC-802](./RFC-802-persistence-architecture-refactor.md) — multi-purpose layout, mode validation  
- [RFC-803](./RFC-803-strangeloop-checkpoint-backend.md) — checkpoint flush / unified write pipeline  
- [Design draft](../drafts/2026-07-24-sqlite-runtime-isolation-performance-design.md)  
- [RFC Index](./rfc-index.md)  
)
