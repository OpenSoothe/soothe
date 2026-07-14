# IG-232 TUI Daemon Session RPC/Stream Separation

## Context

After `resume_thread`, the TUI may fail to recover history messages/events while the thread keeps running. Streaming and RPC calls currently share one WebSocket client and one read lock.

## Root Cause

`iter_turn_chunks()` keeps the read lock while continuously consuming stream events. Concurrent RPC calls (`thread_state`, `thread_messages`, `thread_update_state`, `list_models`, etc.) block behind that lock, delaying or preventing history recovery.

## Goals

1. Separate stream consumption and RPC request/response paths.
2. Allow history/state RPCs to run while background streaming is active.
3. Keep existing daemon protocol and behavior unchanged.

## Implementation Plan

1. Add a dedicated RPC `WebSocketClient` in `TuiDaemonSession`.
2. Add lazy RPC connect helper with its own lock.
3. Route RPC methods to the RPC client while keeping stream reads on the stream client.
4. Close both clients on session shutdown.

## Validation

1. Compile-check updated module.
2. Verify detach/resume path can fetch history without waiting for stream reader to stop.
