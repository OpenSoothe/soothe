---
name: IG-054 Fix Concurrent Query Race Condition
status: completed
created: 2026-04-20
---

# IG-054: Fix Concurrent Query Race Condition

## Problem

Critical race condition in single-threaded query path causing capacity check to incorrectly block concurrent queries when only one query is starting.

### Race Window

```python
# Single-threaded path (buggy):
Line 104: _active_threads[thread_id] = None  # Placeholder under lock
Line 332: _active_threads.pop(thread_id)     # Removed in finally
Line 338: _active_threads[thread_id] = task  # Set AFTER finally

# Window between 104-338:
# - Dict has None placeholder counting toward capacity
# - Capacity check sees active thread
# - No actual task exists to cancel/monitor
# - Concurrent query blocked with DAEMON_BUSY
```

### Comparison with Multithreaded Path

```python
# Multithreaded path (correct):
Line 519: _active_threads[thread_id] = task  # Set immediately
Line 514: _active_threads.pop(thread_id)     # Remove in finally
```

## Root Cause

Placeholder pattern in single-threaded path creates race window:
1. Placeholder set under lock (line 104)
2. Placeholder removed in finally (line 332)
3. Actual task set AFTER finally (line 338)

Between steps 2-3, dict is empty but capacity check already counted placeholder.

## Fix Strategy

Align single-threaded path with multithreaded pattern:

1. **Remove placeholder pattern** (lines 100-107)
2. **Set task immediately** after creating it
3. **Remove in finally** (already correct at line 332)

### Implementation Steps

1. Remove placeholder assignment under lock (lines 100-107)
2. Move task creation before _active_threads assignment
3. Set _active_threads[thread_id] = task immediately
4. Keep finally cleanup (line 332)

## Thread Isolation Analysis

### Current Design (Multi-layer Isolation)

**Goal**: Isolate threads from different clients to prevent cross-contamination.

**Status**: RFC-209 executor thread isolation is **deprecated** (superseded by RFC-207). Current design uses simpler asyncio.Task-based isolation.

### Thread Isolation Layers

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: Client Session Ownership                       │
│  - ClientSessionManager: client_id ↔ thread_id          │
│  - Ownership claim/release lifecycle                     │
│  - Auto-cancel on disconnect (unless detach requested)  │
│  - Prevents cross-client thread access                   │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Layer 2: Thread State Registry                          │
│  - ThreadStateRegistry: thread_id → ThreadState         │
│  - Per-thread workspace, logger, query state            │
│  - Draft thread isolation before persistence            │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Layer 3: Workspace Isolation                            │
│  - Per-thread workspace paths                            │
│  - Filesystem context scoped to thread                   │
│  - FrameworkFilesystem.set_current_workspace()          │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Layer 4: Durability Checkpoint Isolation               │
│  - DurabilityProtocol: thread_id → checkpoint state     │
│  - LangGraph checkpointer: atomic state updates         │
│  - Message queue per thread (FIFO ordering)             │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Layer 5: Event Bus Subscription Isolation              │
│  - EventBus: topic-based routing (thread:{id})          │
│  - Events broadcast only to subscribed clients           │
│  - Verbosity filtering per client session                │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Layer 6: Execution Task Isolation                       │
│  - _active_threads: thread_id → asyncio.Task            │
│  - Each query runs in isolated asyncio.Task             │
│  - Concurrent capacity enforcement                       │
└─────────────────────────────────────────────────────────┘
```

### Isolation Guarantees

#### 1. Ownership Isolation (ClientSessionManager)
```python
# Claim: client owns thread during query execution
await session_manager.claim_thread_ownership(client_id, thread_id)

# Release: ownership released after query completes
await session_manager.release_thread_ownership(client_id)

# Auto-cancel: thread cancelled if client disconnects without detach
# (Implemented in ClientSessionManager.remove_session)
```

**Key properties**:
- Only one client can own a thread at a time
- Ownership prevents accidental thread cancellation by other clients
- Detach mode allows query to continue after disconnect

#### 2. State Registry Isolation (ThreadStateRegistry)
```python
# Per-thread state tracking
thread_state = ThreadState(
    thread_id=thread_id,
    workspace=Path(...),       # Isolated workspace
    thread_logger=ThreadLogger(...),  # Isolated logger
    is_draft=bool,             # Draft thread isolation
    query_running=bool,        # Runtime state
)
```

**Key properties**:
- Each thread has isolated workspace path
- ThreadLogger is per-thread (no cross-contamination)
- Draft threads isolated before persistence

#### 3. Workspace Isolation
```python
# Per-thread workspace context
workspace = resolve_workspace_for_stream(
    thread_workspace=registry.get_workspace(thread_id),
    installation_default=daemon_workspace,
    config_workspace_dir=config.workspace_dir,
)

# FrameworkFilesystem scoped to workspace
FrameworkFilesystem.set_current_workspace(workspace)
```

**Key properties**:
- File operations scoped to thread workspace
- No cross-thread file access
- Workspace path resolved from registry/config

#### 4. Checkpoint Isolation (DurabilityProtocol)
```python
# LangGraph checkpointer: atomic state updates
checkpointer = AsyncSqliteSaver(...)  # or AsyncPostgresSaver

# Thread-scoped checkpoint state
state = await checkpointer.aget(thread_id)
await checkpointer.aput(thread_id, checkpoint)

# Message queue per thread (FIFO ordering)
messages = state.get("messages", [])
```

**Key properties**:
- Atomic database transactions prevent concurrent update conflicts
- Message queue maintains FIFO ordering per thread
- ToolMessage separation prevents result mixing
- No shared mutable state between threads

#### 5. Event Bus Isolation
```python
# Topic-based routing: thread:{id}
await event_bus.subscribe(f"thread:{thread_id}", client_queue)

# Events broadcast only to subscribed clients
await event_bus.publish(f"thread:{thread_id}", event)

# Verbosity filtering per client
if should_show(event_meta.verbosity, client_session.verbosity):
    await transport.send(event)
```

**Key properties**:
- Events routed to subscribed clients only
- No cross-thread event delivery
- Per-client verbosity filtering

#### 6. Execution Task Isolation (Fixed in IG-054)
```python
# Before (buggy):
d._active_threads[thread_id] = None  # Placeholder
# ... finally removes placeholder ...
d._active_threads[thread_id] = task  # Set after finally

# After (fixed):
task = asyncio.create_task(_run_stream())
d._active_threads[thread_id] = task  # Set immediately
await task
# ... finally removes task ...
```

**Key properties**:
- Each query runs in isolated asyncio.Task
- Task set immediately after creation (no race)
- Concurrent capacity enforcement: `len(_active_threads) >= max_concurrent`
- Task cancellation targets specific thread

### ThreadExecutor Design (Deprecated RFC-209)

**Status**: RFC-209 executor thread isolation is **deprecated**.

**Location**: `core/thread/executor.py`

**Original design** (no longer recommended):
- ThreadExecutor wraps runner.astream in rate-limited context
- APIRateLimiter controls concurrent API calls
- Manual thread context management

**Current best practice** (RFC-207):
- Trust langgraph's atomic state management
- Use asyncio.Task isolation directly
- Task tool handles subagent isolation automatically
- No manual thread ID generation or merging

### Key Insight: Isolation is Layered

Thread isolation is **NOT** just executor-level (RFC-209 was wrong).

True isolation spans **6 layers**:
1. Client ownership (SessionManager)
2. Thread state registry (ThreadStateRegistry)
3. Workspace filesystem context
4. Checkpoint durability (LangGraph checkpointer)
5. Event bus routing
6. Execution task isolation

Each layer provides specific isolation guarantees.

### RFC-209 vs RFC-207

**RFC-209** (deprecated):
- Tried to isolate at executor level only
- Manual thread ID generation/merging
- Redundant isolation (langgraph already handles it)

**RFC-207** (current):
- Trusts langgraph atomic state updates
- Simplifies executor to pure orchestration
- Task tool handles subagent isolation automatically

### Isolation Test Scenarios

1. **Concurrent file operations**: Two threads writing to different files in same workspace
2. **Cross-client access**: Client A tries to cancel Client B's thread (blocked by ownership)
3. **Disconnect auto-cancel**: Client disconnects without detach, thread auto-cancelled
4. **Event routing**: Thread A events don't appear in Thread B client's TUI
5. **Workspace isolation**: Thread A cannot access Thread B's workspace files
6. **Capacity enforcement**: Concurrent query limit blocks at capacity accurately

## Testing Strategy

1. **Unit test**: Verify no placeholder in _active_threads during single query
2. **Integration test**: Verify concurrent queries don't hang at capacity check
3. **Race test**: Verify capacity check sees accurate active thread count

## Implementation

### File: `packages/soothe/src/soothe/daemon/query_engine.py`

#### Changes in `run_query()` (single-threaded path)

**Before (buggy)**:
```python
query_state_lock = getattr(d, "_query_state_lock", None)
if query_state_lock:
    async with query_state_lock:
        d._query_running = True
        d._active_threads[thread_id] = None  # ← PLACEHOLDER
else:
    d._query_running = True

# ... setup code ...

async def _run_stream() -> None:
    try:
        # ... streaming ...
    finally:
        d._active_threads.pop(thread_id, None)  # ← REMOVES PLACEHOLDER

try:
    task = asyncio.create_task(_run_stream())
    d._current_query_task = task
    d._active_threads[thread_id] = task  # ← SET AFTER FINALLY
    await task
```

**After (fixed)**:
```python
# Remove placeholder pattern entirely
d._query_running = True  # No lock needed, just flag

# ... setup code ...

async def _run_stream() -> None:
    try:
        # ... streaming ...
    finally:
        d._active_threads.pop(thread_id, None)  # ← REMOVES TASK

try:
    task = asyncio.create_task(_run_stream())
    d._current_query_task = task
    d._active_threads[thread_id] = task  # ← SET IMMEDIATELY
    await task
```

## Verification

```bash
./scripts/verify_finally.sh
```

**Result**: ✓ All 1346 tests passed, ready to commit.

## Implementation Complete

Race condition fixed successfully:
- Removed placeholder pattern (lines 100-107)
- Task set immediately after creation (line 338)
- No race window between capacity check and task creation
- Concurrent query hang resolved

## References

- [RFC-209 Executor Thread Isolation Simplification](../specs/RFC-209-executor-thread-isolation-simplification.md)
- [RFC-400 Daemon Communication Protocol](../specs/RFC-400-daemon-communication.md)
- [IG-138 Query Timeout Safeguards](./IG-138-query-timeout-safeguards.md)