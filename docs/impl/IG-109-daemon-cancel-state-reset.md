# IG-109: Fix Daemon Second Query Bug After Ctrl+C

## Problem

After restarting the daemon, running a query, pressing Ctrl+C to cancel it, then running a new query, the daemon fails or behaves incorrectly on the second query.

## Root Cause Analysis

When a query is cancelled via Ctrl+C:
1. `_cancel_current_query()` cancels the asyncio task
2. Task's finally block clears `_query_running` and `_current_query_task`
3. **BUT `_runner._current_thread_id` is NOT cleared**

On the second query:
1. `_ensure_active_thread_id()` checks `self._runner.current_thread_id`
2. If value exists, it's reused without validation
3. New query runs in cancelled thread's context, causing:
   - Checkpoint recovery attempts from partial execution state
   - Stale workspace context
   - Inconsistent LangGraph checkpointer state

## Code Locations

| File | Line | Issue |
|------|------|-------|
| `_handlers.py` | 673-702 | `_cancel_current_query()` doesn't reset thread_id |
| `_handlers.py` | 886-893 | `_run_query()` outer CancelledError handler doesn't reset |
| `_handlers.py` | 1195-1206 | `_ensure_active_thread_id()` reuses stale thread_id |
| `runner/__init__.py` | 154-185 | `_current_thread_id` persists across cancellations |
| `filesystem.py` | 20 | `_current_workspace` ContextVar not cleared on cancel |
| `workspace_context.py` | 83-100 | `aafter_agent()` may not run on cancellation |

## Solution

### Fix 1: Clear thread_id in _cancel_current_query

```python
# After cancelling task, reset runner thread_id
self._runner.set_current_thread_id(None)
```

### Fix 2: Clear thread_id in _run_query outer handler

```python
except asyncio.CancelledError:
    logger.info("Query task cancelled")
    self._runner.set_current_thread_id(None)
```

### Fix 3: Clear workspace ContextVar on cancellation

```python
except asyncio.CancelledError:
    from soothe.safety import FrameworkFilesystem
    FrameworkFilesystem.clear_current_workspace()
```

## Verification

1. Start daemon: `soothe daemon start`
2. Run query: `soothe "list files"`
3. Press Ctrl+C during execution
4. Run new query: `soothe "list files again"`
5. Verify second query works correctly

Run: `./scripts/verify_finally.sh`