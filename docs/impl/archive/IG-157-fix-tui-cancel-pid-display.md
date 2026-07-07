# IG-157: Fix TUI Cancel and PID Display Issues

## Problem

From user screenshot and analysis:

1. **PID shows "?" in TUI** - `Daemon running (PID: ?)` message appears even when daemon is running
2. **Ctrl+C cannot stop running query** - Repeated cancel attempts don't stop the agent execution

## Root Cause Analysis

### Issue 1: PID Not Displayed

The TUI reads PID from `pid_path()` at runtime:
```python
pf = pid_path()
pid = pf.read_text().strip() if pf.exists() else "?"
```

However, the daemon writes PID via `acquire_pid_lock()` which:
- Creates the file with `O_CREAT | O_RDWR`
- Writes PID bytes to the file descriptor
- **Keeps the file descriptor open and locked**

The issue: When writing to a file descriptor with `os.write(fd, ...)`, the data goes to the file, but there's a timing issue:
- The daemon process may not have fsynced/synced the data to disk before TUI reads
- Or the TUI reads before the daemon has fully started

Actually, looking at `acquire_pid_lock()` line 50:
```python
os.fsync(fd)  # Forces write to disk
```

So the PID IS written. The real issue might be:
- The daemon is not actually running (crashed during startup?)
- Or path resolution differs between daemon and TUI context
- Or the file exists but is empty/corrupted

### Issue 2: Cancel Not Working

The cancel flow:
1. TUI: `action_cancel_job()` → `send_command("/cancel")`
2. Daemon: `_input_loop()` → `cancel_current_query()`
3. QueryEngine: Cancels `_current_query_task` task
4. Query task receives `asyncio.CancelledError`
5. **But**: LangGraph `agent.astream()` may not propagate cancellation properly

The real issue: LangGraph's `astream()` is a sync iterator wrapped in async context. When we cancel the task:
- The outer `async for` loop gets cancelled
- **But the inner LangGraph execution continues** because it's a compiled graph that doesn't check for cancellation

Solution: We need to check for cancellation actively in the stream loop.

## Implementation Plan

### Fix 1: Robust PID Display

Current approach reads PID file directly. Need fallback:

```python
# In TUI cancel/detach/quit handlers
from soothe.daemon import pid_path, SootheDaemon

pf = pid_path()
if pf.exists():
    pid = pf.read_text().strip()
else:
    # Fallback: use SootheDaemon.find_pid()
    pid = SootheDaemon.find_pid() or "?"
```

This matches the daemon status command logic at `daemon_cmd.py:123`.

### Fix 2: Proper Query Cancellation

LangGraph `astream()` doesn't check asyncio cancellation internally. We need to:

1. **Add cancellation check in stream loop** (`query_engine.py`):
```python
async for chunk in d._runner.astream(text, **stream_kwargs):
    # Check if task was cancelled from outside
    if d._current_query_task and d._current_query_task.done():
        logger.info("Stream loop detected cancelled task, stopping")
        break

    # Process chunk...
```

2. **Add cancellation propagation in runner** (`_runner_phases.py`):
```python
async for chunk in self._agent.astream(...):
    # Check for cancellation
    try:
        # Check current task cancellation
        current_task = asyncio.current_task()
        if current_task and current_task.cancelling():
            logger.info("Runner stream detected cancellation, stopping")
            break
    except asyncio.CancelledError:
        logger.info("Runner stream received CancelledError, stopping")
        raise

    # Process chunk...
```

3. **Make cancellation more aggressive** (`query_engine.py`):
```python
async def cancel_current_query(self) -> None:
    # Cancel task
    if d._current_query_task and not d._current_query_task.done():
        d._current_query_task.cancel()

        # Wait briefly for cancellation to propagate
        try:
            await asyncio.wait_for(d._current_query_task, timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            # Task didn't stop - log warning
            logger.warning("Query task did not stop within 1s after cancel")

        # Force cleanup
        d._query_running = False
        d._runner.set_current_thread_id(None)
```

### Fix 3: Add Cancellation Event Broadcast

When query is cancelled, broadcast a clear event:

```python
# In query_engine.py cancel handlers
await d._broadcast({
    "type": "event",
    "thread_id": thread_id,
    "namespace": [],
    "mode": "custom",
    "data": {"type": "query_cancelled", "message": "Query cancelled successfully"},
})
```

## Files to Modify

1. `src/soothe/ux/tui/app.py` - Update PID display logic (lines 809-810, 830-831, 908-909, 922-923)
2. `src/soothe/daemon/query_engine.py` - Add cancellation checks in stream loops
3. `src/soothe/core/runner/_runner_phases.py` - Add cancellation check in `_stream_phase()`
4. `src/soothe/daemon/_handlers.py` - Ensure cancel propagates properly

## Testing

1. Start daemon and TUI
2. Send long-running query (e.g., complex code generation)
3. Press Ctrl+C to cancel
4. Verify:
   - PID is displayed correctly (not "?")
   - Query stops within 1-2 seconds
   - TUI shows "Query cancelled" message
   - Status changes to "idle"

## Success Criteria

- PID always shows actual daemon process ID (not "?")
- Ctrl+C stops running queries within 2 seconds
- No zombie queries continue after cancel
- TUI displays clear cancellation feedback

## References

- RFC-0013: Daemon lifecycle
- IG-109: Daemon cancel state reset
- docs/impl/053-optimize-ctrlc-tui.md