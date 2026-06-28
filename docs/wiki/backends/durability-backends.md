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
    async def suspend_thread(self, thread_id: str) -> None: ...
    async def archive_thread(self, thread_id: str) -> None: ...
    async def update_thread_metadata(self, thread_id: str, metadata: dict[str, Any] | ThreadMetadata) -> None: ...
    async def get_thread(self, thread_id: str) -> ThreadInfo | None: ...
    async def list_threads(self, thread_filter: ThreadFilter | None = None) -> list[ThreadInfo]: ...
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
   └─ ThreadFilter
```

#### Implementation

```python
class SQLiteDurability(BasePersistStoreDurability):
    """DurabilityProtocol implementation using SQLite."""

    def __init__(
        self,
        persist_store: AsyncPersistStore | None = None,
        db_path: str | None = None,
    ):
        """Initialize SQLite durability backend."""

        if persist_store is None:
            from soothe_sdk.client.config import SOOTHE_DATA_DIR
            actual_path = db_path or str(Path(SOOTHE_DATA_DIR) / "metadata.db")
            persist_store = SQLitePersistStore(actual_path, namespace="durability")
        super().__init__(persist_store)
    
    # Inherits all methods from BasePersistStoreDurability:
    # - create_thread()
    # - resume_thread()
    # - suspend_thread()
    # - archive_thread()
    # - update_thread_metadata()
    # - get_thread()
    # - list_threads()
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
    tags=["analysis", "code"],
    plan_summary="Analyze codebase structure",
    priority="normal",
)
thread = await durability.create_thread(metadata)

# Get thread
info = await durability.get_thread(thread.thread_id)

# Suspend thread
await durability.suspend_thread(thread.thread_id)

# Resume thread
resumed = await durability.resume_thread(thread.thread_id)

# List threads
thread_filter = ThreadFilter(status="active", tags=["analysis"])
threads = await durability.list_threads(thread_filter)

# Update metadata
await durability.update_thread_metadata(thread.thread_id, {"tags": ["analysis", "complete"]})

# Archive thread
await durability.archive_thread(thread.thread_id)
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

    def __init__(self, persist_store: AsyncPersistStore):
        """Initialize PostgreSQL durability backend."""

        # Initialize base class with PostgreSQL persist store
        super().__init__(persist_store)

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

# Initialize backend (requires an AsyncPersistStore instance)
from soothe.backends.persistence.postgres_store import PostgreSQLPersistStore
persist_store = PostgreSQLPersistStore(dsn="postgresql://localhost/soothe")
durability = PostgreSQLDurability(persist_store)

# All operations same as SQLiteDurability
thread = await durability.create_thread(metadata)
await durability.suspend_thread(thread.thread_id)
threads = await durability.list_threads(thread_filter)
```

---

## Durability Data Model

### ThreadInfo

Thread state container:

```python
class ThreadInfo(BaseModel):
    """Thread information."""

    thread_id: str             # Unique thread ID
    status: Literal["active", "suspended", "archived"]  # Thread status
    created_at: datetime       # Creation timestamp
    updated_at: datetime       # Last update timestamp
    metadata: ThreadMetadata   # Thread metadata
```

### ThreadMetadata

Thread metadata:

```python
class ThreadMetadata(BaseModel):
    """Thread metadata."""

    tags: list[str] = []           # Categorical tags for filtering
    plan_summary: str | None       # Brief summary of the thread's plan
    policy_profile: str = "standard"  # Name of the active policy profile
    labels: list[str] = []         # User-defined labels for organization
    priority: Literal["low", "normal", "high"] = "normal"  # Thread priority
    category: str | None           # User-defined category
    claude_sessions: dict[str, str] = {}  # Workspace cwd → Claude session UUID
```

### ThreadFilter

Thread listing filter:

```python
class ThreadFilter(BaseModel):
    """Thread filter criteria."""

    # Protocol-level fields (used by durability backend)
    status: Literal["active", "suspended", "archived", "idle", "running", "error"] | None = None
    tags: list[str] | None        # Filter by tags (must have all specified tags)
    created_after: datetime | None  # Filter by creation time lower bound
    created_before: datetime | None  # Filter by creation time upper bound

    # Manager-level fields (used by ThreadContextManager in-memory)
    labels: list[str] | None     # Filter by user-defined labels
    priority: Literal["low", "normal", "high"] | None  # Filter by priority
    category: str | None         # Filter by category
    updated_after: datetime | None  # Filter by update time lower bound
    updated_before: datetime | None  # Filter by update time upper bound
```

### Thread Status

Thread status uses string literals (not a separate enum):

- `"active"` — Currently running
- `"suspended"` — Paused execution
- `"archived"` — Archived (triggers memory consolidation)

---

## Thread Lifecycle

### Thread Creation

```python
async def create_thread(self, metadata: ThreadMetadata, thread_id: str | None = None) -> ThreadInfo:
    """Create a new thread."""

    # Generate thread ID
    thread_id = thread_id or generate_thread_id()

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

### Thread Lifecycle Transitions

```python
async def suspend_thread(self, thread_id: str) -> None:
    """Suspend an active thread, persisting its state."""
    data = await self._store.load(f"thread:{thread_id}")
    if data is None:
        return
    info = ThreadInfo.model_validate(data)
    info = info.model_copy(update={"status": "suspended", "updated_at": datetime.now(tz=UTC)})
    await self._store.save(f"thread:{thread_id}", info.model_dump(mode="json"))

async def archive_thread(self, thread_id: str) -> None:
    """Archive a thread. Triggers memory consolidation."""
    data = await self._store.load(f"thread:{thread_id}")
    if data is None:
        return
    info = ThreadInfo.model_validate(data)
    info = info.model_copy(update={"status": "archived", "updated_at": datetime.now(tz=UTC)})
    await self._store.save(f"thread:{thread_id}", info.model_dump(mode="json"))

async def resume_thread(self, thread_id: str) -> ThreadInfo:
    """Resume a suspended thread. Supports prefix matching."""
    data = await self._store.load(f"thread:{thread_id}")
    if data is not None:
        info = ThreadInfo.model_validate(data)
        info = info.model_copy(update={"status": "active", "updated_at": datetime.now(tz=UTC)})
        await self._store.save(f"thread:{thread_id}", info.model_dump(mode="json"))
        return info
    # Try prefix matching ...
```

### Thread Listing

```python
async def list_threads(self, thread_filter: ThreadFilter | None = None) -> list[ThreadInfo]:
    """List threads matching filter."""
    index_data = await self._store.load(self._thread_index_key)
    thread_ids = index_data if isinstance(index_data, list) else []

    results = []
    for tid in thread_ids:
        data = await self._store.load(f"thread:{tid}")
        if data:
            results.append(ThreadInfo.model_validate(data))

    if thread_filter is None:
        return results

    # Apply filters
    if thread_filter.status:
        results = [t for t in results if t.status == thread_filter.status]
    if thread_filter.tags:
        tag_set = set(thread_filter.tags)
        results = [t for t in results if tag_set.issubset(set(t.metadata.tags))]
    if thread_filter.created_after:
        results = [t for t in results if t.created_at >= thread_filter.created_after]
    if thread_filter.created_before:
        results = [t for t in results if t.created_at <= thread_filter.created_before]

    return results
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
    async def create_thread(self, metadata: ThreadMetadata, thread_id: str | None = None) -> ThreadInfo: ...
    async def resume_thread(self, thread_id: str) -> ThreadInfo: ...
    async def suspend_thread(self, thread_id: str) -> None: ...
    async def archive_thread(self, thread_id: str) -> None: ...
    async def get_thread(self, thread_id: str) -> ThreadInfo | None: ...
    async def update_thread_metadata(self, thread_id: str, metadata: dict[str, Any] | ThreadMetadata) -> None: ...

    # Listing methods
    async def list_threads(self, thread_filter: ThreadFilter | None = None) -> list[ThreadInfo]: ...

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
| `get_thread()` | ~5-10ms | Fast read |
| `suspend_thread()` | ~10-20ms | JSON serialization |
| `archive_thread()` | ~10-20ms | JSON serialization |
| `list_threads()` | ~50-100ms | Index scan |
| `update_thread_metadata()` | ~10-20ms | Merge + save |

### PostgreSQLDurability Performance

| Operation | Performance | Notes |
|-----------|-------------|-------|
| `create_thread()` | ~20-50ms | Connection pool overhead |
| `get_thread()` | ~10-30ms | Network overhead |
| `suspend_thread()` | ~20-50ms | JSON serialization + network |
| `archive_thread()` | ~20-50ms | JSON serialization + network |
| `list_threads()` | ~50-200ms | Index scan + network |
| `update_thread_metadata()` | ~20-50ms | Merge + save + network |

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
        thread = await durability.get_thread(thread_id)
    
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
    else:
        # Create new thread
        metadata = ThreadMetadata(
            tags=[],
            plan_summary=self.goal,
        )
        thread_info = await self.durability.create_thread(metadata)

    return thread_info
```

### Post-stream Phase

```python
async def post_stream_phase(self, thread_id: str):
    """Post-stream processing."""

    # Update thread status
    if state.get("paused"):
        await self.durability.suspend_thread(thread_id)
    else:
        await self.durability.archive_thread(thread_id)
```

---

## Testing

### Unit Testing

```python
import pytest

@pytest.mark.asyncio
async def test_sqlite_durability():
    """Test SQLite durability backend."""
    durability = SQLiteDurability(persist_store=None, db_path=":memory:")

    # Test create thread
    metadata = ThreadMetadata(tags=["test"], plan_summary="test")
    thread = await durability.create_thread(metadata)
    assert thread.thread_id is not None

    # Test get thread
    info = await durability.get_thread(thread.thread_id)
    assert info is not None

    # Test suspend
    await durability.suspend_thread(thread.thread_id)
    info = await durability.get_thread(thread.thread_id)
    assert info.status == "suspended"

    # Test resume
    resumed = await durability.resume_thread(thread.thread_id)
    assert resumed.status == "active"

    # Test list threads
    threads = await durability.list_threads(ThreadFilter())
    assert len(threads) > 0

    # Test archive
    await durability.archive_thread(thread.thread_id)
    info = await durability.get_thread(thread.thread_id)
    assert info.status == "archived"
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

    def __init__(
        self,
        persist_store: AsyncPersistStore | None = None,
        db_path: str | None = None,
    ) -> None: ...
```

### PostgreSQLDurability Class

```python
class PostgreSQLDurability(BasePersistStoreDurability):
    """DurabilityProtocol implementation using PostgreSQL."""

    def __init__(self, persist_store: AsyncPersistStore) -> None: ...
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