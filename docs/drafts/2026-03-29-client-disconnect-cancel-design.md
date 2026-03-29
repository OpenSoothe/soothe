# Design Draft: Client Disconnect Query Cancellation

**Date**: 2026-03-29
**Status**: Approved
**Related**: IG-085 Phase 7 (Daemon Lifecycle Polish), RFC-0013 Section "Client Disconnect Query Cancellation"
**Implementation Target**: `src/soothe/daemon/client_session.py`, `src/soothe/daemon/_handlers.py`, `src/soothe/daemon/server.py`

## Problem Statement

When a CLI client disconnects via Ctrl+C, the active Claude subagent query continues running for several seconds before naturally completing. This wastes API credits and leaves orphan queries running in the daemon.

Analysis from log:
```
2026-03-29 21:02:15,068 INFO  soothe.daemon.client_session Removed client session ...
2026-03-29 21:02:17,642 INFO [T:d9d5bi43ackq] soothe.subagents.claude.implementation Progress: tool_use
```

The query continued for ~2.5 seconds after client disconnect because:
1. Client disconnect only removes session and cancels sender_task
2. No signal sent to cancel the actual `_current_query_task`
3. Claude subagent runs in isolated event loop, doesn't receive cancellation

## Design Decision

Two distinct exit behaviors:

| Action | Intent | Query Behavior | Client Behavior |
|--------|--------|----------------|-----------------|
| **Ctrl+C** | "Stop and exit" | Cancel query | Exit client |
| **Ctrl+D / `/detach`** | "Leave it running" | Query continues in daemon | Exit client |

Both preserve daemon persistence (per IG-085), but differ in query lifecycle.

**Chosen Approach**: Daemon auto-cancel on disconnect (with detach exception).

Rationale:
- Guaranteed cancellation - works even if network fails mid-signal
- Default-safe - unexpected disconnects cancel queries (avoid orphan API costs)
- Explicit detachment - only `detach` message keeps query running
- Consistent with IG-085 - daemon persists, queries scoped to client intent

## Architecture

Change localized to daemon server layer:

1. **ClientSession** - adds `detach_requested` flag
2. **ClientSessionManager** - tracks client→thread ownership
3. **DaemonHandlersMixin** - handles `detach` message, claims ownership on query start
4. **UnixSocketTransport** - triggers cancel check on disconnect

No changes needed in Claude subagent, CLI client, or ThreadExecutor.

## Components

### 1. ClientSession (add flag)

```python
@dataclass
class ClientSession:
    client_id: str
    transport: TransportServer
    transport_client: Any
    subscriptions: set[str] = field(default_factory=set)
    event_queue: asyncio.Queue[dict[str, Any]] = field(default_factory=...)
    sender_task: asyncio.Task[None] | None = None
    verbosity: VerbosityLevel = "normal"
    detach_requested: bool = False  # NEW: client explicitly requested detach
```

### 2. ClientSessionManager (add ownership tracking)

```python
class ClientSessionManager:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._sessions: dict[str, ClientSession] = {}
        self._lock = asyncio.Lock()
        self._client_thread_ownership: dict[str, str] = {}  # NEW: client_id → thread_id

    async def claim_thread_ownership(self, client_id: str, thread_id: str) -> None:
        """Claim that client_id owns the running query for thread_id."""
        async with self._lock:
            self._client_thread_ownership[client_id] = thread_id

    async def release_thread_ownership(self, client_id: str) -> str | None:
        """Release ownership, return the thread_id that was owned (or None)."""
        async with self._lock:
            return self._client_thread_ownership.pop(client_id, None)

    async def get_owned_thread(self, client_id: str) -> str | None:
        """Get thread_id owned by client (without releasing)."""
        async with self._lock:
            return self._client_thread_ownership.get(client_id)
```

### 3. DaemonHandlersMixin (handle detach + ownership)

In `_handle_client_message()`:

```python
elif msg_type == "detach":
    session = await self._session_manager.get_session(client_id)
    if session:
        session.detach_requested = True
    # Send acknowledgment
    await self._send_client_message(client_id, {"type": "status", "state": "detached"})
```

In `_run_query()` after query starts:

```python
self._query_running = True
await self._broadcast({"type": "status", "state": "running", "thread_id": thread_id})

# NEW: Claim ownership for the client that started this query
# Need to track which client initiated the query
await self._session_manager.claim_thread_ownership(initiating_client_id, thread_id)
```

Challenge: `_run_query()` currently doesn't track which client initiated it. Need to pass `client_id` through the input queue or track it elsewhere.

**Solution**: Store initiating client_id when input is queued:

```python
# In _handle_client_message() for "input" type:
await self._current_input_queue.put({
    "type": "input",
    "text": text,
    "client_id": client_id,  # NEW: track who sent this
    ...
})

# In _run_query():
async def _run_query(self, text: str, *, ..., client_id: str | None = None) -> None:
    ...
    if client_id:
        await self._session_manager.claim_thread_ownership(client_id, thread_id)
```

### 4. Session Removal (trigger cancel)

In `ClientSessionManager.remove_session()`:

```python
async def remove_session(self, client_id: str) -> None:
    """Remove client session and cleanup.

    Cancels owned query unless detach_requested was set.
    """
    async with self._lock:
        session = self._sessions.pop(client_id, None)
        owned_thread_id = self._client_thread_ownership.pop(client_id, None)

    if not session:
        return

    # NEW: Cancel query unless detach was explicitly requested
    if not session.detach_requested and owned_thread_id:
        # Need reference to daemon to cancel - pass during init or use callback
        await self._cancel_callback(owned_thread_id)
        logger.info(
            "Auto-cancelled thread %s on client %s disconnect (no detach requested)",
            owned_thread_id,
            client_id,
        )

    # Cancel sender task (existing)
    if session.sender_task:
        session.sender_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await session.sender_task

    # Unsubscribe from all topics (existing)
    await self._event_bus.unsubscribe_all(session.event_queue)

    logger.info("Removed client session %s", client_id)
```

Need to inject cancel callback:

```python
class ClientSessionManager:
    def __init__(
        self,
        event_bus: EventBus,
        cancel_callback: Callable[[str], Coroutine[None, None, None]] | None = None,
    ) -> None:
        self._cancel_callback = cancel_callback
```

In `SootheDaemon.__init__()`:

```python
self._session_manager: ClientSessionManager = ClientSessionManager(
    self._event_bus,
    cancel_callback=self._cancel_thread,  # NEW: pass cancel method
)
```

## Data Flow

### Ctrl+C (Cancel + Exit)

```
CLI Client                         Daemon Server
─────────                          ─────────────

1. KeyboardInterrupt caught
2. client.close() ───────────────► 3. Socket disconnect detected
                                   4. remove_session(client_id)
                                   5. Check: session.detach_requested?
                                      → False
                                   6. Get owned_thread_id
                                   7. _cancel_thread(thread_id)
                                   8. Query cancelled (asyncio.Task.cancel)
                                   9. _broadcast ERROR "Query cancelled"
                                   10. _broadcast status "idle"
3. Exit (return 0)
```

### Ctrl+D / `/detach` (Keep Running)

```
CLI Client                         Daemon Server
─────────                          ─────────────

1. User presses Ctrl+D or sends "/detach"
2. send("detach") ───────────────► 3. Handle detach message
                                   4. Set session.detach_requested = True
                                   5. Send ack {"type": "status", "state": "detached"}
3. client.close() ───────────────► 6. Socket disconnect detected
                                   7. remove_session(client_id)
                                   8. Check: session.detach_requested?
                                      → True
                                   9. Skip cancel, query continues
                                   10. Thread transitions to "suspended" later
4. Exit (daemon persists, query runs)
```

## Error Handling

| Scenario | Handling |
|----------|----------|
| Cancel fails (thread already done) | Gracefully ignore - query already finished |
| Thread not found in ownership map | No cancel needed - no query was running |
| Multiple clients subscribed to same thread | Only owner client's disconnect triggers cancel |
| Client crashes (no clean close) | No detach_requested flag → auto-cancel (safe default) |
| Cancel races with query completion | Safe - cancelling a finished asyncio.Task is harmless |
| No cancel_callback provided | Skip cancel (graceful degradation) |

## Testing Plan

### Unit Tests

File: `tests/unit/test_client_disconnect_cancel.py`

```python
async def test_disconnect_without_detach_cancels_query():
    """Client disconnect (no detach) should cancel owned thread."""
    manager = ClientSessionManager(event_bus, cancel_callback=mock_cancel)
    await manager.create_session(transport, client, "client-1")
    await manager.claim_thread_ownership("client-1", "thread-1")

    await manager.remove_session("client-1")

    mock_cancel.assert_called_once_with("thread-1")

async def test_disconnect_with_detach_keeps_query():
    """Client disconnect after detach should NOT cancel thread."""
    manager = ClientSessionManager(event_bus, cancel_callback=mock_cancel)
    session = await manager.create_session(transport, client, "client-1")
    session.detach_requested = True
    await manager.claim_thread_ownership("client-1", "thread-1")

    await manager.remove_session("client-1")

    mock_cancel.assert_not_called()

async def test_disconnect_no_owned_thread_no_cancel():
    """Client disconnect without owned thread should not call cancel."""
    manager = ClientSessionManager(event_bus, cancel_callback=mock_cancel)
    await manager.create_session(transport, client, "client-1")
    # No ownership claim

    await manager.remove_session("client-1")

    mock_cancel.assert_not_called()

async def test_cancel_callback_none_graceful():
    """No cancel_callback should not raise."""
    manager = ClientSessionManager(event_bus)  # No callback
    await manager.create_session(transport, client, "client-1")
    await manager.claim_thread_ownership("client-1", "thread-1")

    await manager.remove_session("client-1")  # Should not raise
```

### Integration Tests

File: `tests/integration/test_daemon_client_disconnect.py`

```python
async def test_ctrl_c_cancels_running_query():
    """Ctrl+C from CLI should cancel the daemon's active query."""
    # Start daemon
    # Connect client
    # Send query that triggers Claude subagent
    # Simulate Ctrl+C: close connection without detach
    # Verify query cancelled in daemon logs
    # Verify thread status → "idle" or "suspended"

async def test_detach_keeps_query_running():
    """Sending detach then closing should keep query running."""
    # Start daemon
    # Connect client
    # Send query
    # Send "detach" message
    # Close connection
    # Verify query continues in daemon logs
    # Verify thread status → still "running" then completes

async def test_client_crash_auto_cancels():
    """Unexpected client disconnect (crash) should auto-cancel."""
    # Start daemon with query running
    # Kill client process without graceful close
    # Verify daemon auto-cancels (no detach flag)
```

### Manual Testing

- [ ] `soothe -p "analyze codebase"` → Ctrl+C → verify "Query cancelled" in daemon log
- [ ] TUI mode → start query → `/detach` → verify query continues
- [ ] TUI mode → start query → Ctrl+C → verify query cancelled
- [ ] Kill client process → verify daemon auto-cancels

## Integration with IG-085

This change is **orthogonal** to IG-085 daemon lifecycle:

- IG-085 ensures daemon persists after client exit (unchanged by this design)
- This design adds: query cancellation semantics based on exit type

IG-085 Phase 4 specifies `detach` handling:

```python
async def handle_detach(self, client_id: str) -> None:
    """Handle detach message from client."""
    # Just close the client session
    await self._session_manager.close_session(client_id)
    # Do NOT call self.request_stop() or self.stop()
```

This design refines that to:

```python
async def handle_detach(self, client_id: str) -> None:
    """Handle detach message from client."""
    session = await self._session_manager.get_session(client_id)
    if session:
        session.detach_requested = True
    await self._send_client_message(client_id, {"type": "status", "state": "detached"})
    # Client will close its own connection after receiving ack
```

## Implementation Scope

| File | Changes |
|------|---------|
| `src/soothe/daemon/client_session.py` | Add `detach_requested`, `_client_thread_ownership`, `cancel_callback`, ownership methods |
| `src/soothe/daemon/_handlers.py` | Handle `detach` message, pass `client_id` through input queue |
| `src/soothe/daemon/server.py` | Pass `cancel_callback` to ClientSessionManager |
| `src/soothe/ux/cli/execution/daemon.py` | No changes (Ctrl+C just closes connection) |
| `tests/unit/test_client_disconnect_cancel.py` | New test file |
| `tests/integration/test_daemon_client_disconnect.py` | New test file |

## Success Criteria

- [ ] Ctrl+C cancels active query immediately (subagent stops within 1s)
- [ ] `/detach` or Ctrl+D leaves query running in daemon
- [ ] Unexpected client crash auto-cancels query
- [ ] All unit and integration tests pass
- [ ] No regression in daemon lifecycle (IG-085 behavior preserved)
- [ ] Clear logging: "Auto-cancelled thread X on client Y disconnect"

## Implementation Notes

### Single-threaded vs Multi-threaded Mode

The daemon has two execution modes:
- **Single-threaded**: Uses `_current_query_task` to track the running query
- **Multi-threaded**: Uses `_active_threads: dict[str, asyncio.Task]` for concurrent queries

The existing `_cancel_thread()` method only handles multi-threaded mode:

```python
async def _cancel_thread(self, thread_id: str) -> None:
    if hasattr(self, "_active_threads") and thread_id in self._active_threads:
        task = self._active_threads[thread_id]
        task.cancel()
```

Need to extend this to also handle single-threaded mode:

```python
async def _cancel_thread(self, thread_id: str) -> None:
    """Cancel a specific thread's execution.

    Works for both single-threaded and multi-threaded modes.
    """
    # Multi-threaded mode
    if hasattr(self, "_active_threads") and thread_id in self._active_threads:
        task = self._active_threads[thread_id]
        task.cancel()
        logger.info("Cancelled thread %s (multi-threaded)", thread_id)
        await self._broadcast(...)
        return

    # Single-threaded mode - cancel current query if thread_id matches
    if self._current_query_task and not self._current_query_task.done():
        current_thread = self._runner.current_thread_id
        if current_thread == thread_id:
            self._current_query_task.cancel()
            logger.info("Cancelled thread %s (single-threaded)", thread_id)
            # The _run_query() finally block handles cleanup
            return

    logger.debug("Thread %s not found or already complete", thread_id)
```

### Cancel Callback Signature

The cancel callback needs to be a bound method, so the signature is:

```python
cancel_callback: Callable[[str], Coroutine[None, None, None]]
```

Passed as:
```python
self._session_manager = ClientSessionManager(
    self._event_bus,
    cancel_callback=self._cancel_thread,
)
```

## Open Questions

None - design is complete and approved.