# Durability Backends

Thread lifecycle and state management via `DurabilityProtocol`. Durability backends persist thread metadata, track status transitions (active → suspended → archived), and maintain a thread index for fast listing. They are the foundation of Soothe's crash-recovery and durable execution model.

---

## What Durability Backends Do

Durability backends manage the *lifecycle* of threads — not their execution state. They handle:

- **Thread creation**: Generates a thread ID, stores `ThreadInfo` with metadata (tags, plan summary, priority, policy profile), and adds the thread to an index for fast listing.
- **Status transitions**: `suspend` pauses a thread (persisting its state for later resumption); `resume` reactivates it; `archive` marks it complete (and triggers memory consolidation).
- **Thread listing**: Iterates the thread index and applies filters (status, tags, creation time range).
- **Metadata updates**: Merges new metadata into existing thread records.

All durability backends inherit from `BasePersistStoreDurability`, which delegates storage to an `AsyncPersistStore` instance. The backend classes themselves are thin wrappers — the only difference is *which persist store they use*.

Source: `packages/soothe/src/soothe/backends/durability/base.py`

---

## Backend Comparison

| Feature | SQLiteDurability | PostgreSQLDurability |
|---------|------------------|---------------------|
| Storage engine | SQLite (file-based) | PostgreSQL (JSONB) |
| Concurrent writes | ❌ Single writer (serialized via lock) | ✅ Connection pool |
| Connection pooling | Reader pool (WAL mode) | ✅ (psycopg_pool, default 10) |
| Setup complexity | Low — zero external dependencies | Medium — requires PostgreSQL + psycopg |
| Production readiness | ⚠️ Local/dev, single-process | ✅ Multi-process, scalable |
| Namespace isolation | ✅ (key prefix) | ✅ (key prefix + JSONB) |
| Default DB path | `$SOOTHE_DATA_DIR/metadata.db` | Configured via DSN |

Both backends serialize `ThreadInfo` as JSON. The difference is purely in the underlying storage engine's concurrency and scalability characteristics.

---

## Available Backends

### SQLiteDurability

Local persistence using SQLite. The default backend for development and single-process deployments.

**Key characteristics**:
- Wraps `SQLitePersistStore` with a `durability` namespace, isolating thread records from other data in the same database.
- Uses WAL mode for concurrent reads with a single serialized writer (asyncio.Lock ensures write consistency).
- Defaults to `$SOOTHE_DATA_DIR/metadata.db` — deliberately separate from LangGraph checkpoints for clarity.
- Reader pool (default 5 connections) enables parallel reads across concurrent loops.

**When to choose**: Local development, single-process production, or any scenario where external database dependencies are undesirable.

**Minimal config**:
```yaml
protocols:
  durability:
    enabled: true
    backend: sqlite
    persist_dir: ~/.soothe/durability
```

Source: `packages/soothe/src/soothe/backends/durability/sqlite.py`

---

### PostgreSQLDurability

Production-grade persistence using PostgreSQL with JSONB storage and connection pooling.

**Key characteristics**:
- Requires a pre-configured `PostgreSQLPersistStore` instance (passed in at construction — no auto-creation of the store).
- Leverages PostgreSQL's native JSONB for efficient JSON querying and indexing.
- Connection pool (default 10 connections) supports concurrent multi-process access.
- Inherits all lifecycle logic from `BasePersistStoreDurability` — no behavior difference, only storage engine.

**When to choose**: Multi-process production deployments, horizontal scaling, or when you already run PostgreSQL for other Soothe backends (vector store, persistence).

**Minimal config**:
```yaml
protocols:
  durability:
    enabled: true
    backend: postgresql
    dsn: postgresql://localhost/soothe
    pool_size: 10
```

Source: `packages/soothe/src/soothe/backends/durability/postgresql.py`

---

## Thread Lifecycle

Thread status uses string literals, not an enum. Three durable statuses exist:

| Status | Meaning | Trigger |
|--------|---------|---------|
| `active` | Currently running or newly created | `create_thread()` or `resume_thread()` |
| `suspended` | Paused — state persisted for later resumption | `suspend_thread()` |
| `archived` | Completed — triggers memory consolidation | `archive_thread()` |

**Key behavior**: `resume_thread()` supports **prefix matching**. If the provided thread ID is a prefix matching one or more threads, the first match is resumed. This allows users to reference threads by short ID prefixes (e.g., `abc` instead of `abc123def456...`).

**Archive triggers consolidation**: When a thread is archived, the system consolidates its significant interactions into long-term memory. This is why `archive` is distinct from `suspend` — archiving is terminal.

---

## Performance Characteristics

| Operation | SQLite | PostgreSQL | Notes |
|-----------|--------|------------|-------|
| `create_thread()` | ~10-20ms | ~20-50ms | Pool overhead on PG |
| `get_thread()` | ~5-10ms | ~10-30ms | Network on PG |
| `suspend/resume/archive` | ~10-20ms | ~20-50ms | JSON serialization + save |
| `list_threads()` | ~50-100ms | ~50-200ms | Index scan, loads all threads |
| `update_metadata()` | ~10-20ms | ~20-50ms | Merge + save |

**`list_threads()` is the slowest operation** because it loads every thread from the index and applies filters in Python. For large thread counts, consider filtering by status or tags to reduce the working set.

---

## Production Gotchas

1. **SQLite single-writer bottleneck**: WAL mode allows concurrent readers, but all writes are serialized through an asyncio.Lock. Under heavy write contention (many threads being created/suspended simultaneously), throughput is limited.

2. **PostgreSQL connection resilience**: `PostgreSQLPersistStore` detects recoverable connection errors (`OperationalError`, `InterfaceError`, `AdminShutdown`, `ConnectionFailure`) and automatically resets the pool. Non-recoverable errors propagate immediately.

3. **Thread index consistency**: The thread index is stored as a single key-value entry. If the process crashes mid-update, the index may be inconsistent with stored threads. The index is rebuilt from stored thread keys on demand.

4. **Namespace separation**: SQLiteDurability uses the `durability` namespace by default, keeping thread records separate from other data (checkpoints, context) in the same SQLite database. PostgreSQL achieves the same via table-level or key-prefix isolation.

5. **No built-in TTL or cleanup**: Archived threads persist indefinitely. Implement external cleanup if thread accumulation is a concern.

---

## Integration with SootheRunner

The runner uses durability backends in two phases:

- **Pre-stream**: Creates a new thread (if no `thread_id` given) or resumes an existing one.
- **Post-stream**: Suspends the thread if paused, or archives it if complete.

This means every Soothe execution touches the durability backend at least twice. Backend choice directly impacts per-run latency.

---

## Related Documentation

- **[Backends Overview](index.md)** — Backend layer introduction
- **[Persistence Backends](persistence-backends.md)** — The PersistStore layer durability builds on
- **[Memory Backends](memory-backends.md)** — Triggered on thread archival
- **[Thread Management](../thread-management.md)** — Thread lifecycle details
