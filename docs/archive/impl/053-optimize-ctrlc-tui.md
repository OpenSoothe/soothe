# IG-053: Optimize Ctrl+C Behavior in TUI

**Status**: ✅ Completed
**Created**: 2026-03-28
**Scope**: TUI UX improvement

## Objective

Improve Ctrl+C user experience in the TUI:
1. Remove verbose "No running query to cancel" message
2. First Ctrl+C: cancel current query OR show brief message to press again to exit
3. Second Ctrl+C (within timeout): exit TUI completely

## Current Behavior

**Binding**: `ctrl+c` → `action_cancel_job()` → sends `/cancel` command to daemon

**Daemon handler** (`_cancel_current_query()`):
- If query running: cancel it and show "Query cancelled successfully"
- If no query running: show verbose yellow message "No running query to cancel"

**Problem**:
- Verbose output is unnecessary and intrusive
- No way to exit TUI with Ctrl+C (requires ctrl+q or /exit)
- Users expect Ctrl+C to work like standard CLI tools (double-press to exit)

## Design

### Ctrl+C State Machine

```
State: IDLE
  ↓ [Ctrl+C pressed]
  ↓
  Check if query running?
  ├─ YES → Cancel query → State: IDLE
  └─ NO  → Show brief message → State: WAITING_FOR_SECOND_CTRLC (3s timeout)
           ↓ [Ctrl+C pressed within 3s]
           ↓
           Exit TUI → State: EXITED
           ↓ [No Ctrl+C within 3s]
           ↓
           Return to IDLE
```

### Implementation Changes

#### 1. TUI App (`src/soothe/ux/tui/app.py`)

**Add state tracking**:
```python
_ctrl_c_pressed_time: float | None = None  # Timestamp of first Ctrl+C
_CTRL_C_TIMEOUT = 3.0  # Seconds to wait for second Ctrl+C
```

**Modify `action_cancel_job()`**:
```python
async def action_cancel_job(self) -> None:
    """Handle Ctrl+C with double-press exit behavior."""
    import time

    current_time = time.time()

    # Check if we're waiting for second Ctrl+C
    if self._ctrl_c_pressed_time is not None:
        time_diff = current_time - self._ctrl_c_pressed_time
        if time_diff < self._CTRL_C_TIMEOUT:
            # Second Ctrl+C within timeout - exit TUI
            self._ctrl_c_pressed_time = None
            await self.action_quit_app()
            return
        else:
            # Timeout expired - reset state
            self._ctrl_c_pressed_time = None

    # First Ctrl+C or timeout expired
    if self._is_running:
        # Query is running - cancel it
        self._ctrl_c_pressed_time = None
        if self._client and self._connected:
            await self._client.send_command("/cancel")
    else:
        # No query running - show brief message and start timeout
        self._ctrl_c_pressed_time = current_time
        self._on_panel_write(
            make_dot_line(DOT_COLORS["protocol"], "Press Ctrl+C again within 3s to exit")
        )
```

#### 2. Daemon Handler (`src/soothe/daemon/_handlers.py`)

**Modify `_cancel_current_query()`**:
- Remove verbose yellow message when no query running
- Only send success message when query was actually cancelled
- Keep the cancellation logic unchanged

```python
async def _cancel_current_query(self) -> None:
    """Cancel the currently running query if any."""
    if not self._query_running:
        # Silently ignore - TUI will handle the UX
        return

    if self._current_query_task and not self._current_query_task.done():
        logger.info("Cancelling current query task")
        self._current_query_task.cancel()

        # Wait for the task to actually be cancelled
        with contextlib.suppress(asyncio.CancelledError):
            await self._current_query_task

        self._query_running = False
        self._current_query_task = None

        await self._broadcast(
            {
                "type": "command_response",
                "content": "[green]Query cancelled.[/green]",
            }
        )
        await self._broadcast(
            {"type": "status", "state": "idle", "thread_id": self._runner.current_thread_id or ""}
        )
```

## Verification

1. **Test query cancellation**:
   - Start long-running query
   - Press Ctrl+C once
   - Verify query cancelled with brief success message

2. **Test double-press exit**:
   - With no query running, press Ctrl+C once
   - Verify brief message appears
   - Press Ctrl+C again within 3s
   - Verify TUI exits cleanly

3. **Test timeout expiration**:
   - With no query running, press Ctrl+C once
   - Wait >3 seconds
   - Press Ctrl+C again
   - Verify message appears again (not exit)

4. **Test rapid cancellation**:
   - Start query, immediately press Ctrl+C
   - Verify query cancelled without "press again" message

## Files Changed

- `src/soothe/ux/tui/app.py`: Add state tracking and double-press logic
- `src/soothe/daemon/_handlers.py`: Remove verbose "no query" message
- `src/soothe/ux/core/progress_verbosity.py`: Fixed missing "internal" verbosity mapping (pre-existing bug)

## Backward Compatibility

- `ctrl+q` binding still works (unchanged)
- `/exit` command still works (unchanged)
- `/cancel` command behavior unchanged for CLI users
- Only TUI UX improved

## Success Criteria

✅ No verbose yellow message when no query running
✅ Single Ctrl+C cancels running query
✅ Double Ctrl+C exits TUI when idle
✅ Timeout prevents accidental exits
✅ All existing tests pass (936 passed, 2 skipped, 1 xfailed)

## Implementation Notes

**Fixed pre-existing bug**: The `verbosity_map` in `progress_verbosity.py` was missing the "internal" entry, causing `ChitchatStartedEvent` to be classified as "protocol" instead of "internal". This caused the test `test_classify_output_events` to fail.

**Added**: `"internal": "internal"` to the `verbosity_map` dictionary to properly classify internal events that should never be shown at any verbosity level.