# Durability Backends

DurabilityProtocol implementations for thread lifecycle and state management.

---

## Overview

Durability backends implement `DurabilityProtocol` for managing thread lifecycle, state persistence, and recovery from crashes. They provide the foundation for Soothe's durable execution model.

---

## DurabilityProtocol Interface

### Core Operations

```python
class DurabilityProtocol(Protocol):
    """Thread lifecycle and state management."""
    
    async def create_thread(self, metadata: ThreadMetadata, thread_id: str | None = None) -> ThreadInfo: ...
    async def resume_thread(self, thread_id: str) -> ThreadInfo: ...
    async def suspend_thread(self, thread_id: str) -> ThreadInfo: ...
    async def complete_thread(self, thread_id: str) -> ThreadInfo: ...
    async def persist_thread(self, thread_id: str, state: dict[str, Any]) -> None: ...
    async def restore_thread(self, thread_id: str) -> dict[str, Any]: ...
    async def list_threads(self, filter: ThreadFilter) -> list[ThreadInfo]: ...
    async def delete_thread(self, thread_id: str) -> bool: ...
```

---

## Available Backends

### SQLiteDurability

Local persistence using SQLite database.

#### Features

- **Async Operations**: All operations are async (IG-258 Phase 2)
- **Thread Index**: Maintains thread index for fast listing
- **State Persistence**: Stores thread state as JSON
- **Metadata Management**: Thread metadata storage
- **Simple Setup**: No external dependencies

#### Architecture

```
SQLiteDurability Backend Architecture
├─ BasePersistStoreDurability (base class)
│  ├─ Thread lifecycle methods
│  ├─ Metadata management
│  ├─ Thread index management
│  └─ State persistence
│
├─ SQLitePersistStore
│  ├─ Async SQLite connection
│  ├─ Key-value storage
│  ├─ JSON serialization
│  └─ Transaction support
│
└─ Data Models
   ├─ ThreadInfo
   ├─ ThreadMetadata
   ├─ ThreadFilter
   └─ ThreadStatus
```

#### Implementation

```python
class SQLiteDurability(BasePersistStoreDurability):
    """DurabilityProtocol implementation using SQLite."""
    
    def __init__(self, persist_dir: str):
        """Initialize SQLite durability backend."""
        
        # Create async SQLite store
        store = SQLitePersistStore(persist_dir)
        
        # Initialize base class
        super().__init__(store)
    
    # Inherits all methods from BasePersistStoreDurability:
    # - create_thread()
    # - resume_thread()
    # - suspend_thread()
    # - complete_thread()
    # - persist_thread()
    # - restore_thread()
    # - list_threads()
    # - delete_thread()
```

#### Configuration

```yaml
protocols:
  durability:
    enabled: true
    backend: sqlite           # SQLiteDurability backend
    
    # Persistence
    persist_dir: ~/.soothe/durability  # Storage directory
    database_file: durability.db      # SQLite database file
```

#### Usage Example

```python
from soothe.backends.durability import SQLiteDurability
from soothe.protocols.durability import ThreadMetadata, ThreadFilter

# Initialize backend
durability = SQLiteDurability("~/.soothe/durability")

# Create thread
metadata = ThreadMetadata(
    goal="Analyze codebase structure",
    workspace="/path/to/project",
    tags=["analysis", "code"]
)
thread = await durability.create_thread(metadata)

# Persist state
await durability.persist_thread(thread.thread_id, {"iteration": 1, "steps": []})

# Restore state
state = await durability.restore_thread(thread.thread_id)

# List threads
filter = ThreadFilter(status="active", limit=10)
threads = await durability.list_threads(filter)

# Complete thread
await durability.complete_thread(thread.thread_id)
```

---

### PostgreSQLDurability

Production-grade persistence using PostgreSQL.

#### Features

- **Async Operations**: Connection pooling with async support
- **Connection Pooling**: Efficient connection management
- **Production-grade**: Scalable, concurrent access
- **Transaction Support**: ACID transaction guarantees
- **Thread Index**: Optimized thread listing

#### Architecture

```
PostgreSQLDurability Backend Architecture
├─ BasePersistStoreDurability (base class)
│  ├─ Thread lifecycle methods
│  ├─ Metadata management
│  ├─ Thread index management
│  └─ State persistence
│
├─ PostgreSQLPersistStore
│  ├─ Async connection pool
│  ├─ psycopg_pool integration
│  ├─ Key-value table
│  ├─ JSON serialization
│  └─ Transaction support
│
└─ Configuration
   ├─ PostgreSQL DSN
   ├─ Pool size
   ├─ Connection timeout
   └─ Table name
```

#### Implementation

```python
class PostgreSQLDurability(BasePersistStoreDurability):
    """DurabilityProtocol implementation using PostgreSQL."""
    
    def __init__(self, dsn: str, pool_size: int = 5):
        """Initialize PostgreSQL durability backend."""
        
        # Create async PostgreSQL store
        store = PostgreSQLPersistStore(
            dsn=dsn,
            pool_size=pool_size,
            table_name="durability"
        )
        
        # Initialize base class
        super().__init__(store)
    
    # Inherits all methods from BasePersistStoreDurability
```

#### Configuration

```yaml
protocols:
  durability:
    enabled: true
    backend: postgresql       # PostgreSQLDurability backend
    
    # PostgreSQL connection
    dsn: postgresql://localhost/soothe
    pool_size: 5              # Connection pool size
    table_name: durability    # Storage table
    
    # Performance
    connection_timeout: 30    # Connection timeout (seconds)
```

#### Usage Example

```python
from soothe.backends.durability import PostgreSQLDurability

# Initialize backend
durability = PostgreSQLDurability(
    dsn="postgresql://localhost/soothe",
    pool_size=5
)

# All operations same as SQLiteDurability
thread = await durability.create_thread(metadata)
await durability.persist_thread(thread.thread_id, state)
threads = await durability.list_threads(filter)
```

---

## Durability Data Model

### ThreadInfo

Thread state container:

```python
class ThreadInfo(BaseModel):
    """Thread information."""
    
    thread_id: str             # Unique thread ID
    status: ThreadStatus       # Thread status
    created_at: datetime       # Creation timestamp
    updated_at: datetime       # Last update timestamp
    metadata: ThreadMetadata   # Thread metadata
```

### ThreadMetadata

Thread metadata:

```python
class ThreadMetadata(BaseModel):
    """Thread metadata."""
    
    goal: str                  # Thread goal
    workspace: str             # Workspace directory
    tags: list[str] = []       # Classification tags
    parent_thread: str | None  # Parent thread ID
    config_overrides: dict = {} # Configuration overrides
```

### ThreadFilter

Thread listing filter:

```python
class ThreadFilter(BaseModel):
    """Thread filter criteria."""
    
    status: ThreadStatus | None  # Filter by status
    tags: list[str] | None       # Filter by tags
    workspace: str | None        # Filter by workspace
    limit: int = 10              # Result limit
    offset: int = 0              # Result offset
```

### ThreadStatus

Thread status enumeration:

```python
class ThreadStatus(str, Enum):
    """Thread status."""
    
    DRAFT = "draft"           # Not yet started
    ACTIVE = "active"         # Currently running
    SUSPENDED = "suspended"   # Paused execution
    COMPLETED = "completed"   # Finished successfully
    FAILED = "failed"         # Failed execution
    DELETED = "deleted"       # Marked for deletion
```

---

## Thread Lifecycle

### Thread Creation

```python
async def create_thread(self, metadata: ThreadMetadata) -> ThreadInfo:
    """Create a new thread."""
    
    # Generate thread ID
    thread_id = generate_thread_id()
    
    # Create thread info
    now = datetime.now(tz=UTC)
    info = ThreadInfo(
        thread_id=thread_id,
        status="active",
        created_at=now,
        updated_at=now,
        metadata=metadata
    )
    
    # Save thread info
    await self._store.save(f"thread:{thread_id}", info.model_dump())
    
    # Add to thread index
    await self._update_thread_index(thread_id, action="add")
    
    return info
```

### Thread State Management

```python
async def persist_thread(self, thread_id: str, state: dict[str, Any]) -> None:
    """Persist thread state."""
    
    # Validate thread exists
    info = await self.restore_thread_info(thread_id)
    
    # Save state
    await self._store.save(f"thread_state:{thread_id}", state)
    
    # Update thread timestamp
    await self._update_thread_timestamp(thread_id)

async def restore_thread(self, thread_id: str) -> dict[str, Any]:
    """Restore thread state."""
    
    # Load state
    state = await self._store.load(f"thread_state:{thread_id}")
    
    if state is None:
        return {}
    
    return state
```

### Thread Listing

```python
async def list_threads(self, filter: ThreadFilter) -> list[ThreadInfo]:
    """List threads matching filter."""
    
    # Load thread index
    index = await self._load_thread_index()
    
    # Filter threads
    threads = []
    for thread_id in index["thread_ids"]:
        info = await self.restore_thread_info(thread_id)
        
        # Apply filters
        if filter.status and info.status != filter.status:
            continue
        
        if filter.tags and not any(tag in info.metadata.tags for tag in filter.tags):
            continue
        
        if filter.workspace and info.metadata.workspace != filter.workspace:
            continue
        
        threads.append(info)
    
    # Apply limit/offset
    threads = threads[filter.offset:filter.offset + filter.limit]
    
    return threads
```

---

## BasePersistStoreDurability

### Base Implementation

All durability backends inherit from `BasePersistStoreDurability`:

```python
class BasePersistStoreDurability:
    """Base implementation using AsyncPersistStore."""
    
    def __init__(self, persist_store: AsyncPersistStore):
        """Initialize with async persist store."""
        self._store = persist_store
        self._thread_index_key = "thread_index"
    
    # Thread lifecycle methods
    async def create_thread(self, metadata: ThreadMetadata) -> ThreadInfo: ...
    async def resume_thread(self, thread_id: str) -> ThreadInfo: ...
    async def suspend_thread(self, thread_id: str) -> ThreadInfo: ...
    async def complete_thread(self, thread_id: str) -> ThreadInfo: ...
    async def delete_thread(self, thread_id: str) -> bool: ...
    
    # State management methods
    async def persist_thread(self, thread_id: str, state: dict[str, Any]) -> None: ...
    async def restore_thread(self, thread_id: str) -> dict[str, Any]: ...
    
    # Listing methods
    async def list_threads(self, filter: ThreadFilter) -> list[ThreadInfo]: ...
    
    # Index management methods
    async def _update_thread_index(self, thread_id: str, action: str) -> None: ...
    async def _load_thread_index(self) -> dict[str, Any]: ...
```

---

## Performance Characteristics

### SQLiteDurability Performance

| Operation | Performance | Notes |
|-----------|-------------|-------|
| `create_thread()` | ~10-20ms | Single-threaded writes |
| `persist_thread()` | ~10-20ms | JSON serialization |
| `restore_thread()` | ~5-10ms | Fast read |
| `list_threads()` | ~50-100ms | Index scan |
| `delete_thread()` | ~10-20ms | Single-threaded writes |

### PostgreSQLDurability Performance

| Operation | Performance | Notes |
|-----------|-------------|-------|
| `create_thread()` | ~20-50ms | Connection pool overhead |
| `persist_thread()` | ~20-50ms | JSON serialization + network |
| `restore_thread()` | ~10-30ms | Network overhead |
| `list_threads()` | ~50-200ms | Index scan + network |
| `delete_thread()` | ~20-50ms | Connection pool overhead |

---

## Comparison Table

### Durability Backend Comparison

| Feature | SQLiteDurability | PostgreSQLDurability |
|---------|------------------|---------------------|
| Storage Type | SQLite database | PostgreSQL table |
| Async Operations | ✅ | ✅ |
| Connection Pooling | ❌ | ✅ |
| Concurrent Writes | ❌ (single-threaded) | ✅ |
| Production Use | ⚠️ (local/dev) | ✅ |
| External Dependencies | SQLite (built-in) | PostgreSQL, psycopg_pool |
| Setup Complexity | Low | Medium |
| Scalability | Limited | High |

---

## Error Handling

### Common Errors

```python
try:
    thread = await durability.create_thread(metadata)
except DurabilityBackendError as e:
    logger.error(f"Durability backend error: {e}")
    
    # Handle specific errors:
    if "connection_failed" in str(e):
        # Retry or fallback to SQLite
        durability = SQLiteDurability("~/.soothe/durability")
    
    elif "thread_exists" in str(e):
        # Use existing thread
        thread = await durability.restore_thread_info(thread_id)
    
    elif "storage_error" in str(e):
        # Check storage health
        await durability._store.health_check()
```

---

## Integration with SootheRunner

### Pre-stream Phase

```python
async def pre_stream_phase(self, thread_id: str):
    """Pre-stream processing."""
    
    # Create or resume thread
    if thread_id:
        # Resume existing thread
        thread_info = await self.durability.resume_thread(thread_id)
        state = await self.durability.restore_thread(thread_id)
    else:
        # Create new thread
        metadata = ThreadMetadata(
            goal=self.goal,
            workspace=self.workspace
        )
        thread_info = await self.durability.create_thread(metadata)
        state = {}
    
    return thread_info, state
```

### Post-stream Phase

```python
async def post_stream_phase(self, thread_id: str, state: dict[str, Any]):
    """Post-stream processing."""
    
    # Persist thread state
    await self.durability.persist_thread(thread_id, state)
    
    # Update thread status
    if state.get("completed"):
        await self.durability.complete_thread(thread_id)
    elif state.get("paused"):
        await self.durability.suspend_thread(thread_id)
```

---

## Testing

### Unit Testing

```python
import pytest

@pytest.mark.asyncio
async def test_sqlite_durability():
    """Test SQLite durability backend."""
    durability = SQLiteDurability(":memory:")  # In-memory SQLite
    
    # Test create thread
    metadata = ThreadMetadata(goal="test", workspace="/tmp")
    thread = await durability.create_thread(metadata)
    assert thread.thread_id is not None
    
    # Test persist state
    state = {"iteration": 1}
    await durability.persist_thread(thread.thread_id, state)
    
    # Test restore state
    restored = await durability.restore_thread(thread.thread_id)
    assert restored["iteration"] == 1
    
    # Test list threads
    threads = await durability.list_threads(ThreadFilter())
    assert len(threads) > 0
    
    # Test complete thread
    await durability.complete_thread(thread.thread_id)
    info = await durability.restore_thread_info(thread.thread_id)
    assert info.status == "completed"
```

---

## Configuration Examples

### Basic SQLite Configuration

```yaml
protocols:
  durability:
    enabled: true
    backend: sqlite
    persist_dir: ~/.soothe/durability
```

### Production PostgreSQL Configuration

```yaml
protocols:
  durability:
    enabled: true
    backend: postgresql
    
    # PostgreSQL connection
    dsn: postgresql://user:pass@host:5432/soothe
    pool_size: 10
    table_name: durability
    
    # Performance tuning
    connection_timeout: 30
    max_overflow: 5
```

---

## Persistence Integration

### Integration with PersistStore

Durability backends use `PersistStore` for storage:

```python
class BasePersistStoreDurability:
    def __init__(self, persist_store: AsyncPersistStore):
        self._store = persist_store
        
    async def _store_operation(self):
        # Key-value operations
        await self._store.save(key, value)
        value = await self._store.load(key)
        await self._store.delete(key)
```

**See**: [Persistence Backends](persistence-backends.md)

---

## Related Documentation

- **[Backends Overview](README.md)** - Backend layer introduction
- **[Persistence Backends](persistence-backends.md)** - PersistStore implementations
- **[Thread Management](../thread-management.md)** - Thread lifecycle
- **[SootheRunner](../core/runner.md)** - Runner integration
- **[RFC-001](../../specs/RFC-001-core-modules-architecture.md)** - Durability protocol spec

---

## API Reference

### SQLiteDurability Class

```python
class SQLiteDurability(BasePersistStoreDurability):
    """DurabilityProtocol implementation using SQLite."""
    
    def __init__(self, persist_dir: str) -> None: ...
```

### PostgreSQLDurability Class

```python
class PostgreSQLDurability(BasePersistStoreDurability):
    """DurabilityProtocol implementation using PostgreSQL."""
    
    def __init__(self, dsn: str, pool_size: int = 5) -> None: ...
```

### BasePersistStoreDurability Class

```python
class BasePersistStoreDurability:
    """Base implementation using AsyncPersistStore."""
    
    def __init__(self, persist_store: AsyncPersistStore) -> None: ...
    
    # All DurabilityProtocol methods
```

---

## See Also

- **[Durability Protocol](../architecture/protocols.md)** - Protocol definition
- **[Protocol Resolver](../core/resolver.md)** - Backend resolution
- **[Thread Management](../thread-management.md)** - Thread lifecycle