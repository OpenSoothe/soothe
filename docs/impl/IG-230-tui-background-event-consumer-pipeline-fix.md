# IG-230 TUI Background Event Consumer Pipeline Fix

## Context

After `detach` + `resume_thread`, the daemon continues running and emits events, but the TUI can stop showing updates. The background consumer crashes shortly after re-attach.

## Root Cause

`SootheApp._consume_daemon_events_background()` calls `StreamDisplayPipeline.process_chunk(...)`, but `StreamDisplayPipeline` exposes `process(event)` only. This raises:

- `'StreamDisplayPipeline' object has no attribute 'process_chunk'`

Once this exception is raised, the background event consumer stops and no further passive progress updates are rendered.

## Goals

1. Keep the background consumer alive after detach/resume.
2. Route daemon `updates` events through the existing pipeline API correctly.
3. Ignore non-progress chunk modes safely.

## Implementation Plan

1. Replace the invalid `process_chunk(...)` call with `process(event_dict)`.
2. Convert background `(namespace, mode, data)` chunks into event dicts only for `updates` payloads.
3. Render resulting `DisplayLine` values into TUI messages.

## Validation

1. Run targeted soothe-cli unit tests for stream/pipeline display behavior.
2. Re-run detach/resume flow and verify:
   - no background consumer crash;
   - progress events continue rendering while thread is running.
