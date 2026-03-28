# IG-085: Daemon Lifecycle Polish Implementation

**Implementation Guide**: 085
**Title**: Polish daemon lifecycle behavior for client attachment/detachment semantics
**Status**: Draft
**Created**: 2026-03-28
**RFC References**: RFC-0013 (Daemon Communication Protocol), RFC-0003 (CLI TUI Architecture)
**Priority**: High
**Estimated Effort**: 2-3 days

## Overview

This implementation guide refines the daemon lifecycle behavior to establish clear semantics for client attachment, detachment, and daemon persistence across all interaction modes (Non-TUI and TUI). The changes ensure:

1. **Daemon persistence**: Daemon remains running across client sessions
2. **Client exit semantics**: `/exit`/`/quit` and double Ctrl+C exit client, not daemon
3. **Clear messaging**: Users understand daemon state at all times
4. **No implicit shutdown**: Only explicit `soothe daemon stop` kills daemon

## RFC Changes Summary

### RFC-0013 Updates (Already Completed)

Added **Daemon Lifecycle Semantics** section with:
- Daemon persistence behavior
- Client-server interaction patterns
- Daemon state transitions
- Client exit semantics
- Thread warning on exit

### RFC-0003 Updates (Already Completed)

Updated:
- `/exit`/`/quit` description: "Exit TUI client; daemon keeps running"
- Keyboard shortcuts: Ctrl+Q now exits client, not daemon
- Double Ctrl+C behavior: 1-second window for intentional exit

## Implementation Plan

### Phase 1: Non-TUI Mode Changes (Headless Single-Prompt)

**File**: `src/soothe/ux/cli/execution/daemon.py`

**Current Behavior**: `run_headless_via_daemon()` connects, executes, and disconnects, but daemon shutdown behavior unclear.

**Required Changes**:
1. Remove any implicit daemon shutdown logic
2. Add clear exit messaging showing daemon persistence
3. Handle daemon auto-start fallback properly

**Implementation Steps**:
```python
# In run_headless_via_daemon()
# After request completes:

# OLD (if exists):
# if daemon_was_started_for_this_request:
#     SootheDaemon.stop_running()  # WRONG - remove this

# NEW:
# Just disconnect client, show message
await client.close()
typer.echo(f"[lifecycle] Request completed. Daemon running (PID: {pid}).", err=True)
```

**Exit Codes**: Return 0 on success, 1 on error, 42 on daemon fallback (already implemented).

**Testing**:
- Test case: Daemon not running → auto-start → request → daemon keeps running
- Test case: Daemon running → attach → request → daemon keeps running
- Verify PID file exists after client disconnect

### Phase 2: TUI Mode Changes

**File**: `src/soothe/ux/tui/app.py`

**Current Behavior**: `/exit`/`/quit` and Ctrl+Q trigger full daemon shutdown.

**Required Changes**:

#### 2.1 Modify Slash Command Handlers

Locate `/exit` and `/quit` command handling (likely in `action_quit()` or similar).

**Changes**:
```python
# OLD:
def action_quit(self) -> None:
    """Quit TUI and stop daemon."""
    await self._client.send_command("/exit")  # This may stop daemon
    self.exit()

# NEW:
def action_quit(self) -> None:
    """Exit TUI client; daemon keeps running."""
    # Send detach message
    await self._client.send_detach()
    # Close connection
    await self._client.close()
    # Show message
    pid = self._get_daemon_pid()
    self._show_exit_message(pid)
    self.exit()
```

**Key Points**:
- Use `send_detach()` message, not `send_command("/exit")`
- Close client connection gracefully
- Show message: "TUI exited. Daemon running (PID: XXX). Use 'soothe daemon stop' to shutdown."
- Exit TUI app

#### 2.2 Implement Double Ctrl+C Detection

Add state tracking for Ctrl+C timing:

```python
class SootheApp(App):
    def __init__(self, ...):
        self._last_ctrl_c_time: float | None = None
        self._ctrl_c_timeout_seconds: float = 1.0

    def action_cancel_job(self) -> None:
        """Handle Ctrl+C - cancel job or exit on double-press."""
        import time
        current_time = time.time()

        # Check if this is second Ctrl+C within timeout
        if self._last_ctrl_c_time and (current_time - self._last_ctrl_c_time) < self._ctrl_c_timeout_seconds:
            # Double Ctrl+C - exit TUI
            self._show_double_ctrl_c_exit_message()
            await self.action_quit()  # Use new quit behavior
            return

        # First Ctrl+C - cancel job
        self._last_ctrl_c_time = current_time
        self._cancel_current_job()
        self._show_cancel_message()

    def _show_cancel_message(self) -> None:
        """Show message after first Ctrl+C."""
        pid = self._get_daemon_pid()
        self._state.add_message(
            "Job cancelled. Press Ctrl+C again within 1s to exit TUI.\n"
            f"Daemon running (PID: {pid})."
        )

    def _show_double_ctrl_c_exit_message(self) -> None:
        """Show message after double Ctrl+C."""
        pid = self._get_daemon_pid()
        self._state.add_message(
            f"TUI exited via double Ctrl+C. Daemon running (PID: {pid}).\n"
            "Use 'soothe daemon stop' to shutdown daemon."
        )
```

#### 2.3 Add Thread Running Warning

Before exiting, check if thread is in `running` state:

```python
def action_quit(self) -> None:
    """Exit TUI client; daemon keeps running."""
    # Check thread state
    if self._state.thread_state == "running":
        # Show warning modal
        response = self._show_thread_running_warning()
        if response == "n":
            return  # Stay in TUI
        # If 'y', proceed to exit (thread transitions to suspended)

    # Proceed with detach and exit
    await self._client.send_detach()
    await self._client.close()
    pid = self._get_daemon_pid()
    self._show_exit_message(pid)
    self.exit()

def _show_thread_running_warning(self) -> str:
    """Show warning modal for running thread."""
    from soothe.ux.tui.modals import ConfirmModal

    modal = ConfirmModal(
        title="Thread Running Warning",
        message=f"Thread {self._state.thread_id} is still running.\nExit anyway? (y/n)",
    )
    self.push_screen(modal)
    return modal.response  # 'y' or 'n'
```

#### 2.4 Helper Methods

Add helper methods for daemon PID retrieval and message display:

```python
def _get_daemon_pid(self) -> str:
    """Get daemon PID from PID file."""
    from soothe.daemon import pid_path

    pf = pid_path()
    if pf.exists():
        return pf.read_text().strip()
    return "?"

def _show_exit_message(self, pid: str) -> None:
    """Show daemon running message in TUI or stdout."""
    import sys

    message = f"TUI exited. Daemon running (PID: {pid}). Use 'soothe daemon stop' to shutdown."
    sys.stderr.write(f"\n{message}\n")
    sys.stderr.flush()
```

### Phase 3: Update TUI Commands Handler

**File**: `src/soothe/ux/tui/commands.py`

**Changes**: Ensure `/exit`/`/quit`/`/detach` all trigger same detach behavior (not daemon shutdown).

```python
async def handle_command(self, cmd: str) -> None:
    """Handle slash command."""
    if cmd in ("/exit", "/quit", "/detach"):
        # All three should detach client, not stop daemon
        await self._app.action_quit()
        return

    # Other commands...
```

### Phase 4: Daemon Server Side Changes

**File**: `src/soothe/daemon/server.py`

**Current Behavior**: May have daemon shutdown logic on client disconnect.

**Required Changes**:
1. Ensure daemon doesn't shutdown on client disconnect
2. Handle `detach` message properly (just close client connection)
3. Track connected clients (already implemented via ClientSessionManager)

**Verify in `stop()` method**:
```python
async def stop(self) -> None:
    """Shut down the daemon gracefully."""
    # This should ONLY be called by:
    # 1. Explicit 'soothe daemon stop'
    # 2. SIGTERM signal
    # 3. Foreground Ctrl+C (--foreground mode)

    # NOT called on:
    # - Client disconnect
    # - Thread completion
    # - Client sending 'detach' message
```

**Verify `detach` handling in `_handlers.py`**:
```python
async def handle_detach(self, client_id: str) -> None:
    """Handle detach message from client."""
    # Just close the client session
    await self._session_manager.close_session(client_id)
    # Do NOT call self.request_stop() or self.stop()
```

### Phase 5: Non-TUI Launcher Changes

**File**: `src/soothe/ux/cli/execution/launcher.py`

**Current Behavior**: `run_headless()` decides whether to use daemon or standalone.

**Required Changes**:
- Ensure daemon fallback logic doesn't stop daemon after request
- Add clear messaging about daemon persistence

```python
def run_headless(cfg, prompt, thread_id, output_format, autonomous, max_iterations):
    """Run headless mode - choose daemon or standalone."""
    from soothe.daemon import SootheDaemon

    # Try daemon first
    if SootheDaemon.is_running() or should_auto_start():
        exit_code = run_headless_via_daemon(...)

        # NEW: Show daemon persistence message
        if SootheDaemon.is_running():
            pid = get_daemon_pid()
            typer.echo(f"[lifecycle] Daemon running (PID: {pid}).", err=True)

        sys.exit(exit_code)
    else:
        # Fallback to standalone
        run_headless_standalone(...)
```

### Phase 6: User Messaging Polish

**Add consistent lifecycle messages across all modes**:

Create helper function for daemon lifecycle messages:

```python
# In src/soothe/utils/lifecycle.py (new file)

def format_daemon_status_message(pid: str | None, action: str) -> str:
    """Format daemon lifecycle status message.

    Args:
        pid: Daemon PID (or None if not running)
        action: Action context (start, stop, exit, detach)

    Returns:
        Formatted message string
    """
    pid_str = pid or "?"
    if action == "start":
        return f"Daemon started (PID: {pid_str}). Use 'soothe daemon stop' to shutdown."
    elif action == "stop":
        return "Daemon stopped."
    elif action in ("exit", "detach"):
        return f"Client exited. Daemon running (PID: {pid_str}). Use 'soothe daemon stop' to shutdown."
    else:
        return f"Daemon running (PID: {pid_str})."
```

Use this helper in:
- `daemon_cmd.py` (start, stop, restart commands)
- `daemon.py` (headless exit)
- `app.py` (TUI exit messages)

### Phase 7: Documentation Updates

**Update CLI help text and examples**:

**File**: `src/soothe/ux/cli/main.py`

Update docstrings for `run_impl()`:

```python
def run_impl(...):
    """Core implementation for running Soothe agent.

    Args:
        prompt: Optional prompt for headless mode.
        ...

    Note:
        In headless mode (-p or --no-tui), the daemon auto-starts if not running
        and remains running after request completion. Use 'soothe daemon stop'
        to explicitly shutdown the daemon.

    Examples:
        soothe -p "analyze code"  # Daemon starts/persists
        soothe --no-tui           # TUI disabled, daemon persists
        soothe                    # TUI mode, daemon persists after exit
    """
```

**Update user guide** (if exists): `docs/user_guide.md`

Add section: "Daemon Lifecycle Management"

Explain:
- Daemon auto-start behavior
- Client exit vs daemon shutdown
- When daemon persists
- How to explicitly stop daemon

## Testing Plan

### Unit Tests

**Test File**: `tests/unit/test_daemon_lifecycle.py` (new)

Test cases:
1. `test_daemon_persists_after_headless_request`: Daemon running before → request → daemon still running after
2. `test_daemon_auto_starts_for_headless`: Daemon not running → auto-start → request → daemon running
3. `test_tui_exit_leaves_daemon_running`: Mock TUI exit → verify daemon still running
4. `test_double_ctrl_c_exits_client`: Mock Ctrl+C timing → verify client exit, daemon running
5. `test_single_ctrl_c_cancels_job`: Mock Ctrl+C → verify job cancelled, TUI stays
6. `test_thread_running_warning`: Mock running thread → verify warning modal shown
7. `test_explicit_daemon_stop`: Call `SootheDaemon.stop_running()` → verify daemon stopped

### Integration Tests

**Test File**: `tests/integration/test_daemon_client_sessions.py`

Test scenarios:
1. **Multi-session persistence**:
   - Start daemon
   - Run headless request A → daemon keeps running
   - Run headless request B → daemon keeps running
   - Run TUI session → exit TUI → daemon keeps running
   - Stop daemon explicitly → daemon stopped

2. **Client disconnect handling**:
   - Start daemon
   - Client connects → client disconnects → daemon still running
   - Another client connects → works fine

3. **Daemon auto-start**:
   - No daemon running
   - Run headless → daemon starts → request → daemon running
   - Run another headless → connects to same daemon

### Manual Testing Checklist

- [ ] **Non-TUI mode**:
  - [ ] Daemon not running → `soothe -p "test"` → daemon starts, runs request, keeps running
  - [ ] Daemon running → `soothe -p "test"` → uses existing daemon, keeps running
  - [ ] Show message: "Daemon running (PID: XXX)"
  - [ ] Check PID file exists after client exit

- [ ] **TUI mode**:
  - [ ] `/exit` → TUI exits, daemon keeps running, message shown
  - [ ] `/quit` → Same as `/exit`
  - [ ] `/detach` → Same as `/exit`
  - [ ] Ctrl+C once → Job cancelled, message "Press Ctrl+C again..."
  - [ ] Ctrl+C twice (within 1s) → TUI exits, daemon keeps running
  - [ ] Ctrl+C twice (after 1s) → Only cancels job twice, no exit
  - [ ] Thread running → `/exit` → Warning modal shown
  - [ ] Thread idle → `/exit` → No warning, immediate exit

- [ ] **Daemon lifecycle**:
  - [ ] `soothe daemon start` → Daemon starts, message shown
  - [ ] `soothe daemon stop` → Daemon stops, message shown
  - [ ] `soothe daemon status` → Shows correct PID/state
  - [ ] `soothe daemon restart` → Stops and starts, messages shown

## Verification Checklist

After implementation:

- [ ] All unit tests pass: `make test-unit`
- [ ] All integration tests pass: `make test-integration`
- [ ] Linting passes: `make lint` (zero errors)
- [ ] Formatting passes: `make format-check`
- [ ] Full verification: `./scripts/verify_finally.sh`
- [ ] RFC-0013 updated and validated
- [ ] RFC-0003 updated and validated
- [ ] User-facing messages clear and consistent
- [ ] Manual testing checklist completed

## Success Criteria

Implementation is successful when:

1. ✅ **Daemon persistence**: Daemon remains running across all client sessions
2. ✅ **Client exit**: `/exit`/`/quit`/`/detach` and double Ctrl+C exit client only
3. ✅ **Clear messaging**: Users see daemon PID and lifecycle state at all times
4. ✅ **No implicit shutdown**: Only `soothe daemon stop` shuts down daemon
5. ✅ **Thread warning**: TUI warns when exiting with running thread
6. ✅ **Auto-start seamless**: Daemon auto-start works without user friction
7. ✅ **All tests pass**: Unit, integration, and manual testing complete
8. ✅ **Backward compatible**: Existing workflows continue working

## Implementation Timeline

**Estimated Effort**: 2-3 days

**Breakdown**:
- Phase 1-2 (Non-TUI + TUI changes): 1 day
- Phase 3-4 (Commands + Daemon server): 0.5 day
- Phase 5-6 (Launcher + Messaging): 0.5 day
- Phase 7 (Documentation): 0.5 day
- Testing: 0.5 day

**Dependencies**: None (standalone implementation)

## Rollback Plan

If issues arise:

1. **Critical bug**: Revert changes, restore old behavior (`/exit` stops daemon)
2. **Minor bug**: Fix specific issue, keep new behavior
3. **User confusion**: Add clearer messaging, adjust behavior if needed

**Git Strategy**: Create feature branch `feature/daemon-lifecycle-polish`, merge after verification.

## Post-Implementation Tasks

After implementation complete:

1. Update RFC index if needed
2. Add implementation guide entry to docs/impl/ index
3. Update user guide with daemon lifecycle section
4. Consider future enhancements:
   - Configurable daemon idle timeout (optional RFC)
   - Client reconnect logic after daemon crash (future RFC)
   - Web UI daemon management dashboard (future RFC)

---

**Implementation Status**: Ready to begin Phase 1