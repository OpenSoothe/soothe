# IG-233 TUI Background Update Payload Unwrapping

## Context

After resume, history now recovers correctly, but TUI background progress can still appear silent.

## Root Cause

`_consume_daemon_events_background()` assumes `updates` chunk `data` is always a flat event dict with a top-level `type`. In practice, update payloads may be wrapped (for example keyed by node/state), so the current pipeline call sees no event type and emits nothing.

## Goals

1. Parse wrapped `updates` payloads in background mode.
2. Feed a canonical event dict into `StreamDisplayPipeline`.
3. Render progress lines for both direct and wrapped update payloads.

## Implementation Plan

1. In background consumer, keep only `updates` mode.
2. If `data` has top-level `type`, process directly.
3. Otherwise, inspect first dict value and process it when it contains `type`.

## Validation

1. Compile-check updated TUI app module.
2. Resume a running thread and verify background progress lines appear.
