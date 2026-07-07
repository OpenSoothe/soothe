# IG-489: Include Daemon Readiness State in Status Response

## Problem

The TUI fails with `TimeoutError` when connecting to a daemon that is "running" but still in "warming" state:

1. `soothe status` calls `is_daemon_live()` → checks only `running`/`port_live` → succeeds
2. TUI calls `is_daemon_live()` → succeeds (daemon process is alive)
3. TUI creates `TuiDaemonSession` → waits for `daemon_ready` event with `"ready"` state
4. Daemon is still warming (loading MCP servers, initializing runners) → 20s timeout expires → `TimeoutError`

## Root Cause

`daemon_status_response` (router.py:634-641) does NOT include `_readiness_state`. The liveness check
only validates process/port status, not the daemon's internal readiness state (`"starting"`, `"warming"`,
`"ready"`, `"error"`, `"degraded"`, `"stopped"`).

## Solution

### 1. Add `readiness_state` to `daemon_status_response`

**File**: `packages/soothe-daemon/src/soothe_daemon/protocol/router.py`

In `_handle_daemon_status()` (line 608-643), add:
```python
response = {
    "type": "daemon_status_response",
    "request_id": request_id,
    "running": running,
    "port_live": port_live,
    "active_threads": active_threads,
    "daemon_pid": os.getpid() if running else None,
    "readiness_state": d._readiness_state,  # NEW
    "readiness_message": d._readiness_message,  # NEW
}
```

### 2. Update `_daemon_status_indicates_live()` to check readiness

**File**: `packages/soothe-sdk/src/soothe_sdk/client/helpers.py`

Modify `_daemon_status_indicates_live()` (line 91-100):
```python
def _daemon_status_indicates_live(status: dict) -> bool:
    """Infer liveness from a ``daemon_status_response`` payload.

    Now considers readiness_state: transitional states (starting, warming)
    indicate the daemon is not yet ready to handle loops.
    """
    # Check readiness_state first (new field)
    readiness_state = status.get("readiness_state")
    if readiness_state:
        # Transitional states mean daemon is not ready
        if readiness_state in {"starting", "warming"}:
            return False
        # Terminal error states
        if readiness_state in {"error", "degraded", "stopped"}:
            return False
        # Only "ready" is truly live for loop operations
        if readiness_state == "ready":
            return True
        # Unknown state - fall through to legacy check

    # Legacy check (for older daemons without readiness_state)
    if "running" in status:
        return bool(status["running"])
    return bool(status.get("port_live", True))
```

### 3. Add optional `wait_for_ready` parameter to `is_daemon_live()`

**File**: `packages/soothe-sdk/src/soothe_sdk/client/helpers.py`

For TUI and headless callers that need to wait for full readiness:
```python
async def is_daemon_live(
    ws_url: str,
    timeout: float = 5.0,
    wait_for_ready: bool = False,
    ready_timeout: float = 30.0,
) -> bool:
    """Check daemon liveness, optionally waiting for ready state.

    Args:
        ws_url: WebSocket URL to check
        timeout: Per-request timeout for status RPC
        wait_for_ready: If True, poll until daemon is "ready" (not "starting"/"warming")
        ready_timeout: Max seconds to wait for ready state when wait_for_ready=True

    Returns:
        True if daemon is live (and ready if wait_for_ready=True), False otherwise
    """
```

### 4. Update TUI to use `wait_for_ready=True`

**File**: `packages/soothe-cli/src/soothe_cli/tui/app/_startup.py`

Change line 445:
```python
daemon_live = await is_daemon_live(ws_url, timeout=5.0, wait_for_ready=True, ready_timeout=30.0)
```

### 5. Update headless execution to use `wait_for_ready=True`

**File**: `packages/soothe-cli/src/soothe_cli/cli/execution/headless.py`

Change lines 45 and 70 to use `wait_for_ready=True`.

## Files Changed

| Package | File | Change |
|---------|------|--------|
| soothe-daemon | `protocol/router.py` | Add `readiness_state`, `readiness_message` to response |
| soothe-sdk | `client/helpers.py` | Update `_daemon_status_indicates_live()`, add `wait_for_ready` param |
| soothe-cli | `tui/app/_startup.py` | Use `wait_for_ready=True` |
| soothe-cli | `cli/execution/headless.py` | Use `wait_for_ready=True` |
| soothe-sdk | `tests/unit/test_helpers_daemon_live.py` | Add tests for readiness_state |

## Testing

1. Unit tests for `_daemon_status_indicates_live()` with new `readiness_state` field
2. Integration test verifying daemon_status_response includes readiness fields
3. Manual test: start daemon, immediately run `soothe` TUI — should wait for ready, not timeout

## Backward Compatibility

- Older daemons (without `readiness_state` in response) fall back to `running`/`port_live` check
- New clients work with old daemons (missing field handled)
- Old clients work with new daemons (extra fields ignored)