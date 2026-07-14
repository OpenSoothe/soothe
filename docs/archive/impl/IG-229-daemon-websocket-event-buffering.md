# IG-229 Daemon WebSocket Event Buffering

## Context

When the TUI resumes a running daemon thread, thread execution continues on the daemon, but live event updates can disappear on the client. The daemon logs show events are emitted and sent, yet the UI does not always receive progressive updates.

## Root Cause

`WebSocketClient.request_response()` in `soothe_sdk.client.websocket` reads directly from the same socket stream used for live events. While waiting for a specific `request_id`, it currently discards every non-matching frame. This can drop `event` and `status` messages needed by `iter_turn_chunks()`.

## Goals

1. Preserve live stream frames while RPC-style calls wait for responses.
2. Keep message ordering stable for non-consumed frames.
3. Apply the same safeguard to `wait_for_daemon_ready()` and `wait_for_subscription_confirmed()`.

## Implementation Plan

1. Add an in-memory pending event queue to `WebSocketClient`.
2. Make `read_event()` consume pending events first, then socket frames.
3. Update response waiters to:
   - search pending events for a match first;
   - read new frames until match;
   - enqueue non-matching frames instead of dropping them.

## Validation

1. Run targeted SDK/client tests if available.
2. Run daemon/TUI resume scenario and confirm:
   - `resume_thread` + `subscribe_thread` still complete;
   - background `event` frames continue to appear during RPC calls.
