# Vector Store Backends

VectorStoreProtocol implementations for semantic search and embeddings.

---

## Overview

Vector store backends implement `VectorStoreProtocol` for storing and searching vector embeddings. They enable semantic search capabilities for memory, context, and knowledge retrieval.

---

## VectorStoreProtocol Interface

### Core Operations

```python
class VectorStoreProtocol(Protocol):
    """Async protocol for vector database operations."""

    async def create_collection(self, vector_size: int, distance: str = "cosine") -> None: ...
    async def insert(self, vectors: list[list[float]], payloads: list[dict] | None = None, ids: list[str] | None = None) -> None: ...
    async def search(self, query: str, vector: list[float], limit: int = 5, filters: dict | None = None) -> list[VectorRecord]: ...
    async def delete(self, record_id: str) -> None: ...
    async def update(self, record_id: str, vector: list[float] | None = None, payload: dict | None = None) -> None: ...
    async def get(self, record_id: str) -> VectorRecord | None: ...
    async def list_records(self, filters: dict | None = None, limit: int | None = None) -> list[VectorRecord]: ...
    async def delete_collection(self) -> None: ...
    async def reset(self) -> None: ...
    async def close(self) -> None: ...
```

---

## Vector Record Model

### VectorRecord

Vector record data structure:

```python
class VectorRecord(BaseModel):
    """A stored vector record with metadata."""

    id: str                      # Unique identifier
    score: float | None          # Similarity score from search (None for non-search results)
    payload: dict[str, Any]      # Arbitrary metadata stored alongside the vector
```

---

## Available Backends

### PGVectorStore

Production-grade vector storage using PostgreSQL pgvector extension.

#### Features

- **Async Operations**: Connection pooling with async support
- **Index Types**: HNSW and IVFFlat index support
- **Production-grade**: Scalable, concurrent access
- **Native PostgreSQL**: Integrated with existing PostgreSQL infrastructure
- **Metadata Filtering**: Filter search results by metadata
- **Connection Pooling**: Efficient connection management

#### Architecture

```
PGVectorStore Architecture
├─ PostgreSQL Database
│  ├─ pgvector extension
│  ├─ Vector table
│  ├─ HNSW/IVFFlat index
│  ├─ Async connection pool (psycopg_pool)
│  └─ Transaction support
│
├─ Index Types
│  ├─ HNSW (Hierarchical Navigable Small World)
│  │  ├─ Fast approximate search
│  │  ├─ Better recall than IVFFlat
│  │  └─ Build time: O(n log n)
│  │
│  └─ IVFFlat (Inverted File with Flat compression)
│  │  ├─ Faster build than HNSW
│  │  ├─ Good for large datasets
│  │  └─ Build time: O(n)
│  │
│  └─ None (no index)
│     ├─ Exact search (slow)
│     └─ Use for small datasets
│
└─ Configuration
   ├─ Collection name
   ├─ Vector dimension
   ├─ Index type
   ├─ Pool size
   └─ DSN
```

#### Index Types Comparison

| Index Type | Build Speed | Search Speed | Recall | Best Use Case |
|------------|-------------|--------------|--------|---------------|
| **HNSW** | Moderate | Fast | High | Production, accuracy-critical |
| **IVFFlat** | Fast | Moderate | Good | Large datasets, speed-critical |
| **None** | N/A | Slow | Perfect | Small datasets (<1000 vectors), exact search |

#### Implementation

```python
class PGVectorStore(VectorStoreProtocol):
    """VectorStoreProtocol implementation using PostgreSQL with pgvector."""

    def __init__(
        self,
        collection: str = "soothe_vectors",
        dsn: str = "postgresql://localhost/soothe",
        pool_size: int = 5,
        index_type: str = "hnsw",
        vector_size: int = 1536,
    ) -> None:
        """Initialize PGVectorStore.

        Args:
            collection: Table name for storing vectors.
            dsn: PostgreSQL connection string.
            pool_size: Connection pool size.
            index_type: Index type (hnsw, ivfflat, or none).
            vector_size: Dimension of vectors (default: 1536).
        """
        ...

    async def create_collection(
        self, vector_size: int | None = None, distance: str = "cosine"
    ) -> None:
        """Create or ensure a collection exists."""
        ...

    async def insert(
        self,
        vectors: list[list[float]],
        payloads: list[dict] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """Insert vectors with optional payloads and IDs."""
        ...

    async def search(
        self,
        query: str,
        vector: list[float],
        limit: int = 5,
        filters: dict | None = None,
    ) -> list[VectorRecord]:
        """Search for nearest neighbours."""
        ...

    async def delete(self, record_id: str) -> None:
        """Delete a record by ID."""
        ...

    async def update(
        self,
        record_id: str,
        vector: list[float] | None = None,
        payload: dict | None = None,
    ) -> None:
        """Update a record's vector and/or payload."""
        ...

    async def get(self, record_id: str) -> VectorRecord | None:
        """Retrieve a single record by ID."""
        ...

    async def list_records(
        self,
        filters: dict | None = None,
        limit: int | None = None,
    ) -> list[VectorRecord]:
        """List records matching optional filters."""
        ...

    async def delete_collection(self) -> None:
        """Delete the entire collection and its data."""
        ...

    async def reset(self) -> None:
        """Clear all records from the collection."""
        ...

    async def close(self) -> None:
        """Close connections and release resources."""
        ...
```

#### Configuration

```yaml
vector_store:
  enabled: true
  provider: pgvector        # PGVectorStore backend
  
  # PostgreSQL connection
  dsn: postgresql://localhost/soothe
  pool_size: 5
  
  # Collection settings
  collection: soothe_vectors
  vector_size: 1536         # OpenAI embedding dimension
  
  # Index settings
  index_type: hnsw          # HNSW index (recommended)
```

#### Usage Example

```python
from soothe.backends.vector_store import PGVectorStore
from soothe.protocols.vector_store import VectorRecord

# Initialize store
store = PGVectorStore(
    dsn="postgresql://localhost/soothe",
    collection="memories",
    vector_size=1536,
)

# Create collection
await store.create_collection(vector_size=1536, distance="cosine")

# Insert vectors
await store.insert(
    vectors=[[0.1, 0.2, ...], [0.3, 0.4, ...]],
    payloads=[{"content": "test memory"}, {"content": "another"}],
    ids=["mem_abc123", "mem_def456"],
)

# Search vectors
results = await store.search(
    query="test memory",
    vector=[0.1, 0.2, ...],
    limit=10,
    filters={"tags": ["test"]},
)

# Get vector
record = await store.get("mem_abc123")

# Update vector
await store.update("mem_abc123", payload={"tags": ["updated"]})

# List records
records = await store.list_records(limit=100)

# Delete vector
await store.delete("mem_abc123")

# Close connections
await store.close()
```

---

### SQLiteVecStore

Embedded vector storage using sqlite-vec extension.

#### Features

- **Embedded**: No external database required
- **Async Operations**: Async SQLite support
- **HNSW Index**: Fast approximate search
- **Local Storage**: File-based persistence
- **No External Dependencies**: Self-contained

#### Architecture

```
SQLiteVecStore Architecture
├─ SQLite Database
│  ├─ sqlite-vec extension
│  ├─ Vector table
│  ├─ HNSW index (built-in)
│  ├─ Async connection (aiosqlite)
│  └─ WAL mode
│
├─ Index Management
│  ├─ HNSW index (automatic)
│  ├─ Index configuration
│  └─ Reindex support
│
└─ Configuration
   ├─ Database file
   ├─ Collection name
   ├─ Vector dimension
   └─ Index parameters
```

#### Implementation

```python
class SQLiteVecStore(VectorStoreProtocol):
    """VectorStoreProtocol implementation using sqlite-vec.

    Uses the sqlite-vec extension for vector similarity search.
    Falls back to Python-side similarity computation if sqlite-vec
    virtual tables are unavailable.

    Args:
        collection: Collection name (becomes table name prefix).
        db_path: Path to SQLite database. Defaults to $SOOTHE_HOME/vector.db.
        vector_size: Dimension of vectors (default: 1536).
        distance: Distance metric (cosine, l2, ip).
        reader_pool_size: Number of reader connections for concurrent reads.
    """

    def __init__(
        self,
        collection: str = "soothe_vectors",
        db_path: str | None = None,
        vector_size: int = 1536,
        distance: str = "cosine",
        reader_pool_size: int = 8,
    ) -> None:
        """Initialize SQLiteVecStore."""
        ...

    async def create_collection(
        self, vector_size: int | None = None, distance: str = "cosine"
    ) -> None:
        """Create or ensure a collection exists."""
        ...

    async def insert(
        self,
        vectors: list[list[float]],
        payloads: list[dict] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """Insert vectors with optional payloads and IDs."""
        ...

    async def search(
        self,
        query: str,
        vector: list[float],
        limit: int = 5,
        filters: dict | None = None,
    ) -> list[VectorRecord]:
        """Search for nearest neighbours."""
        ...

    async def delete(self, record_id: str) -> None: ...
    async def update(self, record_id: str, vector: list[float] | None = None, payload: dict | None = None) -> None: ...
    async def get(self, record_id: str) -> VectorRecord | None: ...
    async def list_records(self, filters: dict | None = None, limit: int | None = None) -> list[VectorRecord]: ...
    async def delete_collection(self) -> None: ...
    async def reset(self) -> None: ...
    async def close(self) -> None: ...
```

#### Configuration

```yaml
vector_store:
  enabled: true
  provider: sqlite_vec      # SQLiteVecStore backend

  # Storage
  db_path: ~/.soothe/vector_store/vector.db

  # Collection settings
  collection: soothe_vectors
  vector_size: 1536         # OpenAI embedding dimension

  # Index parameters
  distance: cosine          # Distance metric (cosine, l2, ip)
  reader_pool_size: 8       # Concurrent reader connections
```

#### Usage Example

```python
from soothe.backends.vector_store import SQLiteVecStore

# Initialize store
store = SQLiteVecStore(
    collection="memories",
    db_path="~/.soothe/vector_store/vector.db",
    vector_size=1536,
)

# Create collection
await store.create_collection(vector_size=1536)

# Insert vectors
await store.insert(
    vectors=[[0.1, 0.2, ...]],
    payloads=[{"content": "test memory"}],
    ids=["mem_abc123"],
)

# Search
results = await store.search(query="test", vector=[0.1, 0.2, ...], limit=10)

# Get, update, delete, list
record = await store.get("mem_abc123")
await store.update("mem_abc123", payload={"tags": ["updated"]})
await store.delete("mem_abc123")
records = await store.list_records(limit=100)
await store.close()
```

---

### WeaviateVectorStore

Cloud-native vector storage using Weaviate.

#### Features

- **Cloud-native**: Designed for cloud deployment
- **GraphQL API**: Rich querying capabilities
- **Multi-modal**: Support for various data types
- **Semantic Search**: Advanced semantic search features
- **Schema Management**: Automatic schema inference
- **Modules**: Extensible with modules (text2vec, img2vec, etc.)

#### Architecture

```
WeaviateVectorStore Architecture
├─ Weaviate Server
│  ├─ GraphQL API
│  ├─ REST API
│  ├─ HNSW index (built-in)
│  ├─ Schema management
│  └─ Module system
│
├─ Client Library
│  ├─ weaviate-client
│  ├─ Async support
│  ├─ GraphQL queries
│  ├─ Batch operations
│  └─ Schema utilities
│
└─ Configuration
   ├─ Weaviate URL
   ├─ Collection class
   ├─ Vectorizer module
   └─ Authentication
```

#### Implementation

```python
class WeaviateVectorStore(VectorStoreProtocol):
    """VectorStoreProtocol implementation using Weaviate v4 async client.

    Uses self-provided vectors (skip vectorizer) so embedding is
    handled externally by Soothe's embedding model.

    Args:
        collection: Weaviate collection (class) name.
        url: Weaviate server URL.
        api_key: Weaviate API key (for Weaviate Cloud).
        grpc_port: gRPC port for Weaviate.
    """

    def __init__(
        self,
        collection: str = "SootheVectors",
        url: str = "http://localhost:8080",
        api_key: str | None = None,
        grpc_port: int = 50051,
    ) -> None:
        """Initialize WeaviateVectorStore."""
        ...

    async def create_collection(
        self, vector_size: int | None = None, distance: str = "cosine"
    ) -> None: ...
    async def insert(
        self, vectors: list[list[float]], payloads: list[dict] | None = None, ids: list[str] | None = None
    ) -> None: ...
    async def search(
        self, query: str, vector: list[float], limit: int = 5, filters: dict | None = None
    ) -> list[VectorRecord]: ...
    async def delete(self, record_id: str) -> None: ...
    async def update(self, record_id: str, vector: list[float] | None = None, payload: dict | None = None) -> None: ...
    async def get(self, record_id: str) -> VectorRecord | None: ...
    async def list_records(self, filters: dict | None = None, limit: int | None = None) -> list[VectorRecord]: ...
    async def delete_collection(self) -> None: ...
    async def reset(self) -> None: ...
    async def close(self) -> None: ...
```

#### Configuration

```yaml
vector_store:
  enabled: true
  provider: weaviate        # WeaviateVectorStore backend

  # Weaviate connection
  url: http://localhost:8080
  grpc_port: 50051

  # Collection settings
  collection: SootheVectors

  # Authentication (optional)
  api_key: null             # Weaviate API key (for Weaviate Cloud)
```

#### Usage Example

```python
from soothe.backends.vector_store import WeaviateVectorStore

# Initialize store
store = WeaviateVectorStore(
    collection="Memories",
    url="http://localhost:8080",
)

# Create collection
await store.create_collection(vector_size=1536)

# Insert vectors
await store.insert(
    vectors=[[0.1, 0.2, ...]],
    payloads=[{"content": "test memory"}],
    ids=["mem_abc123"],
)

# Search
results = await store.search(query="test", vector=[0.1, 0.2, ...], limit=10)

# Get, update, delete, list
record = await store.get("mem_abc123")
await store.update("mem_abc123", payload={"tags": ["updated"]})
await store.delete("mem_abc123")
records = await store.list_records(limit=100)
await store.close()
```

---

## Performance Characteristics

### PGVectorStore Performance

| Operation | Performance | Notes |
|-----------|-------------|-------|
| `create_collection()` | ~50-100ms | DDL with index creation |
| `insert()` | ~20-50ms | Connection pool overhead |
| `search()` | ~50-100ms | HNSW index, fast approximate search |
| `get()` | ~10-30ms | Network overhead |
| `delete()` | ~20-50ms | Connection pool overhead |
| `list_records()` | ~50-200ms | Filter + network |

### SQLiteVecStore Performance

| Operation | Performance | Notes |
|-----------|-------------|-------|
| `create_collection()` | ~5-10ms | Local DDL |
| `insert()` | ~10-20ms | Local, no network |
| `search()` | ~20-50ms | HNSW index, local |
| `get()` | ~5-10ms | Fast local read |
| `delete()` | ~10-20ms | Local |
| `list_records()` | ~50-100ms | Index scan |

### WeaviateVectorStore Performance

| Operation | Performance | Notes |
|-----------|-------------|-------|
| `create_collection()` | ~100-200ms | Schema creation |
| `insert()` | ~50-100ms | gRPC API overhead |
| `search()` | ~100-200ms | gRPC query overhead |
| `get()` | ~50-100ms | REST API overhead |
| `delete()` | ~50-100ms | REST API overhead |
| `list_records()` | ~100-300ms | GraphQL aggregation |

---

## Comparison Table

### Vector Store Backend Comparison

| Feature | PGVectorStore | SQLiteVecStore | WeaviateVectorStore |
|---------|---------------|---------------|--------------|
| Storage Type | PostgreSQL pgvector | sqlite-vec | Weaviate |
| Index Type | HNSW/IVFFlat | HNSW | HNSW (built-in) |
| Async Operations | ✅ | ✅ | ✅ |
| Connection Pooling | ✅ | ✅ (reader pool) | ✅ (via client) |
| Metadata Filtering | ✅ | ⚠️ (limited) | ✅ |
| Production Use | ✅ | ⚠️ (local) | ✅ (cloud) |
| External Dependencies | PostgreSQL, pgvector, psycopg_pool | sqlite-vec | weaviate-client, Weaviate server |
| Setup Complexity | Medium | Low | Medium-High |
| Scalability | High | Limited | High |
| Cloud-ready | ✅ | ❌ | ✅ |

---

## Error Handling

### Common Errors

```python
try:
    await store.insert(
        vectors=[[0.1, 0.2, ...]],
        payloads=[{"content": "test"}],
        ids=["mem_abc123"],
    )
except VectorStoreBackendError as e:
    logger.error(f"Vector store backend error: {e}")

    # Handle specific errors:
    if "connection_failed" in str(e):
        # Retry or fallback
        pass

    elif "index_error" in str(e):
        # Reindex
        await store.reset()

    elif "dimension_mismatch" in str(e):
        # Check vector dimension
        pass
```

---

## Integration with Memory

### Memory → Vector Store Flow

Memory backends use vector stores for semantic search:

```python
class MemUMemory(MemoryProtocol):
    def __init__(self, config: SootheConfig):
        # Create embedding model
        embedding_model = config.create_embedding_model()
        
        # Use vector store for semantic search
        # (MemU has its own embedding store)
```

---

## Testing

### Unit Testing

```python
import pytest

@pytest.mark.asyncio
async def test_pgvector_store():
    """Test PGVectorStore backend."""
    store = PGVectorStore(
        dsn="postgresql://localhost/test",
        collection="test_vectors"
    )

    # Create collection
    await store.create_collection(vector_size=1536)

    # Test insert
    await store.insert(
        vectors=[[0.1] * 1536],
        payloads=[{"test": "data"}],
        ids=["test_1"],
    )

    # Test search
    results = await store.search(query="test", vector=[0.1] * 1536, limit=10)
    assert len(results) > 0

    # Test get
    result = await store.get("test_1")
    assert result.id == "test_1"

    # Test list
    records = await store.list_records()
    assert len(records) > 0

    # Test delete
    await store.delete("test_1")
    result = await store.get("test_1")
    assert result is None

    await store.close()
```

---

## Configuration Examples

### Basic SQLiteVec Configuration

```yaml
vector_store:
  enabled: true
  provider: sqlite_vec
  db_path: ~/.soothe/vector_store/vector.db
  collection: soothe_vectors
  vector_size: 1536
  distance: cosine
  reader_pool_size: 8
```

### Production PGVector Configuration

```yaml
vector_store:
  enabled: true
  provider: pgvector
  
  # PostgreSQL connection
  dsn: postgresql://user:pass@host:5432/soothe
  pool_size: 10
  
  # Collection settings
  collection: soothe_vectors
  vector_size: 1536
  
  # Index settings
  index_type: hnsw
```

### Cloud Weaviate Configuration

```yaml
vector_store:
  enabled: true
  provider: weaviate

  # Weaviate connection
  url: https://your-weaviate-instance.weaviate.cloud
  grpc_port: 443
  api_key: your-api-key

  # Collection settings
  collection: SootheVectors
```

---

## Related Documentation

- **[Backends Overview](README.md)** - Backend layer introduction
- **[Memory Backends](memory-backends.md)** - Memory semantic search
- **[Context Protocol](../architecture/protocols.md#context)** - Context semantic search
- **[RFC-001](../../specs/RFC-001-core-modules-architecture.md)** - Vector store protocol spec

---

## API Reference

### PGVectorStore Class

```python
class PGVectorStore(VectorStoreProtocol):
    """VectorStoreProtocol implementation using PostgreSQL with pgvector."""

    def __init__(
        self,
        collection: str = "soothe_vectors",
        dsn: str = "postgresql://localhost/soothe",
        pool_size: int = 5,
        index_type: str = "hnsw",
        vector_size: int = 1536,
    ) -> None: ...
```

### SQLiteVecStore Class

```python
class SQLiteVecStore(VectorStoreProtocol):
    """VectorStoreProtocol implementation using sqlite-vec."""

    def __init__(
        self,
        collection: str = "soothe_vectors",
        db_path: str | None = None,
        vector_size: int = 1536,
        distance: str = "cosine",
        reader_pool_size: int = 8,
    ) -> None: ...
```

### WeaviateVectorStore Class

```python
class WeaviateVectorStore(VectorStoreProtocol):
    """VectorStoreProtocol implementation using Weaviate v4 async client."""

    def __init__(
        self,
        collection: str = "SootheVectors",
        url: str = "http://localhost:8080",
        api_key: str | None = None,
        grpc_port: int = 50051,
    ) -> None: ...
```

---

## See Also

- **[VectorStore Protocol](../architecture/protocols.md)** - Protocol definition
- **[Protocol Resolver](../core/resolver.md)** - Backend resolution
- **[Memory Backends](memory-backends.md)** - Memory integration