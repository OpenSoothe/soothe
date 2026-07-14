# IG-236 Daemon Ready Pending Queue Deadlock Fix

## Context

After IG-229 introduced pending-event buffering in `WebSocketClient`, headless CLI startup (`soothe --no-tui`) can hang before query execution begins.

## Root Cause

`wait_for_daemon_ready()` consumes via `read_event()`, which prioritizes `_pending_events`.  
When the first pending frame is not `daemon_ready`, the method appends it back into `_pending_events` and loops. That same frame is popped again immediately on the next iteration, causing an infinite in-memory cycle that never returns to socket reads.

## Fix

1. Add a helper to search `_pending_events` for a matching message type while preserving order of non-matching events.
2. Update `wait_for_daemon_ready()` to:
   - first consume a matching pending `daemon_ready` event if present;
   - otherwise read directly from socket (`_read_from_socket`) and enqueue unrelated frames.

## Validation

1. Run targeted SDK unit tests covering websocket client behavior.
2. Verify headless CLI no longer hangs:
   - `uv run soothe --no-tui -p "read 10 lines of project readme"`
