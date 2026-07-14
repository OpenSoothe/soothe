# IG-059: Thread Continue Resume And History Restoration

## Summary

This guide fixes `uv run soothe thread continue <thread_id>` so resume reuses the requested
thread instead of silently opening a new one, and restores prior chat history when the TUI
starts on an existing thread.

## Problem Statement

Observed behavior:

- `soothe thread continue <thread_id>` can fall through to `new_thread` when daemon resume
  returns `THREAD_NOT_FOUND`, masking the failure and changing the active thread unexpectedly.
- TUI startup resume consumes the initial daemon `status` event during handshake, but only the
  later event-loop path restores `conversation_history` and `input_history`.
- `soothe thread continue` without an explicit ID resolves the latest thread through a
  standalone runner even when a daemon is already running, so the selected thread can come from
  a different persistence context than the daemon-backed TUI session.

## Scope

In scope:

- TUI startup resume handling in `src/soothe/ux/tui/app.py`.
- CLI "continue latest thread" resolution in `src/soothe/ux/cli/commands/thread_cmd.py`.
- Regression tests for explicit resume, startup history restoration, and missing-thread errors.

Out of scope:

- Changing daemon durability semantics.
- Reworking the thread logger storage model.
- Altering `SootheRunner` fallback behavior outside the CLI/TUI resume surface.

## Target Behavior

1. Explicit `soothe thread continue <thread_id>` must either:
   - resume the requested thread and keep that thread ID active, or
   - fail clearly if the daemon cannot resume it.
2. Startup resume must restore:
   - `input_history` into `ChatInput`,
   - `conversation_history` into the conversation panel.
3. When a daemon is already running, `soothe thread continue` with no ID should select the
   latest active thread from the daemon rather than a separate standalone runner.

## Implementation Plan

1. Add a shared TUI helper that applies thread switch/resume status state consistently.
2. Use that helper for both:
   - the initial post-connect `status` event,
   - normal event-loop `status` events.
3. Replace the startup `THREAD_NOT_FOUND -> send_new_thread()` fallback with a visible error and
   early return for explicit resume requests.
4. Resolve the latest active thread via `DaemonClient.send_thread_list()` when a daemon is
   already running; keep standalone lookup when no daemon exists.
5. Add regression tests for:
   - startup resume history rendering,
   - explicit resume failure not calling `send_new_thread`,
   - latest-thread lookup using daemon thread listing.

## Verification Checklist

- `uv run soothe thread continue <thread_id>` reuses the requested thread when it exists.
- Missing thread resume surfaces an error instead of silently opening a new draft thread.
- Resumed TUI sessions show earlier user and assistant turns immediately on startup.
- `uv run soothe thread continue` chooses the latest active daemon thread when a daemon is
  running.
- `./scripts/verify_finally.sh` passes.
