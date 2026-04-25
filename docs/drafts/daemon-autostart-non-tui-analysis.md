# Daemon Auto-Start Issue in Non-TUI Mode - Analysis

**Created**: 2026-03-28
**Status**: Critical Bug
**Related**: RFC-400, IG-085

## Problem Statement

When running `soothe -p "prompt"` in non-TUI mode and the daemon is NOT running:
- The command runs in **standalone mode** (single process)
- Ctrl+C kills the entire process
- **No daemon persists** because it was never started

This violates RFC-400 daemon lifecycle semantics which state:
> "If daemon not running: Start daemon, connect, create thread, execute request"

## Current Behavior (INCORRECT)

### Flow in `run_headless()` (headless.py lines 36-63)

```python
def run_headless(cfg, prompt, ...):
    if SootheDaemon.is_running():
        # Use existing daemon
        exit_code = asyncio.run(run_headless_via_daemon(...))
    else:
        # BUG: Runs in standalone mode!
        # No daemon started, no persistence
        exit_code = asyncio.run(run_headless_standalone(...))

    sys.exit(exit_code)
```

**Problems**:
1. No daemon auto-start
2. Falls back to standalone mode
3. Standalone = single process, killed by Ctrl+C
4. No daemon persistence

## Expected Behavior (RFC-400)

```
User runs: soothe -p "query"
  ↓
Check daemon status
  ↓
If NOT running:
  → Auto-start daemon in background
  → Wait for daemon to initialize
  ↓
Connect to daemon
  ↓
Execute request
  ↓
Client exits, daemon persists
```

## Root Cause

The code was designed with the assumption that:
- TUI mode auto-starts daemon
- Non-TUI mode should use standalone if daemon not running

**This is incorrect** according to RFC-400:
- **Both TUI and non-TUI should auto-start daemon**
- Daemon should ALWAYS persist after request
- Only `soothed stop` should kill daemon

## Solution

### Change `run_headless()` to Auto-Start Daemon

**File**: `src/soothe/ux/cli/execution/headless.py`

```python
def run_headless(
    cfg: SootheConfig,
    prompt: str,
    *,
    thread_id: str | None = None,
    output_format: str = "text",
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> None:
    """Run a single prompt with streaming output and progress events.

    Connects to running daemon if available to avoid RocksDB lock conflicts.
    Auto-starts daemon if not running (RFC-400 daemon lifecycle).
    """
    import asyncio
    import time

    from soothe.ux.cli.execution.daemon import run_headless_via_daemon

    # Auto-start daemon if not running (RFC-400)
    if not SootheDaemon.is_running():
        typer.echo("[lifecycle] Starting daemon...", err=True)
        from soothe.ux.cli.commands.daemon_cmd import daemon_start

        daemon_start(config=None, foreground=False)
        # Wait for daemon to initialize
        for _ in range(50):  # Wait up to 10 seconds
            time.sleep(0.2)
            if SootheDaemon.is_running():
                break
        else:
            typer.echo("Error: Failed to start daemon", err=True)
            sys.exit(1)

    # Connect to daemon and execute
    exit_code = asyncio.run(
        run_headless_via_daemon(
            cfg,
            prompt,
            thread_id=thread_id,
            output_format=output_format,
            autonomous=autonomous,
            max_iterations=max_iterations,
        )
    )
    sys.exit(exit_code)
```

**Key Changes**:
1. Remove standalone fallback
2. Auto-start daemon if not running
3. Wait for daemon initialization
4. Always use daemon mode

### Remove Standalone Mode

**Decision**: Should we remove `run_headless_standalone()` entirely?

**Option A**: Remove completely
- Pro: Simpler code, consistent behavior
- Con: Requires daemon for all non-TUI operations

**Option B**: Keep as fallback for edge cases
- Pro: Works even if daemon fails to start
- Con: More complex, inconsistent lifecycle

**Recommendation**: **Option A** - Remove standalone mode entirely

**Rationale**:
- RFC-400 specifies daemon-centric architecture
- Daemon provides thread persistence, multi-client support
- Standalone mode defeats the purpose of daemon lifecycle
- Simpler mental model: "Daemon always runs"

## Impact Analysis

### What Changes

**Before**:
- `soothe -p "query"` (daemon not running) → standalone → no persistence
- `soothe -p "query"` (daemon running) → daemon → persistence

**After**:
- `soothe -p "query"` (daemon not running) → auto-start daemon → persistence
- `soothe -p "query"` (daemon running) → use daemon → persistence

### Benefits

1. **Consistent daemon lifecycle**: Daemon always persists
2. **Thread persistence**: Threads can be resumed later
3. **Multi-client support**: Multiple clients can connect
4. **Simpler code**: No standalone mode complexity

### Risks

1. **Daemon startup time**: Adds ~2-5 seconds for first query
2. **Resource usage**: Daemon runs in background continuously
3. **Daemon failures**: If daemon fails, non-TUI mode won't work

## Implementation Plan

### Phase 1: Update headless.py
- Add daemon auto-start logic
- Remove standalone fallback
- Update docstrings

### Phase 2: Testing
- Test daemon auto-start
- Test Ctrl+C during query (daemon should persist)
- Test multiple sequential queries

### Phase 3: Documentation
- Update RFC-400 if needed
- Update user guide
- Add to changelog

## Verification

After implementation, verify:

```bash
# Start fresh (no daemon running)
rm -rf ~/.soothe/*.pid ~/.soothe/*.sock

# Run non-TUI query
soothe -p "hello"

# Daemon should be running now
soothed status

# Ctrl+C during query should NOT kill daemon
soothe -p "long running task..."
# Press Ctrl+C
soothed status  # Should still be running

# Explicit stop required
soothed stop
```

## References

- RFC-400: Daemon Lifecycle Semantics
- IG-085: Daemon Lifecycle Polish Implementation
- `src/soothe/ux/cli/execution/headless.py`
- `src/soothe/ux/cli/execution/standalone.py`