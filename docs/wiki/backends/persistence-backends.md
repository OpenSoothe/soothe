# Persistence Backends

PersistStore implementations for generic key-value storage.

---

## Overview

Persistence backends provide generic key-value storage used by durability, memory, and other protocols. They implement `PersistStore` interface for storing arbitrary JSON-serializable data.

---

## PersistStore Interface

### Core Operations

```python
class AsyncPersistStore(Protocol):
    """Async key-value persistence store."""
    
    async def save(self, key: str, value: dict[str, Any]) -> None: ...
    async def load(self, key: str) -> dict[str, Any] | None: ...
    async def delete(self, key: str) -> bool: ...
    async def exists(self, key: str) -> bool: ...
    async def list_keys(self, prefix: str | None = None) -> list[str]: ...
    async def clear(self) -> None: ...
```

---

## Available Backends

### SQLitePersistStore

Local key-value storage using SQLite.

#### Features

- **Async Operations**: All operations are async (IG-258 Phase 2)
- **Key-value Storage**: Generic JSON storage
- **Simple Setup**: No external dependencies
- **Transaction Support**: ACID transaction guarantees
- **Namespace Support**: Key prefix namespaces

#### Architecture

```
SQLitePersistStore Architecture
├─ SQLite Database
│  ├─ Key-value table
│  ├─ JSON serialization
│  ├─ Async connection (aiosqlite)
│  └─ Transaction support
│
├─ Key Management
│  ├─ Key namespace support
│  ├─ Prefix listing
│  ├─ Key existence check
│  └─ Bulk key deletion
│
└─ Performance
   ├─ Connection pooling
   ├─ WAL mode
   └─ Batch operations
```

#### Implementation

```python
class SQLitePersistStore(AsyncPersistStore):
    """AsyncPersistStore implementation using SQLite."""
    
    def __init__(self, persist_dir: str, database_file: str = "persist.db"):
        """Initialize SQLite persist store."""
        
        # Resolve database path
        self._db_path = Path(persist_dir) / database_file
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Async SQLite connection
        self._conn: Any = None
        
    async def _ensure_conn(self) -> Any:
        """Ensure database connection."""
        if self._conn is None:
            import aiosqlite
            self._conn = await aiosqlite.connect(str(self._db_path))
            
            # Create table
            await self._conn.execute("""
                CREATE TABLE IF NOT EXISTS persist_store (
                    key TEXT PRIMARY KEY,
                    value JSON NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Enable WAL mode for performance
            await self._conn.execute("PRAGMA journal_mode=WAL")
            
        return self._conn
    
    async def save(self, key: str, value: dict[str, Any]) -> None:
        """Save key-value pair."""
        conn = await self._ensure_conn()
        
        await conn.execute("""
            INSERT OR REPLACE INTO persist_store (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (key, json.dumps(value)))
        
        await conn.commit()
    
    async def load(self, key: str) -> dict[str, Any] | None:
        """Load value by key."""
        conn = await self._ensure_conn()
        
        result = await conn.execute_fetchone(
            "SELECT value FROM persist_store WHERE key = ?", (key,)
        )
        
        if result is None:
            return None
        
        return json.loads(result[0])
    
    async def delete(self, key: str) -> bool:
        """Delete key."""
        conn = await self._ensure_conn()
        
        result = await conn.execute(
            "DELETE FROM persist_store WHERE key = ?", (key,)
        )
        
        await conn.commit()
        return result.rowcount > 0
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        conn = await self._ensure_conn()
        
        result = await conn.execute_fetchone(
            "SELECT 1 FROM persist_store WHERE key = ? LIMIT 1", (key,)
        )
        
        return result is not None
    
    async def list_keys(self, prefix: str | None = None) -> list[str]:
        """List keys with prefix."""
        conn = await self._ensure_conn()
        
        if prefix:
            result = await conn.execute_fetchall(
                "SELECT key FROM persist_store WHERE key LIKE ? ORDER BY key",
                (prefix + "%",)
            )
        else:
            result = await conn.execute_fetchall(
                "SELECT key FROM persist_store ORDER BY key"
            )
        
        return [row[0] for row in result]
    
    async def clear(self) -> None:
        """Clear all keys."""
        conn = await self._ensure_conn()
        
        await conn.execute("DELETE FROM persist_store")
        await conn.commit()
```

#### Configuration

```yaml
protocols:
  persistence:
    enabled: true
    backend: sqlite           # SQLitePersistStore backend
    
    # Storage
    persist_dir: ~/.soothe/persistence
    database_file: persist.db
```

#### Usage Example

```python
from soothe.backends.persistence import SQLitePersistStore

# Initialize store
store = SQLitePersistStore("~/.soothe/persistence")

# Save value
await store.save("thread:abc123", {"status": "active", "goal": "test"})

# Load value
value = await store.load("thread:abc123")

# Check existence
exists = await store.exists("thread:abc123")

# List keys with prefix
keys = await store.list_keys("thread:")

# Delete key
await store.delete("thread:abc123")

# Clear all
await store.clear()
```

---

### PostgreSQLPersistStore

Production-grade key-value storage using PostgreSQL.

#### Features

- **Async Operations**: Connection pooling with async support
- **Connection Pooling**: Efficient connection management
- **Production-grade**: Scalable, concurrent access
- **Transaction Support**: ACID transaction guarantees
- **JSON Support**: Native JSON/JSONB data type

#### Architecture

```
PostgreSQLPersistStore Architecture
├─ PostgreSQL Database
│  ├─ Key-value table
│  ├─ JSONB data type
│  ├─ Async connection pool (psycopg_pool)
│  └─ Transaction support
│
├─ Connection Pool
│  ├─ psycopg_pool.AsyncConnectionPool
│  ├─ Pool sizing
│  ├─ Connection timeout
│  └─ Connection reuse
│
└─ Performance
   ├─ JSONB indexing
   ├─ Connection pooling
   └─ Batch operations
```

#### Implementation

```python
class PostgreSQLPersistStore(AsyncPersistStore):
    """AsyncPersistStore implementation using PostgreSQL."""
    
    def __init__(
        self,
        dsn: str,
        pool_size: int = 5,
        table_name: str = "persist_store"
    ):
        """Initialize PostgreSQL persist store."""
        
        self._dsn = dsn
        self._pool_size = pool_size
        self._table_name = table_name
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
            
            # Create table
            async with self._pool.connection() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS {} (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """.format(self._table_name))
                
        return self._pool
    
    async def save(self, key: str, value: dict[str, Any]) -> None:
        """Save key-value pair."""
        pool = await self._ensure_pool()
        
        async with pool.connection() as conn:
            await conn.execute("""
                INSERT INTO {} (key, value, updated_at)
                VALUES (?, ?, NOW())
                ON CONFLICT (key) DO UPDATE SET value = ?, updated_at = NOW()
            """.format(self._table_name), (key, value, value))
    
    async def load(self, key: str) -> dict[str, Any] | None:
        """Load value by key."""
        pool = await self._ensure_pool()
        
        async with pool.connection() as conn:
            result = await conn.execute(
                "SELECT value FROM {} WHERE key = ?".format(self._table_name),
                (key,)
            )
            
            row = await result.fetchone()
            if row is None:
                return None
            
            return row[0]
    
    async def delete(self, key: str) -> bool:
        """Delete key."""
        pool = await self._ensure_pool()
        
        async with pool.connection() as conn:
            result = await conn.execute(
                "DELETE FROM {} WHERE key = ?".format(self._table_name),
                (key,)
            )
            
            return result.rowcount > 0
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        pool = await self._ensure_pool()
        
        async with pool.connection() as conn:
            result = await conn.execute(
                "SELECT 1 FROM {} WHERE key = ? LIMIT 1".format(self._table_name),
                (key,)
            )
            
            row = await result.fetchone()
            return row is not None
    
    async def list_keys(self, prefix: str | None = None) -> list[str]:
        """List keys with prefix."""
        pool = await self._ensure_pool()
        
        async with pool.connection() as conn:
            if prefix:
                result = await conn.execute(
                    "SELECT key FROM {} WHERE key LIKE ? ORDER BY key".format(self._table_name),
                    (prefix + "%",)
                )
            else:
                result = await conn.execute(
                    "SELECT key FROM {} ORDER BY key".format(self._table_name)
                )
            
            rows = await result.fetchall()
            return [row[0] for row in rows]
    
    async def clear(self) -> None:
        """Clear all keys."""
        pool = await self._ensure_pool()
        
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM {}".format(self._table_name))
```

#### Configuration

```yaml
protocols:
  persistence:
    enabled: true
    backend: postgresql       # PostgreSQLPersistStore backend
    
    # PostgreSQL connection
    dsn: postgresql://localhost/soothe
    pool_size: 5              # Connection pool size
    table_name: persist_store # Storage table
```

#### Usage Example

```python
from soothe.backends.persistence import PostgreSQLPersistStore

# Initialize store
store = PostgreSQLPersistStore(
    dsn="postgresql://localhost/soothe",
    pool_size=5
)

# All operations same as SQLitePersistStore
await store.save("thread:abc123", {"status": "active"})
value = await store.load("thread:abc123")
keys = await store.list_keys("thread:")
await store.delete("thread:abc123")
```

---

## Performance Characteristics

### SQLitePersistStore Performance

| Operation | Performance | Notes |
|-----------|-------------|-------|
| `save()` | ~10-20ms | Single-threaded writes |
| `load()` | ~5-10ms | Fast read |
| `delete()` | ~10-20ms | Single-threaded writes |
| `exists()` | ~5-10ms | Fast check |
| `list_keys()` | ~50-100ms | Index scan |
| `clear()` | ~50-100ms | Bulk delete |

### PostgreSQLPersistStore Performance

| Operation | Performance | Notes |
|-----------|-------------|-------|
| `save()` | ~20-50ms | Connection pool overhead |
| `load()` | ~10-30ms | Network overhead |
| `delete()` | ~20-50ms | Connection pool overhead |
| `exists()` | ~10-30ms | Network overhead |
| `list_keys()` | ~50-200ms | Index scan + network |
| `clear()` | ~50-200ms | Bulk delete + network |

---

## Comparison Table

### Persistence Backend Comparison

| Feature | SQLitePersistStore | PostgreSQLPersistStore |
|---------|-------------------|------------------------|
| Storage Type | SQLite database | PostgreSQL table |
| Async Operations | ✅ | ✅ |
| Connection Pooling | ❌ | ✅ |
| Concurrent Writes | ❌ (single-threaded) | ✅ |
| JSON Support | JSON serialization | Native JSONB |
| Production Use | ⚠️ (local/dev) | ✅ |
| External Dependencies | aiosqlite | PostgreSQL, psycopg_pool |
| Setup Complexity | Low | Medium |
| Scalability | Limited | High |

---

## Error Handling

### Common Errors

```python
try:
    await store.save("key", {"value": "data"})
except PersistenceBackendError as e:
    logger.error(f"Persistence backend error: {e}")
    
    # Handle specific errors:
    if "connection_failed" in str(e):
        # Retry or fallback to SQLite
        store = SQLitePersistStore("~/.soothe/persistence")
    
    elif "key_exists" in str(e):
        # Update existing key
        await store.save("key", {"value": "new_data"})
    
    elif "storage_error" in str(e):
        # Check storage health
        await store.health_check()
```

---

## Integration Patterns

### Used by Durability

```python
class SQLiteDurability(BasePersistStoreDurability):
    def __init__(self, persist_dir: str):
        store = SQLitePersistStore(persist_dir)
        super().__init__(store)
```

### Used by Memory

```python
class MemUMemory(MemoryProtocol):
    def __init__(self, config: SootheConfig):
        # MemU uses its own file store
        # But pattern is similar
```

### General Purpose Storage

```python
# Store arbitrary data
await store.save("config:default", config_dict)
config = await store.load("config:default")

# Store thread state
await store.save(f"thread_state:{thread_id}", state)
state = await store.load(f"thread_state:{thread_id}")

# Store metadata
await store.save(f"metadata:{item_id}", metadata)
metadata = await store.load(f"metadata:{item_id}")
```

---

## Testing

### Unit Testing

```python
import pytest

@pytest.mark.asyncio
async def test_sqlite_persist_store():
    """Test SQLite persist store."""
    store = SQLitePersistStore(":memory:")  # In-memory SQLite
    
    # Test save
    await store.save("test_key", {"value": "test_data"})
    
    # Test load
    data = await store.load("test_key")
    assert data["value"] == "test_data"
    
    # Test exists
    exists = await store.exists("test_key")
    assert exists is True
    
    # Test list keys
    keys = await store.list_keys()
    assert "test_key" in keys
    
    # Test delete
    result = await store.delete("test_key")
    assert result is True
    
    # Test clear
    await store.save("key1", {"value": 1})
    await store.save("key2", {"value": 2})
    await store.clear()
    
    keys = await store.list_keys()
    assert len(keys) == 0
```

---

## Configuration Examples

### Basic SQLite Configuration

```yaml
protocols:
  persistence:
    enabled: true
    backend: sqlite
    persist_dir: ~/.soothe/persistence
```

### Production PostgreSQL Configuration

```yaml
protocols:
  persistence:
    enabled: true
    backend: postgresql
    
    # PostgreSQL connection
    dsn: postgresql://user:pass@host:5432/soothe
    pool_size: 10
    table_name: persist_store
    
    # Performance tuning
    connection_timeout: 30
    max_overflow: 5
```

---

## Key Naming Patterns

### Namespace Patterns

Use key prefixes for different namespaces:

```python
# Thread namespace
await store.save("thread:abc123", thread_info)
await store.save("thread_state:abc123", state)

# Memory namespace
await store.save("memory:xyz789", memory_item)

# Config namespace
await store.save("config:default", config_dict)

# Metadata namespace
await store.save("metadata:item1", metadata)
```

### Prefix Listing

List keys by namespace:

```python
# List all threads
thread_keys = await store.list_keys("thread:")

# List all thread states
state_keys = await store.list_keys("thread_state:")

# List all memories
memory_keys = await store.list_keys("memory:")
```

---

## Related Documentation

- **[Backends Overview](README.md)** - Backend layer introduction
- **[Durability Backends](durability-backends.md)** - Durability implementation
- **[Memory Backends](memory-backends.md)** - Memory implementation
- **[RFC-001](../../specs/RFC-001-core-modules-architecture.md)** - Persistence protocol spec

---

## API Reference

### SQLitePersistStore Class

```python
class SQLitePersistStore(AsyncPersistStore):
    """AsyncPersistStore implementation using SQLite."""
    
    def __init__(self, persist_dir: str, database_file: str = "persist.db") -> None: ...
    
    async def save(self, key: str, value: dict[str, Any]) -> None: ...
    async def load(self, key: str) -> dict[str, Any] | None: ...
    async def delete(self, key: str) -> bool: ...
    async def exists(self, key: str) -> bool: ...
    async def list_keys(self, prefix: str | None = None) -> list[str]: ...
    async def clear(self) -> None: ...
```

### PostgreSQLPersistStore Class

```python
class PostgreSQLPersistStore(AsyncPersistStore):
    """AsyncPersistStore implementation using PostgreSQL."""
    
    def __init__(
        self,
        dsn: str,
        pool_size: int = 5,
        table_name: str = "persist_store"
    ) -> None: ...
    
    async def save(self, key: str, value: dict[str, Any]) -> None: ...
    async def load(self, key: str) -> dict[str, Any] | None: ...
    async def delete(self, key: str) -> bool: ...
    async def exists(self, key: str) -> bool: ...
    async def list_keys(self, prefix: str | None = None) -> list[str]: ...
    async def clear(self) -> None: ...
```

---

## See Also

- **[PersistStore Protocol](../architecture/protocols.md)** - Protocol definition
- **[Protocol Resolver](../core/resolver.md)** - Backend resolution