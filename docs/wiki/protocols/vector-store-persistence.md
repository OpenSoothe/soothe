# VectorStoreProtocol & AsyncPersistStore

**RFCs**: RFC-000 Module 8 (VectorStore), RFC-300 (PersistStore)  
**Locations**:
- `packages/soothe-sdk/src/soothe_sdk/protocols/vector_store.py`
- `packages/soothe-sdk/src/soothe_sdk/protocols/persistence.py`

**Re-exported**:
- `packages/soothe/src/soothe/protocols/vector_store.py`
- `packages/soothe/src/soothe/protocols/persistence.py`

**Status**: Implemented  

## Overview

VectorStoreProtocol and AsyncPersistStore provide the **persistence layer** for Soothe:

1. **VectorStoreProtocol**: Async vector database abstraction for semantic search
2. **AsyncPersistStore**: Async key-value persistence for context and durability

Both protocols are defined in the SDK package for reusability and implemented by multiple backends in the soothe package.

## VectorStoreProtocol

### Purpose

- **Vector storage**: Store embedding vectors with metadata
- **Semantic search**: Retrieve by similarity, not keywords
- **Collection management**: Create collections with configurable distance metrics
- **Async operations**: All methods are async for concurrent access

### Protocol Interface

```python
@runtime_checkable
class VectorStoreProtocol(Protocol):
    """Async protocol for vector database operations.
    
    All methods are async. Implementations must handle connection
    lifecycle internally (lazy connect, connection pooling, etc.).
    """

    async def create_collection(
        self, 
        vector_size: int, 
        distance: str = "cosine"
    ) -> None:
        """Create or ensure a collection exists.
        
        Args:
            vector_size: Dimensionality of vectors in this collection.
            distance: Distance metric ('cosine', 'l2', 'ip').
        """
        ...

    async def insert(
        self,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """Insert vectors with optional payloads and IDs.
        
        Args:
            vectors: List of embedding vectors.
            payloads: Per-vector metadata dicts. Must match length of vectors.
            ids: Per-vector IDs. Auto-generated if not provided.
        """
        ...

    async def search(
        self,
        query: str,
        vector: list[float],
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorRecord]:
        """Search for nearest neighbours.
        
        Args:
            query: The original text query (for hybrid search implementations).
            vector: Query embedding vector.
            limit: Maximum results to return.
            filters: Metadata filter conditions.
            
        Returns:
            Records ordered by descending similarity.
        """
        ...

    async def delete(self, record_id: str) -> None:
        """Delete a record by ID.
        
        Args:
            record_id: The record to delete.
        """
        ...

    async def update(
        self,
        record_id: str,
        vector: list[float] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Update a record's vector and/or payload.
        
        Args:
            record_id: The record to update.
            vector: New embedding vector (None to keep existing).
            payload: New metadata (None to keep existing).
        """
        ...

    async def get(self, record_id: str) -> VectorRecord | None:
        """Retrieve a single record by ID.
        
        Args:
            record_id: The record ID.
            
        Returns:
            VectorRecord if found, None otherwise.
        """
        ...
```

### Data Models

#### VectorRecord

```python
class VectorRecord(BaseModel):
    """A stored vector record with metadata.
    
    Args:
        id: Unique record identifier.
        score: Similarity score from search (None for non-search results).
        payload: Arbitrary metadata stored alongside the vector.
    """

    id: str
    score: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
```

### Backend Implementations

#### PGVectorStore

**Status**: Production implementation  
**Location**: `packages/soothe/src/soothe/backends/vector_store/pgvector.py`  
**Dependencies**: PostgreSQL with pgvector extension (RFC-612 vector database)

**Features**:
- Production-grade vector storage
- Connection pooling
- Cosine/L2/IP distance metrics
- Metadata filtering
- Dedicated vector database (RFC-612)

**Configuration**:
```yaml
persistence:
  vector_store_backend: pgvector
  postgres_base_dsn: postgresql://user:pass@host:port
  postgres_databases:
    vectors: soothe_vectors  # Dedicated vector database
```

#### SQLiteVecStore

**Status**: Lightweight implementation  
**Location**: `packages/soothe/src/soothe/backends/vector_store/sqlite_vec.py`  
**Dependencies**: sqlite-vec extension

**Features**:
- Zero-configuration vector storage
- Single-file database
- Suitable for development and prototyping
- Async operations via aiosqlite

**Configuration**:
```yaml
persistence:
  vector_store_backend: sqlite_vec
  vector_sqlite_path: ~/.soothe/vectors.db
```

#### WeaviateStore

**Status**: Cloud-ready implementation  
**Location**: `packages/soothe/src/soothe/backends/vector_store/weaviate.py`  
**Dependencies**: Weaviate instance (local or cloud)

**Features**:
- Cloud-ready vector storage
- GraphQL-based queries
- Multi-tenancy support
- Semantic search with hybrid capabilities

**Configuration**:
```yaml
persistence:
  vector_store_backend: weaviate
  weaviate_url: http://localhost:8080
  weaviate_api_key: ${WEAVIATE_API_KEY}
```

## AsyncPersistStore

### Purpose

- **Key-value persistence**: Simple save/load/delete operations
- **Namespace support**: Organized storage with namespaces
- **Async operations**: Concurrent safe operations
- **Backend abstraction**: SQLite, PostgreSQL, RocksDB

### Protocol Interface

```python
@runtime_checkable
class AsyncPersistStore(Protocol):
    """Async key-value persistence interface with concurrent operation support.
    
    Implemented by SQLitePersistStore and PostgreSQLPersistStore.
    Provides a storage-agnostic async interface for context, memory,
    and durability backends.
    
    All methods are async to support concurrent operations and
    connection pooling.
    """

    async def save(self, key: str, data: Any) -> None:
        """Persist data under the given key.
        
        Args:
            key: Storage key.
            data: JSON-serialisable data.
        """
        ...

    async def load(self, key: str) -> Any | None:
        """Load data for the given key.
        
        Args:
            key: Storage key.
            
        Returns:
            The stored data, or None if not found.
        """
        ...

    async def delete(self, key: str) -> None:
        """Delete data for the given key.
        
        Args:
            key: Storage key.
        """
        ...

    async def list_keys(self, namespace: str | None = None) -> list[str]:
        """List all keys in the namespace.
        
        Args:
            namespace: Optional namespace to list keys from.
                      If None, uses default namespace.
            
        Returns:
            List of keys in the namespace.
        """
        ...

    async def close(self) -> None:
        """Release any resources held by the store."""
        ...
```

### Backend Implementations

#### SQLitePersistStore

**Status**: Development implementation  
**Location**: `packages/soothe/src/soothe/backends/persistence/sqlite_store.py`  

**Features**:
- Single-file storage
- Namespace support via key prefixes
- Async operations via aiosqlite
- Zero external dependencies

**Usage**:
```python
from soothe.backends.persistence import create_persist_store

store = create_persist_store(
    backend="sqlite",
    db_path="~/.soothe/persistence.db",
    namespace="context"
)

await store.save("thread:abc123", {"entries": [...]})
data = await store.load("thread:abc123")
```

#### PostgreSQLPersistStore

**Status**: Production implementation  
**Location**: `packages/soothe/src/soothe/backends/persistence/postgres_store.py`  

**Features**:
- Production-grade persistence
- Connection pooling
- Namespace support
- Multi-database architecture (RFC-612)

**Usage**:
```python
from soothe.backends.persistence import create_persist_store

dsn = config.resolve_postgres_dsn_for_database("context")
store = create_persist_store(
    backend="postgresql",
    dsn=dsn,
    namespace="context"
)

await store.save("thread:abc123", {"entries": [...]})
```

## Usage Patterns

### VectorStore Usage

```python
from soothe.protocols import VectorStoreProtocol, VectorRecord
from soothe.config import SootheConfig

# Resolve vector store
vector_store: VectorStoreProtocol = resolve_vector_store(config)

# Create collection
await vector_store.create_collection(
    vector_size=1536,  # OpenAI embedding dimension
    distance="cosine"
)

# Insert vectors
vectors = [
    [0.1, 0.2, ...],  # Embedding for "database optimization"
    [0.3, 0.4, ...],  # Embedding for "PostgreSQL tuning"
]
payloads = [
    {"text": "database optimization", "source": "thread_abc"},
    {"text": "PostgreSQL tuning", "source": "thread_def"},
]

await vector_store.insert(vectors, payloads)

# Search by similarity
query_vector = [0.15, 0.25, ...]  # Embedding for "improve database"
results = await vector_store.search(
    query="improve database performance",
    vector=query_vector,
    limit=5
)

for result in results:
    print(f"[score={result.score:.3f}] {result.payload['text']}")
```

### PersistStore Usage

```python
from soothe.backends.persistence import create_persist_store

# Create store
store = create_persist_store(
    backend="postgresql",
    dsn="postgresql://user:pass@host:port/database",
    namespace="context"
)

# Save context data
await store.save(
    "thread:abc123",
    {
        "entries": [
            {"source": "tool", "content": "Found solution"},
            ...
        ]
    }
)

# Load context data
data = await store.load("thread:abc123")
if data:
    entries = data["entries"]
    
# List keys in namespace
keys = await store.list_keys(namespace="context")
# ["thread:abc123", "thread:def456", ...]

# Delete key
await store.delete("thread:abc123")

# Close store (cleanup)
await store.close()
```

## Integration with Other Protocols

### VectorStore ↔ Memory Integration

Memory backends use VectorStore for semantic retrieval:

```python
# Memory recall uses vector search
memories = await vector_store.search(
    query="database optimization",
    vector=query_embedding,
    limit=10,
    filters={"memory_type": "knowledge"}
)
```

### PersistStore ↔ Durability Integration

Durability backends use PersistStore for thread storage:

```python
# Thread persistence via PersistStore
await persist_store.save(
    f"thread:{thread_id}",
    thread_info.model_dump()
)

# Thread retrieval
data = await persist_store.load(f"thread:{thread_id}")
thread_info = ThreadInfo.model_validate(data)
```

### PersistStore ↔ Context Integration

Context backends use PersistStore for ledger persistence:

```python
# Context ledger persistence
await persist_store.save(
    f"context:{thread_id}",
    context_ledger.model_dump()
)

# Context ledger restoration
data = await persist_store.load(f"context:{thread_id}")
if data:
    context_ledger.restore_from_dict(data)
```

## Multi-Database Architecture

### RFC-612 Architecture

PostgreSQL implementations use dedicated databases:

```yaml
postgres_databases:
  metadata: soothe_metadata    # DurabilityProtocol
  context: soothe_context      # ContextProtocol (future)
  vectors: soothe_vectors      # VectorStoreProtocol
  checkpoints: soothe_checkpoints  # LangGraph Checkpointer
```

**Benefits**:
- Isolation of concerns
- Independent scaling
- Separate backup strategies
- Clear data boundaries

## Configuration

### VectorStore Settings

```yaml
# config/config.template.yml
persistence:
  vector_store_backend: pgvector  # or sqlite_vec, weaviate
  
  # PostgreSQL vector storage
  postgres_base_dsn: postgresql://user:pass@host:port
  postgres_databases:
    vectors: soothe_vectors
    
  # SQLite vector storage
  vector_sqlite_path: ~/.soothe/vectors.db
  
  # Weaviate configuration
  weaviate_url: http://localhost:8080
  weaviate_api_key: ${WEAVIATE_API_KEY}
```

### PersistStore Settings

```yaml
persistence:
  # SQLite persistence
  metadata_sqlite_path: ~/.soothe/metadata.db
  context_sqlite_path: ~/.soothe/context.db
  
  # PostgreSQL persistence
  postgres_base_dsn: postgresql://user:pass@host:port
  postgres_databases:
    metadata: soothe_metadata
    context: soothe_context
```

### Resolution

```python
from soothe.core.resolver import (
    resolve_vector_store,
    resolve_persist_store
)

# Resolve protocols
vector_store = resolve_vector_store(config)
persist_store = resolve_persist_store(config, namespace="context")
```

## Testing

### Unit Tests

**Locations**:
- `packages/soothe/tests/unit/backends/vector_store/`
- `packages/soothe/tests/unit/backends/persistence/`

Tests verify:
- Vector insertion and retrieval
- Similarity search accuracy
- Metadata filtering
- Key-value persistence
- Namespace isolation
- Connection lifecycle

### Integration Tests

**Locations**:
- `packages/soothe/tests/integration/backends/persistence/`

Tests verify:
- PostgreSQL connection handling
- Multi-database architecture
- Concurrent operations
- Large-scale vector storage

## Design Rationale

### Why Async-First?

Concurrent operation support:
- Multiple threads accessing same store
- Connection pooling for efficiency
- Non-blocking I/O for performance

### Why Backend Abstraction?

Swappable implementations:
- SQLite for development
- PostgreSQL for production
- Weaviate for cloud deployments
- Zero code changes when switching

### Why Multi-Database Architecture?

Isolation benefits (RFC-612):
- Metadata vs vectors vs checkpoints
- Independent scaling and backup
- Clear ownership boundaries
- Prevents data contamination

## Specification Reference

- **RFC-000**: System Conceptual Design (Module 8)
- **RFC-300**: Context and Memory Architecture Design
- **RFC-612**: Persistence Architecture Refactor
- **RFC-602**: SQLite Backend

## Related Documentation

- [Memory Protocol](memory.md)
- [Durability Protocol](durability.md)
- [Backend Implementation Guide](../backends.md)