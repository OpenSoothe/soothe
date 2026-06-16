# DurabilityProtocol

**RFC**: 408  
**Module**: RFC-000 Module 5  
**Location**: `packages/soothe/src/soothe/protocols/durability.py`  
**Status**: Implemented  

## Overview

DurabilityProtocol defines the interface for **thread lifecycle management** in Soothe. It handles creation, resumption, suspension, and archiving of agent conversation threads, maintaining thread metadata and status across restarts and crashes.

**Note**: State persistence (checkpoints, artifacts) is handled separately by LangGraph's Checkpointer system and `RunArtifactStore` (RFC-0010).

## Purpose

- **Thread lifecycle**: Create, resume, suspend, archive threads
- **Metadata persistence**: Thread tags, labels, policy profiles
- **Status tracking**: active, suspended, archived states
- **Prefix matching**: Resume threads by partial ID
- **Thread filtering**: Query threads by status, tags, metadata

## Protocol Interface

```python
@runtime_checkable
class DurabilityProtocol(Protocol):
    """Protocol for thread lifecycle management.
    
    State persistence (checkpoints, artifacts) is handled by
    ``RunArtifactStore`` (RFC-0010).
    """

    async def create_thread(
        self,
        metadata: ThreadMetadata,
        thread_id: str | None = None,
    ) -> ThreadInfo:
        """Create a new thread with metadata.
        
        Args:
            metadata: Thread metadata.
            thread_id: Optional thread ID. If not provided, 
                       a new UUID is generated.
                       
        Returns:
            ThreadInfo for the created thread.
        """
        ...

    async def resume_thread(self, thread_id: str) -> ThreadInfo:
        """Resume a suspended thread.
        
        Supports prefix matching for thread IDs. If the provided
        thread_id is a prefix that matches one or more threads,
        the first match is resumed.
        
        Args:
            thread_id: Full thread ID or prefix.
            
        Returns:
            ThreadInfo for the resumed thread.
            
        Raises:
            KeyError: If thread not found.
        """
        ...

    async def suspend_thread(self, thread_id: str) -> ThreadInfo:
        """Suspend an active thread.
        
        Args:
            thread_id: The thread to suspend.
            
        Returns:
            ThreadInfo for the suspended thread.
            
        Raises:
            KeyError: If thread not found.
        """
        ...

    async def archive_thread(self, thread_id: str) -> ThreadInfo:
        """Archive a thread (permanent archive, no resumption).
        
        Args:
            thread_id: The thread to archive.
            
        Returns:
            ThreadInfo for the archived thread.
            
        Raises:
            KeyError: If thread not found.
        """
        ...

    async def get_thread(self, thread_id: str) -> ThreadInfo | None:
        """Retrieve thread info by ID (exact match only).
        
        Args:
            thread_id: The thread ID.
            
        Returns:
            ThreadInfo if found, None otherwise.
        """
        ...

    async def list_threads(
        self,
        filter: ThreadFilter | None = None,
    ) -> list[ThreadInfo]:
        """List threads matching filter criteria.
        
        Args:
            filter: Optional filter criteria.
            
        Returns:
            Matching threads ordered by updated_at descending.
        """
        ...

    async def update_thread_metadata(
        self,
        thread_id: str,
        metadata: ThreadMetadata,
    ) -> ThreadInfo:
        """Update thread metadata.
        
        Args:
            thread_id: The thread to update.
            metadata: New metadata to apply.
            
        Returns:
            Updated ThreadInfo.
            
        Raises:
            KeyError: If thread not found.
        """
        ...
```

## Data Models

### ThreadMetadata

```python
class ThreadMetadata(BaseModel):
    """Metadata associated with a thread.
    
    Args:
        tags: Categorical tags for filtering.
        plan_summary: Brief summary of the thread's plan (if any).
        policy_profile: Name of the active policy profile.
        labels: User-defined labels for organization (RFC-303).
        priority: Thread priority level (RFC-303).
        category: User-defined category (RFC-303).
        claude_sessions: Maps resolved workspace cwd to Claude Agent SDK
            session UUID for resumption (IG-202).
    """

    tags: list[str] = Field(default_factory=list)
    plan_summary: str | None = None
    policy_profile: str = "standard"
    # RFC-303: Enhanced metadata
    labels: list[str] = Field(default_factory=list)
    priority: Literal["low", "normal", "high"] = "normal"
    category: str | None = None
    claude_sessions: dict[str, str] = Field(default_factory=dict)
```

**Key Fields**:
- **tags**: System-level categorical tags (e.g., "autopilot", "interactive")
- **labels**: User-defined organization labels
- **priority**: Execution priority (low, normal, high)
- **policy_profile**: Security policy applied to thread

### ThreadInfo

```python
class ThreadInfo(BaseModel):
    """Full information about a thread.
    
    Args:
        thread_id: Unique thread identifier.
        status: Current lifecycle status.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        metadata: Associated metadata.
    """

    thread_id: str
    status: Literal["active", "suspended", "archived"]
    created_at: datetime
    updated_at: datetime
    metadata: ThreadMetadata = Field(default_factory=ThreadMetadata)
```

### ThreadFilter

```python
class ThreadFilter(BaseModel):
    """Filter criteria for listing threads.
    
    Supports both protocol-level filtering (durability backend) and
    manager-level in-memory filtering (ThreadContextManager).
    
    Args:
        status: Filter by status.
        tags: Filter by tags (items must have all specified tags).
        labels: Filter by user-defined labels.
        priority: Filter by priority level.
        category: Filter by category.
        created_after: Filter by creation time lower bound.
        created_before: Filter by creation time upper bound.
        updated_after: Filter by update time lower bound.
        updated_before: Filter by update time upper bound.
    """

    status: Literal["active", "suspended", "archived", "idle", "running", "error"] | None = None
    tags: list[str] | None = None
    labels: list[str] | None = None
    priority: Literal["low", "normal", "high"] | None = None
    category: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None
```

## Backend Implementations

### PostgreSQLDurability

**Status**: Production implementation  
**Location**: `packages/soothe/src/soothe/backends/durability/postgresql.py`  
**Dependencies**: PostgreSQL database (metadata database per RFC-802)

**Features**:
- Production-grade persistence
- Connection pooling
- Multi-database architecture (RFC-802)
- Thread prefix matching
- Async operations

**Configuration**:
```yaml
persistence:
  durability_backend: postgresql
  postgres_base_dsn: postgresql://user:pass@host:port
  postgres_databases:
    metadata: soothe_metadata  # Durability data
```

**Implementation**:
```python
class PostgreSQLDurability(BasePersistStoreDurability):
    """PostgreSQL durability backend using dedicated metadata database."""
    
    def __init__(self, persist_store: AsyncPersistStore) -> None:
        super().__init__(persist_store)
        # Uses AsyncPersistStore with PostgreSQL backend
```

### SQLiteDurability

**Status**: Development implementation  
**Location**: `packages/soothe/src/soothe/backends/durability/sqlite.py`  
**Dependencies**: SQLite database (metadata.db)

**Features**:
- Lightweight, zero-configuration
- Single-file storage
- Async operations via aiosqlite
- Suitable for development and testing

**Configuration**:
```yaml
persistence:
  durability_backend: sqlite
  metadata_sqlite_path: ~/.soothe/metadata.db
```

**Implementation**:
```python
class SQLiteDurability(BasePersistStoreDurability):
    """SQLite durability backend using metadata.db."""
    
    def __init__(self, db_path: str) -> None:
        persist_store = create_persist_store(
            backend="sqlite",
            db_path=db_path,
        )
        super().__init__(persist_store)
```

### BasePersistStoreDurability

**Location**: `packages/soothe/src/soothe/backends/durability/base.py`  
**Purpose**: Base implementation using `AsyncPersistStore`

```python
class BasePersistStoreDurability:
    """Base implementation using AsyncPersistStore.
    
    Provides thread lifecycle management. Subclasses only need to
    provide an AsyncPersistStore instance.
    """

    def __init__(self, persist_store: AsyncPersistStore) -> None:
        self._store = persist_store
        self._thread_index_key = "thread_index"
```

**Key Features**:
- Thread storage key: `thread:{thread_id}`
- Thread index tracking for listing
- Prefix matching support for resumption
- Automatic UUID generation if thread_id not provided

## Usage Patterns

### Thread Creation

```python
from soothe.protocols import ThreadMetadata, DurabilityProtocol

durability: DurabilityProtocol = resolve_durability(config)

# Create new thread with metadata
metadata = ThreadMetadata(
    tags=["autopilot", "goal-oriented"],
    labels=["project-alpha"],
    priority="high",
    policy_profile="standard"
)

thread_info = await durability.create_thread(metadata)
print(f"Thread created: {thread_info.thread_id}")
```

### Thread Resumption

```python
# Resume with exact ID
thread = await durability.resume_thread("thread_abc123")

# Resume with prefix (matches first result)
thread = await durability.resume_thread("abc")  # Matches thread_abc123

# Get thread without changing status
thread = await durability.get_thread("thread_abc123")
if thread:
    print(f"Thread status: {thread.status}")
```

### Thread Listing and Filtering

```python
from soothe.protocols import ThreadFilter

# List all active threads
filter = ThreadFilter(status="active")
active_threads = await durability.list_threads(filter)

# List high-priority threads with specific labels
filter = ThreadFilter(
    priority="high",
    labels=["critical"],
    updated_after=datetime.now() - timedelta(days=7)
)
recent_critical = await durability.list_threads(filter)

# List all threads (no filter)
all_threads = await durability.list_threads()
```

### Thread Lifecycle Management

```python
# Suspend thread (can be resumed later)
suspended = await durability.suspend_thread("thread_abc123")

# Archive thread (permanent, no resumption)
archived = await durability.archive_thread("thread_xyz789")

# Update metadata
new_metadata = ThreadMetadata(
    tags=["autopilot", "completed"],
    priority="low"
)
updated = await durability.update_thread_metadata(
    "thread_abc123",
    new_metadata
)
```

## Integration with Other Protocols

### Durability ↔ Checkpointer Integration

Durability and Checkpointer have separate responsibilities:

- **DurabilityProtocol**: Thread metadata and lifecycle
- **LangGraph Checkpointer**: Execution state and checkpoints

```
Thread Lifecycle (Durability):
  - Thread ID, status, metadata
  - ThreadFilter queries
  
Execution State (Checkpointer):
  - LangGraph checkpoint snapshots
  - Conversation history
  - Tool/subagent state
```

### Durability ↔ Memory Integration

Threads track source of memory items:

```python
# MemoryItem has source_thread field
memory_item = MemoryItem(
    content="Important finding",
    source_thread="thread_abc123",  # From ThreadInfo.thread_id
    ...
)
```

### Durability ↔ Policy Integration

Threads carry policy profile:

```python
# ThreadMetadata has policy_profile field
metadata = ThreadMetadata(
    policy_profile="readonly"  # Applied to all operations in thread
)
```

## Thread ID Generation

Thread IDs are UUID-based:

```python
# Auto-generated if not provided
thread = await durability.create_thread(metadata)
# thread.thread_id = "thread_abc123def456..."

# Custom ID for persistence
thread = await durability.create_thread(
    metadata,
    thread_id="thread_custom123"  # User-provided
)
```

**Prefix Matching**:
```python
# Resume by prefix
thread = await durability.resume_thread("abc")
# Matches thread_abc123def456...

# Multiple matches? Returns most recently updated
```

## Thread Status Flow

```
Thread Lifecycle States:

[Create] → active → [Suspend] → suspended → [Resume] → active
             ↓                           ↓
          [Archive]                   [Archive]
             ↓                           ↓
          archived                    archived (no resumption)
```

**States**:
- **active**: Currently executing or ready to execute
- **suspended**: Paused, can be resumed
- **archived**: Permanent archive, cannot resume
- **idle/running/error**: Additional status from ThreadFilter (for querying)

## Configuration

### Durability Backend Settings

```yaml
# config/config.template.yml
persistence:
  durability_backend: postgresql  # or sqlite
  
  # PostgreSQL configuration
  postgres_base_dsn: postgresql://user:pass@host:port
  postgres_databases:
    metadata: soothe_metadata  # Durability data
    
  # SQLite configuration
  metadata_sqlite_path: ~/.soothe/metadata.db
```

### Resolution

```python
from soothe.core.resolver import resolve_durability

# Resolve durability protocol from config
durability = resolve_durability(config)

# Returns: DurabilityProtocol implementation
# Backend: PostgreSQLDurability or SQLiteDurability
```

## Testing

### Unit Tests

**Location**: `packages/soothe/tests/unit/backends/durability/test_sqlite_durability.py`

Tests verify:
- Thread creation with metadata
- Thread resumption (exact and prefix matching)
- Thread suspension and archiving
- Thread listing and filtering
- Metadata updates

### Integration Tests

Durability integration tests verify:
- PostgreSQL connection handling
- Multi-database architecture
- Thread persistence across restarts
- Concurrent thread operations

## Design Rationale

### Why Separate Durability from Checkpointer?

**RFC-000 Principle 5**: Durable by default.

- **Durability**: Thread-level metadata and lifecycle
- **Checkpointer**: Execution-level state and snapshots
- Different data structures, different query patterns

### Why Prefix Matching?

Convenience for thread resumption:
- Full UUIDs are hard to remember/type
- Prefix matching enables easy resumption
- Returns most recently updated if multiple matches

### Why Three Status States?

- **active**: Execution-ready
- **suspended**: Pause for later resumption
- **archived**: Permanent storage, no resumption

Separate states for different lifecycle phases.

## Specification Reference

- **RFC-306**: Durability Protocol Architecture
- **RFC-802**: Persistence Architecture Refactor (multi-database)
- **RFC-452**: Unified Thread Management
- **RFC-000**: System Conceptual Design (protocol philosophy)

## Related Documentation

- [Persistence Protocol](persistence.md)
- [Memory Protocol](memory.md)
- [Policy Protocol](policy.md)
- [Backend Implementation Guide](../backends.md)