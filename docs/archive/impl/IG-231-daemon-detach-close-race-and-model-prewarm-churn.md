# IG-231 Daemon Detach Close-Race and Model Prewarm Churn

## Context

Detach/resume sessions show two additional reliability issues:

1. Daemon logs emit ERROR on expected WebSocket close races right after detach.
2. TUI startup/prewarm opens extra WebSocket connections and logs repeated provider-fetch failures.

## Root Causes

1. `WebSocketTransport.send()` treats all send failures as fatal and logs exception stack traces, including expected `ConnectionClosedOK` during graceful client disconnect.
2. `_prewarm_model_caches()` always invokes model discovery helpers that open standalone WebSocket clients, even when TUI already uses a daemon session (or before daemon session is established).
3. Provider credential helpers in `model_config.py` use `asyncio.run(...)` unconditionally, which is unsafe when called from an active event loop.

## Goals

1. Suppress/downgrade expected close-race noise while preserving real send errors.
2. Avoid redundant WebSocket connections from model prewarm in daemon-backed TUI.
3. Make provider helper RPC fallback safe under active event loops.

## Implementation Plan

1. In daemon transport send path, detect `ConnectionClosed*` and log at debug level.
2. In TUI prewarm, skip daemon-side model prewarm until a daemon session exists.
3. In model config helpers, only use `asyncio.run(...)` when no loop is running.

## Validation

1. Verify no regressions in TUI startup and detach/resume flow.
2. Confirm daemon logs no longer show ERROR for graceful close race after detach.
3. Confirm model prewarm no longer creates extra daemon connection churn in daemon-backed startup.
