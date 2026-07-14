# Implementation Guide: SQLite Backend (IG-126)

**Guide**: IG-126
**Title**: SQLite Backend for Persistence, Durability, and Vector Store
**Created**: 2026-04-04
**Related RFCs**: RFC-602
**Dependencies**: RFC-001, RFC-300

## Overview

This implementation guide covers the full SQLite backend suite: `SQLitePersistStore`, `SQLiteDurability`, and `SQLiteVecStore` (sqlite-vec). Makes SQLite the default backend for local development.

## Prerequisites

- [x] RFC-602 draft created
- [ ] `sqlite-vec` added to pyproject.toml
- [ ] Existing codebase understanding (completed via exploration agents)

## Implementation Order

1. Config model changes (models.py)
2. SQLitePersistStore + tests
3. SQLiteDurability + tests
4. SQLiteVecStore + tests
5. Factory wiring (__init__.py files)
6. Resolver updates
7. Default config updates
8. pyproject.toml dependency
9. Run verification

## File Structure

```
src/soothe/
├── backends/
│   ├── persistence/
│   │   ├── __init__.py          # MODIFIED
│   │   └── sqlite_store.py      # NEW
│   ├── durability/
│   │   ├── __init__.py          # MODIFIED
│   │   └── sqlite.py            # NEW
│   └── vector_store/
│       ├── __init__.py          # MODIFIED
│       └── sqlite_vec.py        # NEW
├── config/
│   └── models.py                # MODIFIED
├── core/resolver/
│   ├── __init__.py              # MODIFIED
│   └── _resolver_infra.py       # MODIFIED
├── protocols/
│   └── vector_store.py          # READ ONLY (no changes)
└── utils/
    └── paths.py                 # READ (for SOOTHE_HOME resolution)

tests/unit/
├── test_sqlite_store.py         # NEW
├── test_sqlite_durability.py    # NEW
└── test_sqlite_vec.py           # NEW

pyproject.toml                   # MODIFIED (add sqlite-vec dep)
```

## Implementation Details

### 1. Config Model Changes (models.py)

**PersistenceConfig**: Add `"sqlite"` to `default_backend` Literal. Add `sqlite_path: str | None = None`.

**DurabilityProtocolConfig**: Add `"sqlite"` to `backend` Literal. Add `"sqlite"` to `checkpointer` Literal.

**VectorStoreProviderConfig**: Add `"sqlite_vec"` to `provider_type` Literal. Add `sqlite_vec_path: str | None = None`.

Change all three defaults from postgresql/in_memory to sqlite/sqlite_vec.

### 2. SQLitePersistStore (sqlite_store.py)

```python
class SQLitePersistStore:
    """SQLite-backed key-value store implementing PersistStore protocol."""

    def __init__(self, db_path: str | None = None, namespace: str = "default") -> None:
        # Resolve db_path to $SOOTHE_HOME/soothe.db if None
        # Open connection with check_same_thread=False
        # Enable WAL mode
        # Create table if not exists

    def save(self, key: str, data: Any) -> None:
        # INSERT OR REPLACE INTO soothe_kv (namespace, key, data, updated_at)

    def load(self, key: str) -> Any | None:
        # SELECT data FROM soothe_kv WHERE namespace=? AND key=?
        # Return json.loads(result) or None

    def delete(self, key: str) -> None:
        # DELETE FROM soothe_kv WHERE namespace=? AND key=?

    def close(self) -> None:
        # Commit and close connection

    def list_keys(self, namespace: str | None = None) -> list[str]:
        # Optional: list keys for namespace
```

### 3. SQLiteDurability (sqlite.py)

```python
class SQLiteDurability:
    """DurabilityProtocol implementation using SQLite backend."""

    def __init__(self, persist_store: PersistStore | None = None,
                 db_path: str | None = None) -> None:
        if persist_store is None:
            persist_store = SQLitePersistStore(db_path, namespace="durability")
        self._impl = BasePersistStoreDurability(persist_store)
```

### 4. SQLiteVecStore (sqlite_vec.py)

```python
class SQLiteVecStore:
    """SQLite vector store using sqlite-vec extension."""

    def __init__(self, db_path: str | None = None,
                 collection: str = "default",
                 vector_size: int = 1536) -> None:
        # Load sqlite-vec extension
        # Store params, lazy init on first use

    async def create_collection(self, vector_size: int, distance: str = "cosine") -> None:
        # CREATE VIRTUAL TABLE vec_{collection} USING vec0(...)

    async def insert(self, vectors, payloads, ids) -> None:
        # INSERT INTO vec_{collection} (id, embedding, payload)

    async def search(self, query, vector, limit, filters) -> list[VectorRecord]:
        # SELECT id, distance, payload FROM vec_{collection}
        # WHERE embedding MATCH ? ORDER BY distance LIMIT ?

    # ... implement remaining protocol methods
```

### 5. Factory Wiring

**persistence/__init__.py**:
```python
elif backend == "sqlite":
    from soothe.backends.persistence.sqlite_store import SQLitePersistStore
    return SQLitePersistStore(persist_dir or default_path, namespace=namespace)
```

**vector_store/__init__.py**:
```python
elif provider in ("sqlite_vec",):
    from soothe.backends.vector_store.sqlite_vec import SQLiteVecStore
    return SQLiteVecStore(db_path, collection, config)
```

**durability/__init__.py**:
```python
from soothe.backends.durability.sqlite import SQLiteDurability
```

### 6. Resolver Updates

**_resolver_infra.py**: Add `"sqlite"` case in `resolve_durability()` that creates `SQLitePersistStore` and wraps in `SQLiteDurability`.

**__init__.py**: Handle `"vector-sqlite"` in `resolve_context()` to create `SQLiteVecStore` and pass to `VectorContext`.

## Testing Strategy

### Unit Tests
- SQLitePersistStore: CRUD operations, namespace isolation, WAL mode, close behavior
- SQLiteDurability: thread lifecycle via base class, composition pattern
- SQLiteVecStore: create/insert/search/delete, vector size validation, fallback

### Integration
- Run existing tests with SQLite config to verify resolver chain
- `soothe checkhealth` with default config validates SQLite backends

## Verification

- [ ] All new unit tests pass
- [ ] `./scripts/verify_finally.sh` passes (format + lint + unit tests)
- [ ] Existing tests continue passing (backward compat)
- [ ] `soothe checkhealth` validates SQLite configuration

## Related Documents

- [RFC-602](../specs/RFC-602-sqlite-backend.md) -- SQLite Backend Specification
- [RFC-001](../specs/RFC-001-core-modules-architecture.md) -- Core Modules Architecture
