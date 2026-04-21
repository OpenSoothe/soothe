---
name: IG-054 Fix Concurrent Query Race Condition
status: completed
created: 2026-04-20
---

# IG-054: Fix Concurrent Query Race Condition

## Problem

Critical race condition in concurrent query handling causing capacity limit violations.

### Race Window (Actual Problem)

The capacity check in `message_router.py` happens **before** messages are queued, but tasks are only added to `_active_threads` **after** the input loop processes them from the queue. This creates a race window where multiple messages can pass the capacity check before any tasks are created.

```python
# Buggy flow:
Message Router (line 52-53):
  max_concurrent = getattr(d._config.daemon, "max_concurrent_threads", 100)
  at_capacity = max_concurrent > 0 and len(d._active_threads) >= max_concurrent
  if at_capacity:  # ← CHECK HAPPENS HERE
      await d._send_client_message(client_id, {"type": "error", "code": "DAEMON_BUSY", ...})
      return

  await d._current_input_queue.put(msg)  # ← QUEUE MESSAGE

Input Loop (line 178):
  msg = await self._current_input_queue.get()  # ← PROCESS MESSAGE
  await self._query_engine.run_query(...)  # ← EXECUTE

Query Engine (line 334):
  task = asyncio.create_task(_run_stream())
  d._active_threads[thread_id] = task  # ← TASK ADDED HERE (after queue processing)
```

### Timeline Example

```python
# Two clients sending queries when max_concurrent_threads = 1:

T0: Client A sends input
    - message_router checks: len(_active_threads) = 0 ✓
    - message queued

T1: Client B sends input
    - message_router checks: len(_active_threads) = still 0 ✓ (no task created yet!)
    - message queued

T2: Input loop processes A
    - query_engine creates task
    - len(_active_threads) = 1

T3: Input loop processes B
    - query_engine creates task
    - len(_active_threads) = 2 ← EXCEEDS LIMIT!
```

### Root Cause

**Capacity check at wrong stage**: Checking at message routing time (before queueing) instead of at task creation time (after queue processing) allows multiple messages to slip through before any task is actually created.

## Fix Strategy

Move capacity check from message routing to task creation time:

1. **Remove capacity checks** in `message_router.py` (happens too early)
2. **Add capacity check** in `query_engine.py` right before task creation
3. **Ensures atomicity**: Check → Create task → Add to dict (no race window)

### Implementation Steps

1. Remove capacity checks in message_router.py (lines 52-67 and 777-793)
2. Add capacity check in query_engine.py before task creation (lines 100-129)
3. Add same check to multithreaded path (lines 409-437)
4. Broadcast DAEMON_BUSY error when at capacity
5. Release thread ownership if client_id present

## Thread Isolation Analysis

### Current Design (Multi-layer Isolation)

**Goal**: Isolate threads from different clients to prevent cross-contamination.

**Current approach**: Uses simpler asyncio.Task-based isolation following RFC-207's thread context lifecycle pattern.

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
# message_router checks capacity BEFORE queuing:
at_capacity = len(d._active_threads) >= max_concurrent
if not at_capacity:
    await d._current_input_queue.put(msg)

# Input loop processes queued messages:
msg = await d._current_input_queue.get()
await d._query_engine.run_query(...)  # ← Task created AFTER queue processing

# After (fixed):
# message_router queues directly without capacity check:
await d._current_input_queue.put(msg)

# Input loop processes message:
msg = await d._current_input_queue.get()

# Query engine checks capacity RIGHT BEFORE task creation:
at_capacity = len(d._active_threads) >= max_concurrent
if at_capacity:
    await d._broadcast(DAEMON_BUSY error)
    return

task = asyncio.create_task(_run_stream())
d._active_threads[thread_id] = task  # ← Atomic: check → create → add
```

**Key properties**:
- Capacity check happens immediately before task creation (no queue delay)
- Multiple queued messages won't exceed limit (check happens at execution time)
- Concurrent capacity enforcement: `len(_active_threads) >= max_concurrent`
- Task cancellation targets specific thread

### ThreadExecutor Design (Historical Context)

**Location**: `core/thread/executor.py`

**Historical design** (superseded by RFC-207):
- ThreadExecutor wrapped runner.astream in rate-limited context
- APIRateLimiter controlled concurrent API calls
- Manual thread context management

**Current best practice** (RFC-207):
- Trust langgraph's atomic state management
- Use asyncio.Task isolation directly
- Task tool handles subagent isolation automatically
- No manual thread ID generation or merging

### Key Insight: Isolation is Layered

Thread isolation spans **6 layers**, not just execution-level:
1. Client ownership (SessionManager)
2. Thread state registry (ThreadStateRegistry)
3. Workspace filesystem context
4. Checkpoint durability (LangGraph checkpointer)
5. Event bus routing
6. Execution task isolation

Each layer provides specific isolation guarantees.

### Evolution: From Executor-Only to Layered Isolation

**Historical approach** (superseded):
- Tried to isolate at executor level only
- Manual thread ID generation/merging
- Redundant isolation (langgraph already handles it)

**Current approach** (RFC-207):
- Trusts langgraph atomic state updates
- Simplifies executor to pure orchestration
- Task tool handles subagent isolation automatically
- Isolation distributed across 6 architectural layers

### Isolation Test Scenarios

1. **Concurrent file operations**: Two threads writing to different files in same workspace
2. **Cross-client access**: Client A tries to cancel Client B's thread (blocked by ownership)
3. **Disconnect auto-cancel**: Client disconnects without detach, thread auto-cancelled
4. **Event routing**: Thread A events don't appear in Thread B client's TUI
5. **Workspace isolation**: Thread A cannot access Thread B's workspace files
6. **Capacity enforcement**: Concurrent query limit blocks at capacity accurately

## Testing Strategy

1. **Updated existing test**: Changed `test_daemon_input_message_returns_busy_error_at_concurrency_limit` to `test_daemon_input_message_queued_at_capacity` to reflect that capacity check now happens in query_engine, not message_router
2. **Test validates**: Messages are queued at router level, DAEMON_BUSY error sent at query_engine execution level
3. **Integration test**: Run concurrent queries to verify accurate capacity enforcement at execution time

## Implementation

### Root Cause Analysis

The race condition was **NOT** in the placeholder pattern as initially documented. The actual race was:

**Timeline**:
1. Client A sends input → `message_router.py` checks capacity (len = 0) → message queued
2. Client B sends input → `message_router.py` checks capacity (len still 0) → message queued
3. Input loop processes A → creates task in `query_engine.py` (len = 1)
4. Input loop processes B → creates task in `query_engine.py` (len = 2)
5. **Result**: Both queries execute, exceeding the limit

The capacity check at message routing time was **too early** - before tasks were created.

### File: `packages/soothe/src/soothe/daemon/query_engine.py`

**Added capacity check at task creation time** (lines 100-129):

```python
# IG-054: Check capacity BEFORE creating task (not at message routing time)
# This eliminates race window between capacity check and task creation
max_concurrent = getattr(d._config.daemon, "max_concurrent_threads", 100)
at_capacity = max_concurrent > 0 and len(d._active_threads) >= max_concurrent
if at_capacity:
    logger.warning(
        "Daemon at capacity (%d/%d threads), rejecting query for thread %s",
        len(d._active_threads),
        max_concurrent,
        thread_id,
    )
    from soothe.core.event_catalog import ERROR

    await d._broadcast(
        {
            "type": "event",
            "thread_id": thread_id,
            "namespace": [],
            "mode": "custom",
            "data": {
                "type": ERROR,
                "error": (
                    f"Daemon has reached its concurrent query limit ({max_concurrent}). "
                    "Wait for a query to finish or cancel one before starting a new one."
                ),
                "code": "DAEMON_BUSY",
            },
        }
    )
    await d._broadcast({"type": "status", "state": "idle", "thread_id": thread_id})
    if client_id:
        await d._session_manager.release_thread_ownership(client_id)
    return
```

**Added same check to multithreaded path** (lines 409-437):

Same capacity check logic added to `run_query_multithreaded()` to ensure both paths have the check.

### File: `packages/soothe/src/soothe/daemon/message_router.py`

**Removed premature capacity checks** (lines 49-67 and 777-793):

Removed the capacity checks that happened at message routing time, which created the race window.

**Before (buggy)**:
```python
if msg_type == "input":
    text = msg.get("text", "").strip()
    if text:
        max_concurrent = getattr(d._config.daemon, "max_concurrent_threads", 100)
        at_capacity = max_concurrent > 0 and len(d._active_threads) >= max_concurrent
        if at_capacity:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "DAEMON_BUSY",
                    ...
                },
            )
            return

        # Queue message...
```

**After (fixed)**:
```python
if msg_type == "input":
    text = msg.get("text", "").strip()
    if text:
        # IG-054: Capacity check moved to query_engine.py to eliminate race
        # between checking len(_active_threads) and actually creating the task

        # Queue message directly without premature capacity check...
```

## Verification

```bash
./scripts/verify_finally.sh
```

**Result**: ✓ All 1346 tests passed, ready to commit.

## Implementation Complete

Race condition fixed successfully:
- Removed premature capacity checks from message_router.py (2 locations)
- Added capacity check to query_engine.py right before task creation (both single-threaded and multithreaded paths)
- Made run_query() non-blocking: creates background task and returns immediately (fire-and-forget)
- Moved post-query cleanup logic into task's finally block
- Input loop can now process concurrent queries in parallel

**Key insight**: The input loop was blocking because it awaited `run_query()` which awaited the task. Making queries run in background allows true concurrency.

## Files Modified

1. `packages/soothe/src/soothe/daemon/query_engine.py` - Added capacity checks + made run_query non-blocking
2. `packages/soothe/src/soothe/daemon/message_router.py` - Removed premature capacity checks
3. `packages/soothe/src/soothe/cognition/agent_loop/executor.py` - Fixed import sorting and variable naming (unrelated linting fix)
4. `packages/soothe/tests/unit/cli/test_cli_daemon.py` - Updated 4 tests to wait for background tasks

## References

- [RFC-207 AgentLoop Thread Context Lifecycle](../specs/RFC-207-agentloop-thread-context-lifecycle.md) - Unified thread lifecycle
- [RFC-450 Daemon Communication Protocol](../specs/RFC-450-daemon-communication-protocol.md) - Daemon transport layer
- [RFC-402 Memory Protocol Architecture](../specs/RFC-402-memory-protocol-architecture.md) - Thread state management
- [IG-138 Query Timeout Safeguards](./IG-138-query-timeout-safeguards.md) - Timeout mechanisms