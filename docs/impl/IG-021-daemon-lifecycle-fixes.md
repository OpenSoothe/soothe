# IG-021: Daemon Lifecycle, Singleton Enforcement, and Headless Hang Fixes

## Objective

Fix three interconnected daemon bugs that prevent reliable CLI usage:
1. Daemon ignores SIGTERM so `soothe-daemon stop` fails.
2. Multiple daemon processes can run simultaneously (should be singleton).
3. `soothe run --no-tui` hangs when a daemon is running.

## Scope

- Daemon stop reliability (SIGTERM handling, cleanup timeouts, SIGKILL escalation).
- Singleton enforcement via file lock on PID file.
- Non-blocking runner initialization in daemon context.
- Headless client resilience (timeouts, fallback without RocksDB conflicts).

## Non-Goals

- No protocol changes.
- No changes to TUI streaming (only headless/`--no-tui` path).
- No changes to agent logic, tools, or subagents.

## Root Cause Analysis

### Bug 1: `server stop` fails

`_run_query` catches `Exception` broadly (line 443 in daemon.py), which swallows
`asyncio.CancelledError` on Python 3.11 (where `CancelledError` is not a subclass
of `Exception` but _is_ caught during task cancellation unwinding). After the
`finally` block resets `_query_running`, execution continues to lines 458-462 which
broadcast "idle" -- this broadcast can hang if the socket is being torn down.

`stop_running()` sends SIGTERM and polls for 5s, but returns `True` even on timeout
with no SIGKILL escalation, so the daemon process survives.

### Bug 2: Multiple daemons

`server_start` checks `SootheDaemon.is_running()` then spawns a subprocess. The
PID file is written inside the subprocess after `SootheRunner` init (~2s), leaving
a race window. Also, `start()` unconditionally unlinks any existing socket, stealing
it from a live daemon.

### Bug 3: `--no-tui` hangs

When daemon is detected, headless mode connects via DaemonClient. But:
- Daemon may block the event loop during SootheRunner init (sync, ~2s).
- `_input_loop` serializes queries; a stuck prior query blocks new ones.
- Standalone fallback hangs on RocksDB lock held by the daemon.

## Design

### 1) Daemon stop reliability

- In `_run_query`, re-raise `asyncio.CancelledError` after the `finally` cleanup
  instead of falling through to the idle broadcast.
- Wrap `runner.cleanup()` in `asyncio.wait_for()` with a 3s timeout in `stop()`.
- In `stop_running()`, escalate to SIGKILL after timeout and clean up PID/socket.

### 2) Singleton enforcement

- Write PID file *before* the long `SootheRunner` init, immediately at daemon
  subprocess entry.
- Use `fcntl.flock(LOCK_EX | LOCK_NB)` on the PID file as the authoritative
  singleton guard.
- In `start()`, do not unlink an existing socket if a live daemon owns it.

### 3) Headless hang fix

- Run `SootheRunner(config)` via `await asyncio.to_thread(SootheRunner, config)`
  so the event loop stays responsive during init.
- In `_run_headless_via_daemon`, handle `soothe.error` events received before
  the `"running"` status as query failures (exit code 1, not fallback 42).
- In standalone fallback, force json durability backend to avoid RocksDB lock
  conflicts with the daemon.

## Files

- `src/soothe/cli/daemon.py` -- stop reliability, singleton lock, async init
- `src/soothe/cli/main.py` -- headless fallback, standalone durability override

## Validation

- `soothe-daemon stop` terminates daemon within 10s.
- `soothe-daemon start` twice prints "already running" on second attempt.
- `soothe run --no-tui "who are you"` completes (not hangs) when daemon is running.
- `soothe run --no-tui "who are you"` completes when no daemon is running.
