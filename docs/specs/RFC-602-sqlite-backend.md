# RFC-602: SQLite Backend Specification

**RFC**: 602
**Title**: SQLite Backend for Persistence, Durability, and Vector Store
**Status**: Draft
**Kind**: Architecture Design + Implementation Interface Design
**Created**: 2026-04-04
**Dependencies**: RFC-000, RFC-001, RFC-300, RFC-401
**Related**: RFC-202

## Abstract

This RFC specifies SQLite backends across three storage layers in Soothe: (1) `SQLitePersistStore` for key-value persistence, (2) `SQLiteDurability` for thread lifecycle management, and (3) `SQLiteVecStore` for vector search using the sqlite-vec extension. SQLite becomes the default backend for local/development configurations, eliminating the need for external database services in single-node deployments while preserving PostgreSQL as the production option.

## Problem Statement

Current Soothe storage backends require:
1. **PostgreSQL** -- external service, Docker, or system package needed
2. **RocksDB** -- native library compilation, platform-specific
3. **JSON files** -- no concurrent access, no querying capability
4. **In-memory vector** -- non-persistent, brute-force search, no production viability

This creates a high barrier for local development, testing, and lightweight single-node deployments.

## Design Goals

1. **Zero external dependencies** -- SQLite is in Python stdlib; sqlite-vec is a pip-installable extension
2. **Drop-in replacement** -- implements existing `PersistStore`, `DurabilityProtocol`, and `VectorStoreProtocol` interfaces
3. **SQLite as local default** -- new users get working backends without any database setup
4. **PostgreSQL coexistence** -- existing PostgreSQL configs continue unchanged
5. **Single-file portability** -- `$SOOTHE_HOME/soothe.db` + `$SOOTHE_HOME/vector.db` is all that's needed

## Guiding Principles

1. **Protocol-First** -- SQLite backends implement the same protocols as existing backends
2. **Stdlib-First** -- Use Python's `sqlite3` stdlib where possible; add `sqlite-vec` only for vector
3. **WAL Mode** -- Enable WAL for concurrent read access on persistence DB
4. **Composition Over Inheritance** -- `SQLiteDurability` wraps `SQLitePersistStore` via `BasePersistStoreDurability`
5. **Graceful Degradation** -- If sqlite-vec is unavailable, fall back to in-memory vector store

---

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────┐
│  Config Layer (models.py)                           │
│  - "sqlite" added to Literal types                  │
│  - default_backend: "sqlite"                        │
│  - sqlite_path, sqlite_vec_path config fields       │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Resolver Layer (core/resolver/)                    │
│  - resolve_durability() handles "sqlite" case       │
│  - resolve_context() handles "vector-sqlite" case   │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Factory Layer (backends/*/__init__.py)             │
│  - create_persist_store(backend="sqlite")           │
│  - create_vector_store(provider="sqlite_vec")       │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────┬───────────────────┬───────────┐
│ SQLitePersistStore  │ SQLiteDurability  │ SQLiteVec │
│ (sqlite3 stdlib)    │ (composition)     │ (sqlite-vec)│
└─────────────────────┴───────────────────┴───────────┘
```

### File Structure

```
src/soothe/
├── backends/
│   ├── persistence/
│   │   ├── __init__.py           # MODIFIED: add "sqlite" case
│   │   └── sqlite_store.py       # NEW: SQLitePersistStore
│   ├── durability/
│   │   ├── __init__.py           # MODIFIED: add SQLiteDurability export
│   │   └── sqlite.py             # NEW: SQLiteDurability
│   └── vector_store/
│       ├── __init__.py           # MODIFIED: add "sqlite_vec" case
│       └── sqlite_vec.py         # NEW: SQLiteVecStore
└── core/resolver/
    ├── __init__.py               # MODIFIED: handle sqlite vector
    └── _resolver_infra.py        # MODIFIED: handle sqlite durability
```

### Database File Layout

```
$SOOTHE_HOME/
├── soothe.db          # Persistence + Durability (shared SQLite, WAL mode)
│   ├── soothe_kv      # Key-value table (PersistStore)
│   │   └── (key TEXT PK, data TEXT, namespace TEXT, created_at, updated_at)
│   └── (durability uses same table via namespace="durability")
│
└── vector.db          # Vector store (sqlite-vec, separate file)
    └── vec_{collection}  # One table per collection
        └── (id TEXT PK, embedding F32_BLOB(N), payload TEXT)
```

**Rationale for separate DB files**: sqlite-vec requires loading the extension, which should only happen for the vector DB. The persistence DB uses pure stdlib sqlite3 with no extensions.

---

## Component Responsibilities

### SQLitePersistStore

**File**: `backends/persistence/sqlite_store.py`

**Responsibilities**:
- Implement `PersistStore` protocol (save, load, delete, close)
- Single SQLite database with WAL mode
- Namespace isolation (like PostgreSQLPersistStore)
- Thread-safe access (sqlite3 serialization mode)
- Automatic table creation on first use

**Constructor**:
```python
class SQLitePersistStore:
    def __init__(self, db_path: str = "$SOOTHE_HOME/soothe.db",
                 namespace: str = "default") -> None:
```

**Table Schema**:
```sql
CREATE TABLE IF NOT EXISTS soothe_kv (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (namespace, key)
);
CREATE INDEX IF NOT EXISTS idx_soothe_kv_namespace ON soothe_kv(namespace);
```

**Implementation Details**:
- Enable WAL mode: `PRAGMA journal_mode=WAL`
- Enable foreign keys: `PRAGMA foreign_keys=ON`
- Use `check_same_thread=False` for thread safety
- JSON serialization via `json.dumps`/`json.loads`
- `save()` uses `INSERT OR REPLACE` for upsert semantics
- `close()` commits and closes connection

### SQLiteDurability

**File**: `backends/durability/sqlite.py`

**Responsibilities**:
- Wrap `SQLitePersistStore` via `BasePersistStoreDurability`
- No new logic -- pure composition

**Constructor**:
```python
class SQLiteDurability:
    def __init__(self, persist_store: PersistStore | None = None,
                 db_path: str | None = None) -> None:
```

**Implementation**:
- If `persist_store` provided, use it directly
- If `db_path` provided, create `SQLitePersistStore(db_path, namespace="durability")`
- Pass to `BasePersistStoreDurability.__init__()`

### SQLiteVecStore

**File**: `backends/vector_store/sqlite_vec.py`

**Responsibilities**:
- Implement `VectorStoreProtocol` (create_collection, insert, search, delete, update, get, list_records, delete_collection, reset, close)
- Use sqlite-vec extension for vector similarity search
- Async-compatible (run sync operations in thread pool executor)

**Constructor**:
```python
class SQLiteVecStore:
    def __init__(self, db_path: str = "$SOOTHE_HOME/vector.db",
                 collection: str = "default",
                 vector_size: int = 1536) -> None:
```

**Table Schema** (per collection, created in `create_collection()`):
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS vec_{collection} USING vec0(
    embedding FLOAT[{vector_size}] distance_metric={distance},
    payload TEXT
);
```

Note: sqlite-vec uses `vec0` virtual table module. The exact syntax depends on sqlite-vec version. For versions that don't support `vec0`, fall back to storing vectors as BLOBs and computing similarity in Python.

**Distance Metrics**:
- sqlite-vec supports: `cosine`, `l2`, `ip` (inner product)
- Map from protocol strings to sqlite-vec operators

**Async Compatibility**:
- `sqlite3` is synchronous; wrap in `asyncio.to_thread()` or `loop.run_in_executor()`
- Use `asyncio.Lock()` for write operations to prevent concurrent modification
- Reads can be concurrent (SQLite WAL mode)

**Extension Loading**:
```python
import sqlite_vec
conn.load_extension(sqlite_vec.loadable_path())
```

**Fallback Behavior**:
- If `sqlite-vec` is not installed, raise `ImportError` with helpful message
- Factory should catch and fall back to `InMemoryVectorStore`

---

## Config Layer Changes

### models.py

**PersistenceConfig** (modified):
```python
class PersistenceConfig(BaseModel):
    soothe_postgres_dsn: str = "postgresql://postgres:postgres@localhost:5432/soothe"
    default_backend: Literal["json", "rocksdb", "postgresql", "sqlite"] = "sqlite"
    sqlite_path: str | None = None  # None = $SOOTHE_HOME/soothe.db
```

**DurabilityProtocolConfig** (modified):
```python
class DurabilityProtocolConfig(BaseModel):
    backend: Literal["json", "rocksdb", "postgresql", "sqlite"] = "sqlite"
    checkpointer: Literal["postgresql", "sqlite"] = "sqlite"
    persist_dir: str | None = None
    thread_inactivity_timeout_hours: int = 72
```

**VectorStoreProviderConfig** (modified):
```python
class VectorStoreProviderConfig(BaseModel):
    name: str
    provider_type: Literal["pgvector", "weaviate", "in_memory", "sqlite_vec"] = "sqlite_vec"
    # pgvector options
    dsn: str | None = None
    pool_size: int = 5
    index_type: Literal["hnsw", "ivfflat", "none"] = "hnsw"
    # Weaviate options
    url: str | None = None
    api_key: str | None = None
    grpc_port: int = 50051
    # sqlite_vec options
    sqlite_vec_path: str | None = None  # None = $SOOTHE_HOME/vector.db
```

### Factory Changes

**create_persist_store()** (backends/persistence/__init__.py):
- Add `backend="sqlite"` case → return `SQLitePersistStore(persist_dir or default_path, namespace)`

**create_vector_store()** (backends/vector_store/__init__.py):
- Add `provider="sqlite_vec"` case → return `SQLiteVecStore(db_path, collection)`

### Resolver Changes

**resolve_durability()** (core/resolver/_resolver_infra.py):
- Add `"sqlite"` case → create `SQLitePersistStore` → wrap in `SQLiteDurability`

**resolve_context()** (core/resolver/__init__.py):
- Handle `"vector-sqlite"` backend → create `SQLiteVecStore` → pass to `VectorContext`

---

## Naming Conventions

| Pattern | Value |
|---------|-------|
| PersistStore backend | `"sqlite"` |
| Durability backend | `"sqlite"` |
| Checkpointer backend | `"sqlite"` |
| Vector store provider | `"sqlite_vec"` |
| Context backend string | `"vector-sqlite"` |
| DB file (persistence) | `soothe.db` |
| DB file (vector) | `vector.db` |

## Error Handling

1. **sqlite-vec not installed**: `ImportError` with message "sqlite-vec is required for vector storage. Install with: pip install sqlite-vec"
2. **DB path not writable**: `ValueError` with path and permission details
3. **Collection not created**: `RuntimeError` from `insert()`/`search()` before `create_collection()`
4. **Vector size mismatch**: `ValueError` if inserted vector length != collection vector_size

## Examples

### Minimal local config (SQLite defaults)
```bash
# No config needed - SQLite is default
soothe "What is the weather?"
```

### Explicit SQLite config
```yaml
persistence:
  default_backend: sqlite
  sqlite_path: /tmp/soothe.db

protocols:
  durability:
    backend: sqlite
```

### Mixed config (SQLite persistence + PostgreSQL vector)
```yaml
vector_stores:
  - name: pg_prod
    provider_type: pgvector
    dsn: postgresql://prod-db:5432/soothe

vector_store_router:
  default: "pg_prod:soothe_context"
```

## Migration Notes

- Existing PostgreSQL users: no changes needed, config is explicit
- New users: SQLite works out of the box
- `soothe checkhealth` should validate SQLite backends when configured
- No data migration needed -- SQLite is a new backend, not a replacement

---

## Related Documents

- [RFC-000](./RFC-000-system-conceptual-design.md) -- System Conceptual Design
- [RFC-001](./RFC-001-core-modules-architecture.md) -- Core Modules Architecture
- [RFC-300](./RFC-300-context-memory-protocols.md) -- Context & Memory Protocols
- [RFC Standard](./rfc-standard.md)
- [RFC Index](./rfc-index.md)
