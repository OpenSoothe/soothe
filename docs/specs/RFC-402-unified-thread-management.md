# RFC-402: Unified Thread Management Architecture

**RFC**: 402
**Title**: Unified Thread Management Architecture
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-03-22
**Dependencies**: RFC-000, RFC-001, RFC-200, RFC-400, RFC-101
**Implements**: Thread lifecycle management, multi-threading support, unified transport APIs

## Abstract

This RFC defines a unified thread management architecture for Soothe that consolidates thread lifecycle operations across all transport layers (WebSocket, HTTP REST), supports concurrent multi-thread execution with isolation guarantees, and provides comprehensive thread metadata and statistics. The design introduces a ThreadContextManager component that coordinates all thread-related storage systems (DurabilityProtocol, LangGraph checkpointer, ThreadLogger, RunArtifactStore) and exposes a consistent API for thread CRUD operations across all client interfaces.

## Motivation

### Problem: Fragmented Thread Management

The current thread management system has several critical issues:

1. **CLI Duplication**: `soothe thread continue --thread-id <id>` duplicates functionality provided by `soothe thread continue <id>`, creating user confusion and maintenance burden.

2. **Transport Limitations**: Thread operations primarily work via WebSocket. HTTP REST endpoints defined in RFC-101 are unimplemented placeholders, preventing web UIs and REST clients from managing threads.

3. **Protocol Gaps**: The daemon protocol (RFC-400) lacks dedicated thread management messages. Thread operations require slash commands or are limited to `resume_thread`/`new_thread` primitives.

4. **Single-Threaded Execution**: The daemon maintains a single active thread (`SootheRunner.current_thread_id`). Multiple clients cannot execute queries in different threads simultaneously.

5. **Storage Fragmentation**: Thread data is scattered across four independent systems:
   - DurabilityProtocol (metadata)
   - LangGraph checkpointer (chat history)
   - ThreadLogger (conversation logs)
   - RunArtifactStore (artifacts)

   No unified interface coordinates these systems.

### Problem: Limited Thread Metadata

Current `ThreadInfo` only captures basic metadata (status, timestamps, tags). Missing capabilities:

- **No execution statistics**: Message count, artifact count, token usage, cost tracking
- **No organization tools**: Labels, categories, priority levels
- **No execution context**: Current goal, current step, iteration number for running threads
- **No search/filter**: Cannot filter threads by tags, date range, or custom criteria
- **No bulk operations**: Cannot archive or delete multiple threads at once

### Design Goals

1. **Unified API**: Consistent thread operations across WebSocket and HTTP REST
2. **Multi-threading**: Concurrent thread execution with isolation guarantees
3. **Rich metadata**: Comprehensive thread statistics and organization tools
4. **Single source of truth**: ThreadContextManager coordinates all storage systems
5. **Transport agnostic**: Protocol-level thread messages, not just slash commands
6. **Backward compatible**: Existing workflows continue without changes

### Non-Goals

- **Authentication/authorization**: Handled by reverse proxy (RFC-400)
- **Thread collaboration**: Multi-user thread sharing not in scope
- **Thread templates**: Pre-configured thread setups deferred to future RFC

## Guiding Principles

### Principle 1: Single Coordinator

All thread operations flow through ThreadContextManager, which coordinates with DurabilityProtocol, LangGraph checkpointer, ThreadLogger, and RunArtifactStore. No direct manipulation of thread storage.

### Principle 2: Transport Independence

Thread operations use the same API whether via WebSocket or HTTP REST. The protocol layer translates transport-specific requests to ThreadContextManager calls.

### Principle 3: Isolation by Default

Each thread executes in isolation with separate LangGraph config, isolated context/memory namespaces, and independent artifact directories. No state leakage between threads.

### Principle 4: Statistics on Demand

Thread statistics are calculated lazily on request, not stored permanently. This avoids stale data and synchronization overhead.

### Principle 5: Progressive Enhancement

New thread features (labels, categories, priority) are optional additions to existing metadata. Threads created before RFC-402 continue working with default values.

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Client Layer                            │
│                                                              │
│  CLI Commands    WebSocket    HTTP REST                      │
│  thread list     thread_list  GET /threads                   │
│  thread continue thread_get   POST /threads                  │
│  thread stats    ...          ...                            │
│  thread tag      ...                                         │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  Protocol Layer (RFC-400)                   │
│                                                              │
│  Protocol message validation and routing                     │
│  thread_list, thread_create, thread_get, ...                │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              ThreadContextManager (NEW)                      │
│                                                              │
│  Unified coordinator for thread lifecycle                    │
│  - create_thread(), resume_thread()                          │
│  - get_thread(), list_threads()                              │
│  - archive_thread(), delete_thread()                         │
│  - get_thread_messages(), get_thread_artifacts()             │
│  - get_thread_stats()                                        │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   Storage Layer                              │
│                                                              │
│  ┌───────────────┐ ┌──────────────┐ ┌──────────────┐      │
│  │ Durability    │ │ LangGraph    │ │ ThreadLogger │      │
│  │ Protocol      │ │ Checkpointer │ │              │      │
│  │ (metadata)    │ │ (history)    │ │ (logs)       │      │
│  └───────────────┘ └──────────────┘ └──────────────┘      │
│                                                              │
│  ┌───────────────┐                                         │
│  │ RunArtifact   │                                         │
│  │ Store         │                                         │
│  │ (artifacts)   │                                         │
│  └───────────────┘                                         │
└─────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

#### ThreadContextManager

**Purpose**: Centralized coordinator for all thread lifecycle operations.

**Responsibilities**:
- Create and initialize new threads across all storage systems
- Resume existing threads with full history loading
- Archive threads with optional memory consolidation
- Delete threads with complete cleanup across all storage systems
- List threads with filtering and pagination
- Calculate thread statistics on demand
- Coordinate thread messages retrieval from ThreadLogger
- Manage thread artifacts enumeration

**Dependencies**:
- DurabilityProtocol (thread metadata)
- SootheConfig (configuration)
- ThreadLogger (conversation logs)
- RunArtifactStore (artifacts)

#### ThreadExecutor

**Purpose**: Manage concurrent thread execution with isolation.

**Responsibilities**:
- Execute queries in isolated thread contexts
- Enforce API rate limits across threads
- Manage thread execution state
- Handle concurrent execution limits
- Prevent resource contention

#### Thread Storage Systems (Existing)

1. **DurabilityProtocol**: Thread metadata (status, timestamps, tags, labels, priority, category)
2. **LangGraph Checkpointer**: Full chat history and execution state
3. **ThreadLogger**: Conversation event logs in JSONL format
4. **RunArtifactStore**: Thread artifacts (files, reports, checkpoints)

### Data Flow

#### Thread Creation Flow

```
Client → Protocol Layer → ThreadContextManager.create_thread()
  → DurabilityProtocol.create_thread() (metadata)
  → ThreadLogger initialization (empty log file)
  → Return ThreadInfo to client
```

#### Thread Resume Flow

```
Client → Protocol Layer → ThreadContextManager.resume_thread(thread_id)
  → DurabilityProtocol.resume_thread() (load metadata)
  → LangGraph checkpointer loads history automatically (via thread_id config)
  → ThreadLogger continues appending to existing log
  → ContextProtocol.restore(thread_id) (load context entries)
  → Return ThreadInfo with updated timestamp
```

#### Thread Execution Flow

```
Client → ThreadExecutor.execute_thread(thread_id, user_input)
  → runner.set_current_thread_id(thread_id)
  → ThreadLogger instance for thread
  → APIRateLimiter.acquire()
  → runner.astream(user_input, thread_id=thread_id)
  → Stream chunks logged to ThreadLogger
  → Yield chunks to client
  → Update thread timestamp on completion
```

### Thread Lifecycle

Thread states: `idle` → `running` → `idle` (cycle) → `archived` → `deleted` (terminal). The `suspended` state is reserved for future features.

## Abstract Schemas

### Enhanced Thread Metadata

```python
class ThreadMetadata(BaseModel):
    """Enhanced thread metadata with organization tools."""
    tags: list[str] = Field(default_factory=list)
    plan_summary: str | None = None
    policy_profile: str = "standard"
    # RFC-402 additions:
    labels: list[str] = Field(default_factory=list)
    priority: Literal["low", "normal", "high"] = "normal"
    category: str | None = None
```

### Thread Statistics and Info

```python
class ThreadStats(BaseModel):
    """Thread execution statistics (calculated on demand)."""
    message_count: int = 0
    event_count: int = 0
    artifact_count: int = 0
    total_tokens_used: int = 0
    total_cost: float = 0.0
    avg_response_time_ms: float = 0.0
    error_count: int = 0

class EnhancedThreadInfo(BaseModel):
    """Complete thread information with statistics."""
    thread_id: str
    status: Literal["idle", "running", "suspended", "archived", "error"]
    created_at: datetime
    updated_at: datetime
    metadata: ThreadMetadata
    stats: ThreadStats = Field(default_factory=ThreadStats)
    execution_context: ExecutionContext | None = None

class ThreadFilter(BaseModel):
    """Thread filtering criteria."""
    status: str | None = None
    tags: list[str] | None = None
    labels: list[str] | None = None
    priority: str | None = None
    created_after: datetime | None = None
    updated_after: datetime | None = None
```

## Protocol Specification

### ThreadContextManager Protocol

```python
class ThreadContextManagerProtocol(Protocol):
    """Central coordinator for thread lifecycle operations."""

    async def create_thread(self, initial_message: str | None = None,
                           metadata: ThreadMetadata | None = None) -> ThreadInfo: ...
    async def resume_thread(self, thread_id: str, load_history: bool = True) -> ThreadInfo: ...
    async def get_thread(self, thread_id: str) -> EnhancedThreadInfo: ...
    async def list_threads(self, filter: ThreadFilter | None = None,
                          include_stats: bool = False) -> list[EnhancedThreadInfo]: ...
    async def update_thread_metadata(self, thread_id: str, metadata: ThreadMetadata) -> None: ...
    async def archive_thread(self, thread_id: str) -> None: ...
    async def delete_thread(self, thread_id: str) -> None: ...
    async def get_thread_messages(self, thread_id: str, limit: int = 100,
                                  offset: int = 0) -> list[ThreadMessage]: ...
    async def get_thread_artifacts(self, thread_id: str) -> list[ArtifactEntry]: ...
    async def get_thread_stats(self, thread_id: str) -> ThreadStats: ...
```

### Daemon Protocol Extensions (RFC-400)

Thread management operations are exposed through daemon protocol messages:

**Client → Server**: `thread_list`, `thread_create`, `thread_get`, `thread_archive`, `thread_delete`, `thread_messages`, `thread_artifacts`

**Server → Client**: `thread_list_response`, `thread_get_response`, `thread_created`, `thread_operation_ack`

These messages map directly to ThreadContextManager method calls, enabling WebSocket clients to perform thread operations.

### HTTP REST API

Thread management REST endpoints are defined in the REST API specification (RFC-101). The ThreadContextManager serves as the backend implementation for these endpoints.

## Multi-Threading Architecture

### Thread Isolation Model

Each thread executes in complete isolation:

1. **Separate LangGraph Config**: Each thread uses its own `thread_id` in checkpointer config
2. **Isolated Namespaces**: Context and memory use thread-specific keys
3. **Independent Artifacts**: Each thread has its own `~/.soothe/runs/{thread_id}/` directory
4. **Separate Loggers**: ThreadLogger instances are per-thread

### ThreadExecutor Design

```python
class ThreadExecutor:
    """Manages concurrent thread execution."""

    def __init__(
        self,
        runner: SootheRunner,
        max_concurrent_threads: int = 4,
    ) -> None:
        self._runner = runner
        self._max_concurrent = max_concurrent_threads
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._rate_limiter = APIRateLimiter()

    async def execute_thread(
        self,
        thread_id: str,
        user_input: str,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamChunk]:
        """Execute query in isolated thread context."""
        # 1. Set thread context
        self._runner.set_current_thread_id(thread_id)

        # 2. Create isolated logger
        logger = ThreadLogger(thread_id=thread_id)

        # 3. Acquire rate limit permit
        async with self._rate_limiter.acquire():
            # 4. Execute in isolated context
            async for chunk in self._runner.astream(
                user_input,
                thread_id=thread_id,
                **kwargs,
            ):
                # 5. Log to thread-specific logger
                logger.log(chunk.namespace, chunk.mode, chunk.data)
                yield chunk
```

### API Rate Limiting

```python
class APIRateLimiter:
    """Rate limiter for API calls across all threads."""

    def __init__(
        self,
        requests_per_minute: int = 60,
        tokens_per_minute: int = 90000,
    ) -> None:
        self._rpm_limit = requests_per_minute
        self._tpm_limit = tokens_per_minute
        self._request_semaphore = asyncio.Semaphore(requests_per_minute // 60)

    @asynccontextmanager
    async def acquire(self, estimated_tokens: int = 1000):
        """Acquire rate limit permit."""
        async with self._request_semaphore:
            yield
```

## CLI Commands

The `soothe thread continue` command requires a running daemon for thread continuation. The deprecated `soothe daemon attach --thread-id` has been replaced by `soothe thread continue`, which now exclusively operates via the daemon. See user documentation for complete CLI reference.

## Implementation Notes

Thread statistics are calculated lazily on demand from ThreadLogger records and artifact directories. Existing threads automatically receive default values for new metadata fields. Old protocol messages (`resume_thread`, `new_thread`) remain supported for backward compatibility.

## Migration Path

Implementation phases are detailed in the associated implementation guide. The migration maintains backward compatibility while progressively adding ThreadContextManager, daemon protocol extensions, REST API implementation, and multi-threading support.

## Success Metrics

1. **API Consistency**: Thread operations work identically across all transports
2. **Concurrent Execution**: Multiple threads can execute simultaneously without interference
3. **CLI Simplification**: Users no longer confused by `server attach` vs `thread continue`
4. **HTTP REST Functionality**: Web UIs can manage threads via REST API
5. **Performance**: Statistics calculation completes in <500ms for threads with <1000 messages

## References

- RFC-000: System Conceptual Design
- RFC-001: Core Modules Architecture Design
- RFC-400: Unified Daemon Communication Protocol
- RFC-101: HTTP REST API Specification
- LangGraph Checkpointer Documentation
- ThreadLogger Implementation

---

*This RFC establishes the foundation for unified thread management while maintaining complete backward compatibility with existing systems.*