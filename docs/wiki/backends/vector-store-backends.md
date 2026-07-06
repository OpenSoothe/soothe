# Vector Store Backends

Semantic search via `VectorStoreProtocol`. Vector store backends store embedding vectors and perform similarity search, enabling meaning-based retrieval for memory, context, and knowledge systems. They are the engine behind Soothe's "find by meaning, not keywords" capabilities.

---

## What Vector Store Backends Do

Vector store backends manage collections of embedding vectors with associated metadata payloads. The core operations:

- **`create_collection()`** — Initialize a vector table with a given dimension and distance metric.
- **`insert()`** — Add vectors with optional payloads (metadata dicts) and IDs.
- **`search()`** — Find nearest neighbors to a query vector, returning ranked `VectorRecord` results with similarity scores.
- **`get/update/delete`** — CRUD operations on individual records by ID.
- **`list_records()`** — List records with optional metadata filters.
- **`reset()/delete_collection()`** — Clear data.

**Critical design choice**: All backends use **self-provided vectors** — Soothe generates embeddings externally (via its configured embedding model) and passes raw vectors to the store. No backend runs its own vectorizer. This ensures consistent embedding dimensions across backends.

---

## Backend Comparison

| Feature | PGVectorStore | SQLiteVecStore | WeaviateVectorStore |
|---------|---------------|---------------|---------------------|
| Engine | PostgreSQL + pgvector | sqlite-vec extension | Weaviate v4 (gRPC) |
| Index type | HNSW / IVFFlat / none | HNSW (built-in) | HNSW (built-in) |
| Connection pooling | ✅ (psycopg_pool, default 5) | ✅ (reader pool, default 8) | ✅ (via client) |
| Metadata filtering | ✅ (SQL WHERE) | ⚠️ Limited | ✅ (GraphQL filters) |
| Concurrent writes | ✅ | ❌ (single writer, WAL) | ✅ |
| Cloud-ready | ✅ | ❌ (local file) | ✅ (Weaviate Cloud) |
| External dependencies | PostgreSQL, pgvector, psycopg_pool | sqlite-vec (optional, has fallback) | weaviate-client, Weaviate server |
| Setup complexity | Medium | Low | Medium-High |
| Scalability | High | Limited | High |
| Fallback behavior | N/A | Python-side similarity if extension missing | N/A |

---

## Available Backends

### PGVectorStore

Production-grade vector storage using PostgreSQL with the pgvector extension.

**Key characteristics**:
- **Index choice**: Supports HNSW (fast approximate search, higher recall, moderate build time), IVFFlat (faster build, good for large datasets), or no index (exact search, for small datasets <1000 vectors).
- **Connection pooling** via `psycopg_pool.AsyncConnectionPool` (default 5 connections, min 1).
- **Distance metrics**: cosine (default), l2 (Euclidean), ip (inner product) — mapped to pgvector operators.
- **Metadata filtering** via SQL WHERE clauses on JSONB payload columns.
- **Native PostgreSQL integration** — shares infrastructure with durability and persistence backends.

**When to choose**: Production deployments with existing PostgreSQL infrastructure, scenarios requiring scalable concurrent access, or when you want vector storage co-located with other Soothe data.

**Minimal config**:
```yaml
vector_store:
  enabled: true
  provider: pgvector
  dsn: postgresql://localhost/soothe
  collection: soothe_vectors
  vector_size: 1536
  index_type: hnsw
```

Source: `packages/soothe/src/soothe/backends/vector_store/pgvector.py`

---

### SQLiteVecStore

Embedded vector storage using the sqlite-vec extension — no external database required.

**Key characteristics**:
- **Embedded**: Vectors stored in a local SQLite database file (default `$SOOTHE_HOME/vector.db`). Zero external dependencies.
- **Graceful fallback**: If the sqlite-vec extension (virtual tables) is unavailable, falls back to Python-side similarity computation (`_cosine_similarity`, `_l2_distance`, `_ip_similarity`). This is slower but functional.
- **WAL mode + reader pool**: Concurrent reads via a reader pool (default 8 connections), single serialized writer via `asyncio.Lock`. Supports multiple concurrent loops.
- **Binary vector packing**: Vectors are packed into F32 binary format (`struct.pack`) for efficient sqlite-vec storage.
- **Distance metrics**: cosine, l2, ip — mapped to sqlite-vec distance functions.

**When to choose**: Local development, embedded deployments, single-process production, or any scenario avoiding external dependencies. The fallback ensures it works even without the extension installed.

**Minimal config**:
```yaml
vector_store:
  enabled: true
  provider: sqlite_vec
  db_path: ~/.soothe/vector_store/vector.db
  collection: soothe_vectors
  vector_size: 1536
```

Source: `packages/soothe/src/soothe/backends/vector_store/sqlite_vec.py`

---

### WeaviateVectorStore

Cloud-native vector storage using Weaviate v4's async client with gRPC.

**Key characteristics**:
- **Self-provided vectors**: Uses `skip` vectorizer mode — Weaviate doesn't generate embeddings; Soothe provides them. This ensures consistent embedding dimensions.
- **gRPC for search**: Uses gRPC (default port 50051) for fast query/response, REST for management operations.
- **Weaviate Cloud support**: API key authentication for Weaviate Cloud deployments; local mode for self-hosted instances.
- **Schema management**: Automatic schema inference and collection creation.
- **Timeout configuration**: Init 30s, query 30s, insert 120s (configurable via `AdditionalConfig`).

**When to choose**: Cloud-native deployments, managed vector search, multi-modal data, or when you need Weaviate's GraphQL querying and module ecosystem (text2vec, img2vec, etc.).

**Minimal config**:
```yaml
vector_store:
  enabled: true
  provider: weaviate
  url: http://localhost:8080
  grpc_port: 50051
  collection: SootheVectors
```

Source: `packages/soothe/src/soothe/backends/vector_store/weaviate.py`

---

## Index Type Selection (PGVectorStore)

| Index Type | Build Speed | Search Speed | Recall | Best For |
|------------|-------------|--------------|--------|----------|
| **HNSW** | Moderate (O(n log n)) | Fast | High | Production, accuracy-critical |
| **IVFFlat** | Fast (O(n)) | Moderate | Good | Large datasets, speed-critical |
| **None** | N/A | Slow | Perfect | Small datasets (<1000), exact search |

**Recommendation**: Use HNSW for most production workloads — it offers the best recall-to-speed trade-off. Switch to IVFFlat only if build time becomes a bottleneck on very large datasets. Use `none` only for testing or tiny collections.

---

## Performance Characteristics

| Operation | PGVector | SQLiteVec | Weaviate |
|-----------|----------|-----------|----------|
| `create_collection()` | ~50-100ms | ~5-10ms | ~100-200ms |
| `insert()` | ~20-50ms | ~10-20ms | ~50-100ms |
| `search()` | ~50-100ms | ~20-50ms | ~100-200ms |
| `get()` | ~10-30ms | ~5-10ms | ~50-100ms |
| `delete()` | ~20-50ms | ~10-20ms | ~50-100ms |
| `list_records()` | ~50-200ms | ~50-100ms | ~100-300ms |

**SQLiteVec is fastest for local operations** (no network). PGVector adds network overhead but scales to concurrent access. Weaviate has the highest latency due to gRPC/REST overhead but offers cloud scalability.

**Search latency scales with collection size**: HNSW search is approximately O(log n); exact search (no index) is O(n). Monitor search latency as collections grow.

---

## Production Gotchas

1. **Vector dimension is fixed per collection**: The `vector_size` (default 1536 for OpenAI embeddings) is set at collection creation and cannot change. Switching embedding models requires creating a new collection and re-inserting all vectors.

2. **SQLiteVec fallback is slow**: Without the sqlite-vec extension, Python-side similarity computation iterates all vectors — O(n) per search. Install the extension for production use. The fallback exists for compatibility, not performance.

3. **SQLiteVec single-writer contention**: Like other SQLite backends, writes are serialized via `asyncio.Lock`. Under heavy concurrent insertion, throughput is limited. PGVector and Weaviate handle concurrent writes via pooling.

4. **Weaviate timeout tuning**: Default timeouts (init 30s, query 30s, insert 120s) may need adjustment for large batch inserts or slow networks. Increase `insert` timeout for bulk loading.

5. **PGVector index build time**: Creating an HNSW index on a large existing table can take minutes to hours. Build the index *after* bulk insertion, not before, to avoid re-indexing overhead during loads.

6. **Metadata filter limitations**: SQLiteVec has limited metadata filtering compared to PGVector (SQL WHERE) and Weaviate (GraphQL). If complex filtering is critical, prefer PGVector or Weaviate.

7. **Collection naming**: PGVector uses the collection name as a table name; Weaviate uses it as a class name; SQLiteVec uses it as a table prefix. Ensure names are valid identifiers across your chosen backend.

---

## Integration with Memory

Memory backends (MemUMemory) use vector stores indirectly — MemU maintains its own embedding store for semantic recall. However, the `VectorStoreProtocol` is available for direct semantic search use cases, and the protocol abstraction means you can swap engines without changing application code.

---

## Related Documentation

- **[Backends Overview](index.md)** — Backend layer introduction
- **[Memory Backends](memory-backends.md)** — Memory semantic search integration
- **[Context Protocol](../protocols/index.md)** — Context semantic search
- **[RFC-001](../../specs/RFC-001-core-modules-architecture.md)** — Vector store protocol spec
