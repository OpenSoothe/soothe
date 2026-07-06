# VectorStoreProtocol & AsyncPersistStore

**RFCs**: RFC-000 Module 8 (VectorStore), RFC-300 (PersistStore)
**Locations**:
- `packages/soothe-sdk/src/soothe_sdk/protocols/vector_store.py`
- `packages/soothe-sdk/src/soothe_sdk/protocols/persistence.py`
**Re-exported from**: `packages/soothe/src/soothe/protocols/`
**Status**: Implemented

## What These Protocols Are

These two protocols form Soothe's **persistence layer**:

1. **`VectorStoreProtocol`** — async vector database abstraction for semantic search (store embeddings, retrieve by similarity).
2. **`AsyncPersistStore`** — async key-value persistence for structured data (save/load/delete by key, with namespaces).

Both are defined in the SDK package (`soothe_sdk`) for reusability and implemented by multiple backends in the main `soothe` package. Both are fully async — no synchronous variants exist.

## VectorStoreProtocol

### Role

VectorStoreProtocol abstracts vector databases. It stores embedding vectors with metadata payloads and retrieves them by similarity. This is the foundation for semantic search: "find items similar to this concept" rather than "find items containing this keyword."

### Key Operations

- **`create_collection(vector_size, distance="cosine")`** — create or ensure a collection exists. Distance metrics: `cosine`, `l2`, `ip` (inner product). The vector size must match the embedding model's output dimension (e.g., 1536 for OpenAI embeddings).
- **`insert(vectors, payloads?, ids?)`** — insert vectors with optional metadata payloads and IDs. Payloads and IDs must match the vector list length; IDs are auto-generated if omitted.
- **`search(query, vector, limit=5, filters?)`** — find nearest neighbors by similarity. Takes both the original text query (for hybrid search implementations) and the embedding vector. Returns `VectorRecord`s ordered by descending similarity score.
- **`delete(record_id)` / `update(record_id, vector?, payload?)` / `get(record_id)`** — standard CRUD for individual records.

### Design Principle: Connection Lifecycle Internal

The protocol contract states: *"Implementations must handle connection lifecycle internally (lazy connect, connection pooling, etc.)."* Callers never open or close connections. This simplifies usage and lets each backend optimize its own connection strategy — PGVectorStore pools PostgreSQL connections; SQLiteVecStore uses aiosqlite's async wrapper; WeaviateVectorStore manages HTTP connections.

### VectorRecord

Search results are `VectorRecord` instances carrying `id`, `score` (similarity score, `None` for non-search results), and `payload` (arbitrary metadata stored alongside the vector). The payload is where domain data lives — text content, source thread, memory type, etc.

## AsyncPersistStore

### Role

AsyncPersistStore is the async key-value persistence interface — the simplest possible storage abstraction. It's used by higher-level protocols (Durability, Context) to persist their structured data without depending on a specific database.

### Key Operations

- **`save(key, data)`** — persist JSON-serializable data under a key.
- **`load(key) → data | None`** — retrieve data by key; `None` if not found.
- **`delete(key)`** — remove data by key.
- **`list_keys(namespace?) → list[str]`** — list keys, optionally filtered by namespace.
- **`close()`** — release resources (connections, file handles).

### Namespace Convention

Namespaces organize keys by purpose: `context:thread_abc123`, `thread:def456`. This is convention, not enforcement — backends implement namespaces via key prefixes or separate tables, but the protocol treats them as opaque strings. The default namespace is used when `namespace=None`.

## Multi-Database Architecture (RFC-802)

PostgreSQL deployments use **dedicated databases** per concern:

| Database | Purpose | Protocol |
|----------|---------|----------|
| `soothe_metadata` | Thread lifecycle state | DurabilityProtocol |
| `soothe_context` | Context ledger (future) | ContextProtocol |
| `soothe_vectors` | Vector storage | VectorStoreProtocol |
| `soothe_checkpoints` | LangGraph checkpoints | (LangGraph) |

This separation provides:
- **Isolation** — metadata vs vectors vs checkpoints don't contend for the same tables
- **Independent scaling** — vector database can scale separately from metadata
- **Separate backup strategies** — checkpoints can be backed up more frequently
- **Clear data boundaries** — each database has a single owner

## Backend Implementations

### VectorStore Backends

| Backend | Location | Use Case |
|---------|----------|----------|
| `PGVectorStore` | `backends/vector_store/pgvector.py` | Production — PostgreSQL with pgvector extension |
| `SQLiteVecStore` | `backends/vector_store/sqlite_vec.py` | Development — zero-config, single-file |
| `WeaviateVectorStore` | `backends/vector_store/weaviate.py` | Cloud — multi-tenancy, hybrid search |

### PersistStore Backends

| Backend | Location | Use Case |
|---------|----------|----------|
| `SQLitePersistStore` | `backends/persistence/sqlite_store.py` | Development — single-file, zero dependencies |
| `PostgreSQLPersistStore` | `backends/persistence/postgres_store.py` | Production — connection pooling, multi-database |

Backends are created via factory functions: `create_persist_store(backend=..., ...)` and `resolve_vector_store(config)`. The backend is selected by configuration, not code — switching from SQLite to PostgreSQL requires only a config change.

## Integration Points

### VectorStore ↔ Memory

Memory backends (currently MemU) use vector search for semantic recall. When `MemoryProtocol.recall(query)` is called, the backend embeds the query and searches the vector store for similar items. The protocol boundary means memory callers never touch vectors directly — they call `recall()`, the backend handles embeddings and search internally.

### PersistStore ↔ Durability

Durability backends use PersistStore for thread metadata storage:

```
create_thread() → persist_store.save(f"thread:{thread_id}", thread_info.model_dump())
get_thread()     → persist_store.load(f"thread:{thread_id}") → ThreadInfo.model_validate(data)
```

The key convention (`thread:<id>`) provides namespacing without explicit namespace parameters.

### PersistStore ↔ Context (Future)

When ContextProtocol is implemented, its ledger will persist via PersistStore:

```
persist()  → persist_store.save(f"context:{thread_id}", ledger.model_dump())
restore()  → persist_store.load(f"context:{thread_id}")
```

## Design Rationale

### Why Async-First?

Both protocols are fully async because Soothe's runtime is async. Multiple threads access the same stores concurrently; connection pooling and non-blocking I/O are essential for throughput. Synchronous variants would force callers into thread pools, defeating the async architecture.

### Why Backend Abstraction?

Swappable implementations let deployments match their infrastructure:
- **Development**: SQLite — zero config, single file, no server
- **Production**: PostgreSQL — connection pooling, multi-database, proven reliability
- **Cloud**: Weaviate — managed service, multi-tenancy, hybrid search

Switching backends requires only a configuration change — zero code modifications in consumers.

### Why Multi-Database Architecture?

A single database for everything causes contention: vector inserts lock tables that checkpoint reads need. Dedicated databases (RFC-802) isolate concerns, enable independent scaling, and provide clear ownership boundaries. Each database can be backed up, scaled, and migrated independently.

## Gotchas

- **Vector size must match embedding model** — `create_collection(vector_size=1536)` must match your embedding model's output. Mismatched sizes cause insert failures.
- **`search` takes both query text and vector** — the text query enables hybrid search implementations (keyword + vector). If your backend is pure vector, the text is ignored, but you must still pass it for protocol compliance.
- **PersistStore `close()` is important** — forgetting to close leaves connections open. In long-running daemons, this causes connection pool exhaustion.
- **Namespaces are convention, not enforcement** — `list_keys(namespace="context")` filters by prefix, but `save("thread:abc", ...)` works in any namespace. Don't rely on the protocol to enforce namespace isolation.
- **MemU doesn't use PersistStore** — the current memory backend owns its storage internally, independent of the multi-database architecture. Don't expect memory data in `soothe_metadata` or `soothe_context`.

## Configuration

```yaml
persistence:
  vector_store_backend: pgvector  # or sqlite_vec, weaviate
  postgres_base_dsn: postgresql://user:pass@host:port
  postgres_databases:
    metadata: soothe_metadata
    vectors: soothe_vectors
    checkpoints: soothe_checkpoints
  # SQLite alternatives:
  # vector_sqlite_path: ~/.soothe/vectors.db
  # metadata_sqlite_path: ~/.soothe/metadata.db
```

Resolved via `resolve_vector_store(config)` and `resolve_persist_store(config, namespace=...)`.

## Specification Reference

- **RFC-000**: System Conceptual Design (Module 8: VectorStore)
- **RFC-300**: Context and Memory Architecture Design (PersistStore)
- **RFC-802**: Persistence Architecture Refactor (multi-database)
- **RFC-801**: SQLite Backend

## Related Documentation

- [Memory Protocol](memory.md) — uses VectorStore for semantic recall
- [Durability Protocol](durability.md) — uses PersistStore for thread storage
- [Context Protocol](context.md) — future PersistStore consumer
