# Backends Layer

Protocol implementations for Soothe's core infrastructure.

---

## Overview

The backends layer (`soothe.backends`) provides concrete implementations for Soothe's protocol interfaces. Each backend implements a specific protocol with different storage engines, algorithms, and trade-offs.

```
┌─────────────────────────────────────────────────────┐
│  Protocol Layer (soothe.protocols)                  │
│  • Abstract interfaces                              │
│  • Data models                                      │
│  • Integration contracts                            │
└──────────────────────┬──────────────────────────────┘
                       │ implements
┌──────────────────────▼──────────────────────────────┐
│  Backends Layer (soothe.backends)                   │
│                                                     │
│  memory/        MemoryProtocol implementations     │
│  durability/    DurabilityProtocol implementations │
│  persistence/   PersistStore implementations       │
│  vector_store/  VectorStoreProtocol implementations│
│  cognition/     PlannerProtocol implementations    │
│  backends/policy/PolicyProtocol implementations    │
└──────────────────────┬──────────────────────────────┘
                       │ uses
┌──────────────────────▼──────────────────────────────┐
│  External Dependencies                              │
│  • PostgreSQL / SQLite                              │
│  • Vector engines (pgvector, sqlite-vec, Weaviate) │
│  • MemU memory store                                │
└─────────────────────────────────────────────────────┘
```

---

## Backend Categories

### Memory Backends
Implement `MemoryProtocol` for cross-thread persistent memory.

| Backend | Type | Persistence | Features |
|---------|------|-------------|----------|
| **MemUMemory** | Semantic | File-based | LLM-powered memory management, embeddings, clustering |

**See**: [Memory Backends](memory-backends.md)

---

### Durability Backends
Implement `DurabilityProtocol` for thread lifecycle and state management.

| Backend | Storage | Async | Features |
|---------|---------|-------|----------|
| **SQLiteDurability** | SQLite | ✅ | Local persistence, simple setup |
| **PostgreSQLDurability** | PostgreSQL | ✅ | Production-grade, connection pooling |

**See**: [Durability Backends](durability-backends.md)

---

### Persistence Backends
Implement `PersistStore` for generic key-value storage.

| Backend | Storage | Async | Features |
|---------|---------|-------|----------|
| **SQLitePersistStore** | SQLite | ✅ | Local key-value store |
| **PostgreSQLPersistStore** | PostgreSQL | ✅ | Production-grade persistence |

**See**: [Persistence Backends](persistence-backends.md)

---

### Vector Store Backends
Implement `VectorStoreProtocol` for semantic search and embeddings.

| Backend | Engine | Index Type | Features |
|---------|---------|------------|----------|
| **PGVectorStore** | PostgreSQL pgvector | HNSW/IVFFlat | Production-grade, scalable |
| **SQLiteVecStore** | sqlite-vec | HNSW | Local, no external dependencies |
| **WeaviateStore** | Weaviate | HNSW | Cloud-native, GraphQL API |

**See**: [Vector Store Backends](vector-store-backends.md)

---

### Policy Backends
Implement `PolicyProtocol` for security and filesystem policies.

| Backend | Type | Configuration | Features |
|---------|------|---------------|----------|
| **ConfigDrivenPolicy** | Config-based | YAML | Flexible policy rules, least-privilege |

**See**: [Policy Backends](policy-backends.md)

---

## Backend Resolution

### Protocol Resolver

Backends are resolved from configuration by the resolver:

```python
from soothe.core.resolver import resolve_memory, resolve_durability
from soothe.config import SootheConfig

config = SootheConfig.from_file("config.yml")

# Resolve backends
memory = resolve_memory(config)       # MemUMemory instance
durability = resolve_durability(config)  # SQLiteDurability instance
```

**See**: [Protocol Resolver](../core/resolver.md)

---

## Configuration

### Backend Selection

Select backends via configuration:

```yaml
protocols:
  memory:
    enabled: true
    backend: memu         # MemUMemory
    persist_dir: ~/.soothe/memory
  
  durability:
    enabled: true
    backend: sqlite       # SQLiteDurability
    persist_dir: ~/.soothe/durability
  
  vector_store:
    enabled: true
    provider: pgvector    # PGVectorStore
    dsn: postgresql://localhost/soothe
```

---

## Backend Comparison

### Decision Matrix

Choose backends based on requirements:

| Requirement | Recommended Backend | Reason |
|-------------|--------------------|--------|
| Local development | SQLite variants | Simple setup, no external deps |
| Production deployment | PostgreSQL variants | Scalable, connection pooling |
| Semantic memory | MemUMemory | LLM-powered, embeddings |
| Vector search | PGVectorStore | Production-grade pgvector |
| No external deps | SQLiteVecStore | Embedded vector search |

---

## Backend Implementation Pattern

All backends follow the same implementation pattern:

```python
class MyBackend:
    """Backend implementation for SomeProtocol."""
    
    def __init__(self, config: SomeConfig):
        """Initialize backend with configuration."""
        self._store = create_store(config)
    
    async def operation(self, *args, **kwargs):
        """Implement protocol operation."""
        # Validate inputs
        # Execute operation
        # Handle errors
        # Return result
```

---

## Async Operations

All backend operations are async:

```python
# Memory operations
await memory.remember(item)
items = await memory.recall(query)

# Durability operations
thread = await durability.create_thread(metadata)
await durability.persist_thread(thread_id, state)

# Vector operations
await vector_store.upsert(record)
results = await vector_store.search(query_vector, limit=10)
```

---

## Error Handling

Backend errors follow standard patterns:

```python
try:
    await memory.remember(item)
except BackendError as e:
    logger.error(f"Memory backend error: {e}")
    # Handle error
```

Common error types:
- `BackendNotFoundError`: Backend implementation not found
- `BackendConnectionError`: Connection to storage failed
- `BackendOperationError`: Operation execution failed
- `BackendValidationError`: Input validation failed

---

## Performance Considerations

### Memory Backends
- MemUMemory: LLM calls for clustering, embedding generation overhead
- Consider batch operations for multiple items

### Durability Backends
- SQLite: Good for local development, single-threaded writes
- PostgreSQL: Better for concurrent access, production use

### Vector Store Backends
- PGVectorStore: HNSW index for fast search, connection pooling
- SQLiteVecStore: Embedded search, limited scalability
- Weaviate: Cloud-native, GraphQL API overhead

---

## Backend Dependencies

### External Dependencies

| Backend | Dependencies |
|---------|-------------|
| MemUMemory | MemU store, LLM models, embedding models |
| SQLiteDurability | SQLite (built-in) |
| PostgreSQLDurability | PostgreSQL, psycopg_pool |
| PGVectorStore | PostgreSQL, pgvector extension, psycopg_pool |
| SQLiteVecStore | sqlite-vec extension |
| WeaviateStore | weaviate-client |

---

## Testing Backends

### Unit Testing

Test backend implementations:

```python
import pytest

@pytest.mark.asyncio
async def test_memory_backend():
    """Test memory backend implementation."""
    config = create_test_config()
    memory = MemUMemory(config)
    
    # Test remember
    item = MemoryItem(content="test", tags=["test"])
    item_id = await memory.remember(item)
    assert item_id is not None
    
    # Test recall
    items = await memory.recall("test")
    assert len(items) > 0
```

---

## Related Documentation

- **[Protocols Overview](../architecture/protocol-first.md)** - Protocol definitions
- **[Protocol Resolver](../core/resolver.md)** - Backend resolution
- **[Memory Backends](memory-backends.md)** - Memory implementation details
- **[Durability Backends](durability-backends.md)** - Durability implementation details
- **[Vector Store Backends](vector-store-backends.md)** - Vector search details
- **[RFC-001](../../specs/RFC-001-core-modules-architecture.md)** - Protocol architecture

---

## Backend Index

### Memory Backends
- **[MemUMemory](memory-backends.md#memu-memory)** - Semantic memory with LLM

### Durability Backends
- **[SQLiteDurability](durability-backends.md#sqlite-durability)** - Local persistence
- **[PostgreSQLDurability](durability-backends.md#postgresql-durability)** - Production-grade

### Persistence Backends
- **[SQLitePersistStore](persistence-backends.md#sqlite-persist)** - Local key-value
- **[PostgreSQLPersistStore](persistence-backends.md#postgresql-persist)** - Production-grade

### Vector Store Backends
- **[PGVectorStore](vector-store-backends.md#pgvector)** - PostgreSQL pgvector
- **[SQLiteVecStore](vector-store-backends.md#sqlite-vec)** - Embedded vector search
- **[WeaviateStore](vector-store-backends.md#weaviate)** - Cloud-native

### Policy Backends
- **[ConfigDrivenPolicy](policy-backends.md#config-driven-policy)** - Configuration-based policy

---

## Quick Navigation

| Backend Type | Document | Primary Use Case |
|--------------|----------|------------------|
| Memory | [Memory Backends](memory-backends.md) | Cross-thread persistent memory |
| Durability | [Durability Backends](durability-backends.md) | Thread lifecycle management |
| Persistence | [Persistence Backends](persistence-backends.md) | Generic key-value storage |
| Vector Store | [Vector Store Backends](vector-store-backends.md) | Semantic search and embeddings |
| Policy | [Policy Backends](policy-backends.md) | Security and filesystem policies |