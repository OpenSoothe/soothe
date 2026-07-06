# Persistence Backends

Generic key-value storage via `AsyncPersistStore`. Persistence backends are the foundational storage layer — durability, context, and other protocols compose on top of them. They store arbitrary JSON-serializable data indexed by string keys, with namespace isolation and prefix-based listing.

---

## What Persistence Backends Do

Persistence backends provide six core operations:

- **`save(key, value)`** — Store a JSON-serializable dict, overwriting if the key exists (upsert semantics).
- **`load(key)`** — Retrieve a value by key, or `None` if not found.
- **`delete(key)`** — Remove a key, returning `True` if it existed.
- **`exists(key)`** — Check key existence without loading the value.
- **`list_keys(prefix)`** — List keys, optionally filtered by prefix (enables namespace listing).
- **`clear()`** — Delete all keys in the namespace.

The interface is intentionally minimal — it's a key-value store, not a document database. Higher-level backends (durability, memory) build domain-specific semantics on top of these primitives.

**Namespace pattern**: Keys use prefixes for logical separation (`thread:abc123`, `memory:xyz789`, `config:default`). The `list_keys(prefix)` operation enables efficient namespace enumeration.

---

## Backend Comparison

| Feature | SQLitePersistStore | PostgreSQLPersistStore |
|---------|-------------------|------------------------|
| Storage engine | SQLite (file-based) | PostgreSQL |
| JSON storage | Serialized JSON in TEXT column | Native JSONB |
| Concurrent writes | ❌ Single writer (asyncio.Lock) | ✅ Connection pool |
| Connection pooling | Reader pool (default 5, WAL mode) | ✅ (default 10 connections) |
| Namespace isolation | Key prefix | Key prefix + separate namespace column |
| Async I/O | `asyncio.to_thread` (non-blocking) | psycopg async pool |
| Setup complexity | Low — zero external deps | Medium — requires PostgreSQL |
| Production readiness | ⚠️ Local/dev, single-process | ✅ Multi-process, scalable |
| Connection recovery | N/A (local file) | ✅ Auto-reset on recoverable errors |

Both implement the same interface identically. The choice is purely about the storage engine's concurrency and operational characteristics.

---

## Available Backends

### SQLitePersistStore

Local key-value storage using SQLite with WAL mode and a reader pool.

**Key characteristics**:
- **WAL mode** enables concurrent reads alongside a single writer. The writer connection is serialized via `asyncio.Lock` (SQLite connections are not thread-safe across workers).
- **Reader pool** (default 5 connections) allows parallel reads across concurrent loops — critical for multi-loop scenarios.
- **Namespace isolation** via key prefixing, matching the PostgreSQL backend's pattern.
- **Lazy connection initialization** — connections are created on first use, not at construction.
- All sync SQLite operations run via `asyncio.to_thread` to avoid blocking the event loop (IG-258 Phase 2).

**When to choose**: Local development, single-process production, embedded deployments, or any scenario avoiding external database dependencies.

**Minimal config**:
```yaml
protocols:
  persistence:
    enabled: true
    backend: sqlite
    persist_dir: ~/.soothe/persistence
```

Source: `packages/soothe/src/soothe/backends/persistence/sqlite_store.py`

---

### PostgreSQLPersistStore

Production-grade key-value storage using PostgreSQL with JSONB and async connection pooling.

**Key characteristics**:
- **Native JSONB** storage — efficient JSON querying and indexing at the database level, no serialization overhead.
- **Connection pool** via `psycopg_pool.AsyncConnectionPool` (default 10 connections, min 1). Supports concurrent multi-process access.
- **Automatic table creation** with indexes on key and namespace columns.
- **Connection recovery** — detects transient PostgreSQL failures (`OperationalError`, `InterfaceError`, `AdminShutdown`, `CrashShutdown`, `ConnectionFailure`) and automatically resets the pool. Non-recoverable errors propagate immediately.
- **Async-safe lazy initialization** with `asyncio.Lock` to prevent race conditions during pool creation.

**When to choose**: Multi-process production, horizontal scaling, or when PostgreSQL is already deployed for other Soothe backends (durability, vector store).

**Minimal config**:
```yaml
protocols:
  persistence:
    enabled: true
    backend: postgresql
    dsn: postgresql://localhost/soothe
    pool_size: 10
```

Source: `packages/soothe/src/soothe/backends/persistence/postgres_store.py`

---

## Performance Characteristics

| Operation | SQLite | PostgreSQL | Notes |
|-----------|--------|------------|-------|
| `save()` | ~10-20ms | ~20-50ms | PG has pool + network overhead |
| `load()` | ~5-10ms | ~10-30ms | SQLite is faster for local reads |
| `delete()` | ~10-20ms | ~20-50ms | Single-writer on SQLite |
| `exists()` | ~5-10ms | ~10-30ms | Fast check, no payload |
| `list_keys()` | ~50-100ms | ~50-200ms | Index scan; PG adds network |
| `clear()` | ~50-100ms | ~50-200ms | Bulk delete |

**SQLite is faster for single-process workloads** because there's no network overhead. PostgreSQL wins under concurrent multi-process load where SQLite's single-writer lock becomes a bottleneck.

---

## Production Gotchas

1. **SQLite writer serialization**: Even with WAL mode, all writes go through a single connection guarded by `asyncio.Lock`. Under write-heavy concurrent workloads, this creates contention. Monitor write latency under load.

2. **PostgreSQL pool sizing**: The default pool size (10) matches the checkpointer pattern. For high-concurrency scenarios, increase `pool_size`. Too few connections cause queueing; too many exhaust database resources.

3. **Connection failure handling**: `PostgreSQLPersistStore` resets the pool on recoverable errors but propagates non-recoverable ones. Ensure your error handling accounts for both — a `PoolReset` may leave the store temporarily without a pool during reset.

4. **Key naming conventions**: Use consistent prefix patterns (`namespace:key`). The `list_keys(prefix)` operation relies on `LIKE prefix%` queries — inconsistent naming defeats namespace isolation.

5. **No native transactions across keys**: Each `save()`/`delete()` is an independent transaction. Multi-key atomic operations require application-level coordination.

6. **SQLite database file growth**: WAL mode creates `-wal` and `-shm` sidecar files. These are normal and are checkpointed automatically. Don't delete them while the database is in use.

---

## Integration Patterns

Persistence backends are the foundation other backends build on:

- **Durability**: `BasePersistStoreDurability` delegates all thread storage to an `AsyncPersistStore` instance. `SQLiteDurability` creates a `SQLitePersistStore` with namespace=`durability`; `PostgreSQLDurability` receives a pre-built store.
- **General-purpose storage**: Use for config, metadata, and arbitrary state — `save("config:default", config_dict)`, `save("thread_state:abc123", state)`.
- **Namespace listing**: `list_keys("thread:")` returns all thread keys; `list_keys("memory:")` returns all memory keys.

---

## Related Documentation

- **[Backends Overview](index.md)** — Backend layer introduction
- **[Durability Backends](durability-backends.md)** — Composes on top of PersistStore
- **[Memory Backends](memory-backends.md)** — Memory storage patterns
