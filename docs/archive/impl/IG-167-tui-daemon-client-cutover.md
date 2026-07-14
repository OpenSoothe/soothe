# Implementation Guide: TUI Daemon Client Cutover

**IG**: 167
**RFC**: RFC-400, RFC-402, RFC-606
**Title**: TUI Daemon Client Cutover
**Status**: In Progress
**Created**: 2026-04-14
**Dependencies**: RFC-000, RFC-001, RFC-400, RFC-402, RFC-606, IG-166

## Overview

Refactor the Textual TUI so the main interactive path talks directly to the
daemon over the websocket client instead of depending on a local graph object
for streaming and thread state.

The daemon becomes the runtime source of truth for:

- thread bootstrap and resume
- event streaming
- interrupt continuation
- thread state reads and writes
- thread listing and per-thread metadata

The TUI remains responsible for rendering, local widget state, and user input.

## Scope

### In Scope

- Add a dedicated daemon-backed TUI session layer
- Use daemon bootstrap for TUI startup
- Stream daemon `event` / `status` envelopes into the existing Textual renderer
- Add daemon protocol support for interactive HITL continuation
- Add daemon request/response support for thread state reads and writes
- Route thread APIs to the requesting client
- Replace local TUI history/state reads on the main path

### Out Of Scope

- Rewriting the widget layer
- Replacing the Textual UI layout
- Redesigning daemon transports beyond the websocket protocol additions needed here

## Design

### Client-side components

1. `TuiDaemonSession`
   - owns websocket connection lifecycle
   - runs daemon-ready + thread bootstrap
   - sends inputs, detach, interrupt continuation, and thread RPCs
   - reads daemon envelopes for the active turn

2. `execute_task_textual(..., daemon_session=...)`
   - consumes daemon websocket envelopes directly
   - preserves existing widget behavior for streamed text, tools, and protocol events
   - sends HITL continuation payloads back to the daemon

3. `SootheApp`
   - starts daemon-backed session on launch
   - loads thread history from daemon thread state
   - updates current thread state on switch/resume

### Daemon-side components

1. `MessageRouter`
   - handles direct client request/response RPCs for thread state and continuation
   - sends thread RPC responses only to the requesting client

2. `QueryEngine`
   - pauses for interactive interrupts when the client marks the turn as interactive
   - resumes execution from daemon-side continuation payloads

3. `SootheRunner`
   - exposes thread state read/write helpers
   - supports externally supplied interrupt continuation payloads for interactive daemon sessions

## Implementation Phases

### Phase 1: Session + Protocol Plumbing

- add TUI daemon session module
- add websocket client helpers for thread state and thread RPCs
- add daemon request IDs and client-scoped replies
- add interactive continuation message handling

### Phase 2: TUI Runtime Cutover

- switch TUI startup to daemon bootstrap
- stream daemon envelopes through Textual adapter
- replace history/state loading with daemon thread state
- wire detach and resume flow to the daemon session

### Phase 3: Cleanup

- remove obsolete adapter/bridge assumptions
- leave legacy local-agent path only where still needed for non-daemon test harnesses
- update or add focused tests for daemon-backed TUI flows

## Acceptance Criteria

- TUI launches against a running or auto-started daemon
- New-session startup yields a usable thread ID from daemon bootstrap
- Resumed sessions load history via daemon state, not local SQLite fallback
- User messages stream through daemon websocket envelopes into existing UI widgets
- Interactive approvals and `ask_user` continue via daemon messages
- Thread switch/resume uses daemon-owned thread state
- Thread list/get/messages responses are client-scoped
- `./scripts/verify_finally.sh` passes before any commit
