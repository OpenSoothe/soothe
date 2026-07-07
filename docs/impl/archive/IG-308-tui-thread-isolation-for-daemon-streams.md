# IG-308 TUI Thread Isolation for Daemon Streams

## Context

TUI users can see cancellation and streaming output from a different thread than
the one currently displayed in the session. This causes messages like
`Interrupted by user` / cancellation notices to appear after the wrong query.

## Root Cause

The daemon stream consumer (`TuiDaemonSession.iter_turn_chunks`) reads from a
single websocket queue and does not filter events by the active thread ID.
When stale events for another subscribed/running thread are present, they are
processed in the current thread context.

## Implementation Plan

1. Add strict thread-ID filtering inside `iter_turn_chunks` so mismatched
   thread events are ignored before status/message processing.
2. Keep status handling for the active thread unchanged (running/idle
   lifecycle), while avoiding state transitions from other threads.
3. Add unit coverage for mixed-thread event streams to ensure only active
   thread chunks are yielded.

## Expected Outcome

- Cancellation/interruption notices render adjacent to the cancelled query.
- Streaming content from unrelated threads no longer appears in the current
  thread view.
