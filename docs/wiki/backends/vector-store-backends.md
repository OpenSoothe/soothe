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
    """Vector storage and semantic search."""
    
    async def upsert(self, record: VectorRecord) -> str: ...
    async def batch_upsert(self, records: list[VectorRecord]) -> list[str]: ...
    async def search(self, query_vector: list[float], limit: int = 10, filter: dict | None = None) -> list[VectorRecord]: ...
    async def get(self, record_id: str) -> VectorRecord | None: ...
    async def delete(self, record_id: str) -> bool: ...
    async def count(self, filter: dict | None = None) -> int: ...
```

---

## Vector Record Model

### VectorRecord

Vector record data structure:

```python
class VectorRecord(BaseModel):
    """Vector record with metadata."""
    
    id: str                      # Unique identifier
    vector: list[float]          # Embedding vector
    metadata: dict[str, Any]     # Associated metadata
    created_at: datetime         # Creation timestamp
    updated_at: datetime         # Last update timestamp
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
        vector_size: int = 1536
    ):
        """Initialize PGVectorStore."""
        
        self._collection = collection
        self._dsn = dsn
        self._pool_size = pool_size
        self._index_type = index_type
        self._vector_size = vector_size
        self._pool: Any = None
        
    async def _ensure_pool(self) -> Any:
        """Ensure connection pool."""
        if self._pool is None:
            from psycopg_pool import AsyncConnectionPool
            
            self._pool = AsyncConnectionPool(
                self._dsn,
                min_size=1,
                max_size=self._pool_size,
                open=False
            )
            
            await self._pool.open()
            
            # Create table and index
            async with self._pool.connection() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS {} (
                        id TEXT PRIMARY KEY,
                        vector VECTOR({}),
                        metadata JSONB,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """.format(self._collection, self._vector_size))
                
                # Create index based on type
                if self._index_type == "hnsw":
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS {}_vector_idx ON {}
                        USING hnsw (vector vector_cosine_ops)
                    """.format(self._collection, self._collection))
                    
                elif self._index_type == "ivfflat":
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS {}_vector_idx ON {}
                        USING ivfflat (vector vector_cosine_ops)
                        WITH (lists = 100)
                    """.format(self._collection, self._collection))
        
        return self._pool
    
    async def upsert(self, record: VectorRecord) -> str:
        """Insert or update vector record."""
        pool = await self._ensure_pool()
        
        async with pool.connection() as conn:
            await conn.execute("""
                INSERT INTO {} (id, vector, metadata, updated_at)
                VALUES (?, ?, ?, NOW())
                ON CONFLICT (id) DO UPDATE SET vector = ?, metadata = ?, updated_at = NOW()
            """.format(self._collection),
                (record.id, record.vector, record.metadata, record.vector, record.metadata)
            )
            
            return record.id
    
    async def batch_upsert(self, records: list[VectorRecord]) -> list[str]:
        """Batch insert or update vector records."""
        ids = []
        for record in records:
            id = await self.upsert(record)
            ids.append(id)
        return ids
    
    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        filter: dict | None = None
    ) -> list[VectorRecord]:
        """Search vectors by similarity."""
        pool = await self._ensure_pool()
        
        async with pool.connection() as conn:
            # Build query with optional filter
            if filter:
                filter_clause = " AND metadata @> ?"
                params = [query_vector, filter, limit]
            else:
                filter_clause = ""
                params = [query_vector, limit]
            
            result = await conn.execute("""
                SELECT id, vector, metadata, created_at, updated_at
                FROM {}
                WHERE 1=1 {}
                ORDER BY vector <=> ?
                LIMIT ?
            """.format(self._collection, filter_clause), params)
            
            rows = await result.fetchall()
            
            # Convert to VectorRecord
            records = []
            for row in rows:
                records.append(VectorRecord(
                    id=row[0],
                    vector=list(row[1]),
                    metadata=row[2],
                    created_at=row[3],
                    updated_at=row[4]
                ))
            
            return records
    
    async def get(self, record_id: str) -> VectorRecord | None:
        """Get vector record by ID."""
        pool = await self._ensure_pool()
        
        async with pool.connection() as conn:
            result = await conn.execute("""
                SELECT id, vector, metadata, created_at, updated_at
                FROM {}
                WHERE id = ?
            """.format(self._collection), (record_id,))
            
            row = await result.fetchone()
            if row is None:
                return None
            
            return VectorRecord(
                id=row[0],
                vector=list(row[1]),
                metadata=row[2],
                created_at=row[3],
                updated_at=row[4]
            )
    
    async def delete(self, record_id: str) -> bool:
        """Delete vector record."""
        pool = await self._ensure_pool()
        
        async with pool.connection() as conn:
            result = await conn.execute(
                "DELETE FROM {} WHERE id = ?".format(self._collection),
                (record_id,)
            )
            
            return result.rowcount > 0
    
    async def count(self, filter: dict | None = None) -> int:
        """Count vector records."""
        pool = await self._ensure_pool()
        
        async with pool.connection() as conn:
            if filter:
                result = await conn.execute(
                    "SELECT COUNT(*) FROM {} WHERE metadata @> ?".format(self._collection),
                    (filter,)
                )
            else:
                result = await conn.execute(
                    "SELECT COUNT(*) FROM {}".format(self._collection)
                )
            
            row = await result.fetchone()
            return row[0]
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
    vector_size=1536
)

# Upsert vector
record = VectorRecord(
    id="mem_abc123",
    vector=[0.1, 0.2, ...],  # Embedding vector
    metadata={"content": "test memory", "tags": ["test"]}
)
await store.upsert(record)

# Search vectors
results = await store.search(
    query_vector=[0.1, 0.2, ...],
    limit=10,
    filter={"tags": ["test"]}
)

# Get vector
record = await store.get("mem_abc123")

# Delete vector
await store.delete("mem_abc123")

# Count vectors
total = await store.count()
filtered_count = await store.count(filter={"tags": ["test"]})
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
    """VectorStoreProtocol implementation using sqlite-vec."""
    
    def __init__(
        self,
        persist_dir: str,
        collection: str = "soothe_vectors",
        vector_size: int = 1536,
        database_file: str = "vector.db"
    ):
        """Initialize SQLiteVecStore."""
        
        self._db_path = Path(persist_dir) / database_file
        self._collection = collection
        self._vector_size = vector_size
        self._conn: Any = None
        
    async def _ensure_conn(self) -> Any:
        """Ensure database connection."""
        if self._conn is None:
            import aiosqlite
            import sqlite_vec
            
            self._conn = await aiosqlite.connect(str(self._db_path))
            
            # Load sqlite-vec extension
            await sqlite_vec.load(self._conn)
            
            # Create table
            await self._conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS {} USING vec0(
                    id TEXT PRIMARY KEY,
                    vector FLOAT[{}] HNSW,
                    metadata JSON,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """.format(self._collection, self._vector_size))
            
            # Enable WAL mode
            await self._conn.execute("PRAGMA journal_mode=WAL")
        
        return self._conn
    
    async def upsert(self, record: VectorRecord) -> str:
        """Insert or update vector record."""
        conn = await self._ensure_conn()
        
        await conn.execute("""
            INSERT OR REPLACE INTO {} (id, vector, metadata, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """.format(self._collection),
            (record.id, record.vector, json.dumps(record.metadata))
        )
        
        await conn.commit()
        return record.id
    
    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        filter: dict | None = None
    ) -> list[VectorRecord]:
        """Search vectors by similarity."""
        conn = await self._ensure_conn()
        
        # Build query with optional filter
        if filter:
            # Manual metadata filtering (sqlite-vec doesn't support JSON filtering)
            filter_clause = " AND json_extract(metadata, ?) = ?"
            filter_key = filter.keys()[0]
            filter_value = filter[filter_key]
            params = [query_vector, f'$.{filter_key}', filter_value, limit]
        else:
            filter_clause = ""
            params = [query_vector, limit]
        
        result = await conn.execute("""
            SELECT id, vector, metadata, created_at, updated_at
            FROM {}
            WHERE vector MATCH ? {}
            ORDER BY distance
            LIMIT ?
        """.format(self._collection, filter_clause), params)
        
        rows = await result.fetchall()
        
        # Convert to VectorRecord
        records = []
        for row in rows:
            records.append(VectorRecord(
                id=row[0],
                vector=row[1],
                metadata=json.loads(row[2]),
                created_at=row[3],
                updated_at=row[4]
            ))
        
        return records
    
    # Other methods similar to PGVectorStore
```

#### Configuration

```yaml
vector_store:
  enabled: true
  provider: sqlite_vec      # SQLiteVecStore backend
  
  # Storage
  persist_dir: ~/.soothe/vector_store
  database_file: vector.db
  
  # Collection settings
  collection: soothe_vectors
  vector_size: 1536         # OpenAI embedding dimension
```

#### Usage Example

```python
from soothe.backends.vector_store import SQLiteVecStore

# Initialize store
store = SQLiteVecStore(
    persist_dir="~/.soothe/vector_store",
    collection="memories",
    vector_size=1536
)

# All operations same as PGVectorStore
await store.upsert(record)
results = await store.search(query_vector, limit=10)
record = await store.get("mem_abc123")
await store.delete("mem_abc123")
total = await store.count()
```

---

### WeaviateStore

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
WeaviateStore Architecture
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
class WeaviateStore(VectorStoreProtocol):
    """VectorStoreProtocol implementation using Weaviate."""
    
    def __init__(
        self,
        url: str = "http://localhost:8080",
        collection: str = "SootheVectors",
        vector_size: int = 1536
    ):
        """Initialize WeaviateStore."""
        
        self._url = url
        self._collection = collection
        self._vector_size = vector_size
        self._client: Any = None
        
    async def _ensure_client(self) -> Any:
        """Ensure Weaviate client."""
        if self._client is None:
            import weaviate
            
            self._client = weaviate.Client(self._url)
            
            # Create collection class if not exists
            if not self._client.schema.exists(self._collection):
                class_obj = {
                    "class": self._collection,
                    "vectorizer": "none",  # We provide vectors manually
                    "properties": [
                        {"name": "metadata", "dataType": ["text"]},
                        {"name": "created_at", "dataType": ["date"]},
                        {"name": "updated_at", "dataType": ["date"]}
                    ]
                }
                
                self._client.schema.create_class(class_obj)
        
        return self._client
    
    async def upsert(self, record: VectorRecord) -> str:
        """Insert or update vector record."""
        client = await self._ensure_client()
        
        # Check if object exists
        exists = client.data_object.exists(
            class_name=self._collection,
            uuid=record.id
        )
        
        if exists:
            # Update existing object
            client.data_object.update(
                uuid=record.id,
                class_name=self._collection,
                properties={
                    "metadata": json.dumps(record.metadata),
                    "updated_at": record.updated_at.isoformat()
                },
                vector=record.vector
            )
        else:
            # Create new object
            client.data_object.create(
                class_name=self._collection,
                uuid=record.id,
                properties={
                    "metadata": json.dumps(record.metadata),
                    "created_at": record.created_at.isoformat(),
                    "updated_at": record.updated_at.isoformat()
                },
                vector=record.vector
            )
        
        return record.id
    
    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        filter: dict | None = None
    ) -> list[VectorRecord]:
        """Search vectors by similarity."""
        client = await self._ensure_client()
        
        # Build GraphQL query
        query = client.query.get(self._collection, ["metadata", "created_at", "updated_at"])
        
        # Add vector search
        query = query.with_near_vector({"vector": query_vector})
        
        # Add filter if provided
        if filter:
            # Convert filter to Weaviate where filter
            where_filter = self._build_where_filter(filter)
            query = query.with_where(where_filter)
        
        # Add limit
        query = query.with_limit(limit)
        
        # Execute query
        result = query.do()
        
        # Convert to VectorRecord
        records = []
        for obj in result["data"]["Get"][self._collection]:
            records.append(VectorRecord(
                id=obj["_additional"]["id"],
                vector=obj["_additional"]["vector"],
                metadata=json.loads(obj["metadata"]),
                created_at=obj["created_at"],
                updated_at=obj["updated_at"]
            ))
        
        return records
    
    def _build_where_filter(self, filter: dict) -> dict:
        """Build Weaviate where filter from metadata filter."""
        # Simple implementation for single key filter
        key = list(filter.keys())[0]
        value = filter[key]
        
        return {
            "path": ["metadata"],
            "operator": "Contains",
            "valueString": f'"{key}": "{value}"'
        }
    
    # Other methods similar to PGVectorStore
```

#### Configuration

```yaml
vector_store:
  enabled: true
  provider: weaviate        # WeaviateStore backend
  
  # Weaviate connection
  url: http://localhost:8080
  
  # Collection settings
  collection: SootheVectors
  vector_size: 1536
  
  # Authentication (optional)
  api_key: null             # Weaviate API key
```

#### Usage Example

```python
from soothe.backends.vector_store import WeaviateStore

# Initialize store
store = WeaviateStore(
    url="http://localhost:8080",
    collection="Memories",
    vector_size=1536
)

# All operations same as PGVectorStore
await store.upsert(record)
results = await store.search(query_vector, limit=10)
record = await store.get("mem_abc123")
await store.delete("mem_abc123")
total = await store.count()
```

---

## Performance Characteristics

### PGVectorStore Performance

| Operation | Performance | Notes |
|-----------|-------------|-------|
| `upsert()` | ~20-50ms | Connection pool overhead |
| `batch_upsert()` | ~100-500ms | Batch size dependent |
| `search()` | ~50-100ms | HNSW index, fast approximate search |
| `get()` | ~10-30ms | Network overhead |
| `delete()` | ~20-50ms | Connection pool overhead |
| `count()` | ~50-200ms | Index scan + network |

### SQLiteVecStore Performance

| Operation | Performance | Notes |
|-----------|-------------|-------|
| `upsert()` | ~10-20ms | Local, no network |
| `batch_upsert()` | ~50-200ms | Batch size dependent |
| `search()` | ~20-50ms | HNSW index, local |
| `get()` | ~5-10ms | Fast local read |
| `delete()` | ~10-20ms | Local |
| `count()` | ~50-100ms | Index scan |

### WeaviateStore Performance

| Operation | Performance | Notes |
|-----------|-------------|-------|
| `upsert()` | ~50-100ms | GraphQL API overhead |
| `batch_upsert()` | ~200-1000ms | Batch API overhead |
| `search()` | ~100-200ms | GraphQL query overhead |
| `get()` | ~50-100ms | REST API overhead |
| `delete()` | ~50-100ms | REST API overhead |
| `count()` | ~100-300ms | GraphQL aggregation |

---

## Comparison Table

### Vector Store Backend Comparison

| Feature | PGVectorStore | SQLiteVecStore | WeaviateStore |
|---------|---------------|---------------|--------------|
| Storage Type | PostgreSQL pgvector | sqlite-vec | Weaviate |
| Index Type | HNSW/IVFFlat | HNSW | HNSW (built-in) |
| Async Operations | ✅ | ✅ | ✅ |
| Connection Pooling | ✅ | ❌ | ✅ (via client) |
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
    await vector_store.upsert(record)
except VectorStoreBackendError as e:
    logger.error(f"Vector store backend error: {e}")
    
    # Handle specific errors:
    if "connection_failed" in str(e):
        # Retry or fallback
        pass
    
    elif "index_error" in str(e):
        # Reindex
        await vector_store._reindex()
    
    elif "dimension_mismatch" in str(e):
        # Check vector dimension
        if len(record.vector) != vector_store._vector_size:
            # Regenerate embedding with correct dimension
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
    
    # Test upsert
    record = VectorRecord(
        id="test_1",
        vector=[0.1] * 1536,
        metadata={"test": "data"}
    )
    await store.upsert(record)
    
    # Test search
    results = await store.search([0.1] * 1536, limit=10)
    assert len(results) > 0
    
    # Test get
    result = await store.get("test_1")
    assert result.id == "test_1"
    
    # Test count
    count = await store.count()
    assert count > 0
    
    # Test delete
    await store.delete("test_1")
    result = await store.get("test_1")
    assert result is None
```

---

## Configuration Examples

### Basic SQLiteVec Configuration

```yaml
vector_store:
  enabled: true
  provider: sqlite_vec
  persist_dir: ~/.soothe/vector_store
  collection: soothe_vectors
  vector_size: 1536
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
  api_key: your-api-key
  
  # Collection settings
  collection: SootheVectors
  vector_size: 1536
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
        vector_size: int = 1536
    ) -> None: ...
```

### SQLiteVecStore Class

```python
class SQLiteVecStore(VectorStoreProtocol):
    """VectorStoreProtocol implementation using sqlite-vec."""
    
    def __init__(
        self,
        persist_dir: str,
        collection: str = "soothe_vectors",
        vector_size: int = 1536,
        database_file: str = "vector.db"
    ) -> None: ...
```

### WeaviateStore Class

```python
class WeaviateStore(VectorStoreProtocol):
    """VectorStoreProtocol implementation using Weaviate."""
    
    def __init__(
        self,
        url: str = "http://localhost:8080",
        collection: str = "SootheVectors",
        vector_size: int = 1536
    ) -> None: ...
```

---

## See Also

- **[VectorStore Protocol](../architecture/protocols.md)** - Protocol definition
- **[Protocol Resolver](../core/resolver.md)** - Backend resolution
- **[Memory Backends](memory-backends.md)** - Memory integration