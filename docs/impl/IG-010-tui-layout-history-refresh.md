# Textual TUI and Daemon Implementation

**Guide**: IG-010
**Title**: Textual TUI and Daemon Implementation
**Created**: 2026-03-13
**Related RFCs**: RFC-500
**Supersedes**: Original IG-010 (TUI Layout, Streaming, and Reviewable History Refresh)

## Overview

This guide documents the implementation of the new Textual-based TUI and daemon architecture for Soothe, as specified in RFC-500. The implementation replaces the Rich Live-based stack with a daemon process that serves events over a Unix domain socket, a Textual TUI client that connects to the daemon, and a headless client for single-prompt execution.

## Prerequisites

- [x] RFC-000 accepted (System Conceptual Design)
- [x] RFC-001 accepted (Core Modules Architecture Design)
- [x] RFC-500 accepted (CLI TUI Architecture Design)
- [x] IG-007 completed (CLI TUI Implementation)

## Module Scope

This guide covers the following modules:

| Module | Purpose |
|--------|---------|
| `src/soothe/cli/daemon.py` | SootheDaemon, DaemonClient, IPC protocol |
| `src/soothe/cli/tui_app.py` | SootheApp (Textual TUI) |
| `src/soothe/cli/main.py` | CLI commands, _run_tui, _run_headless |
| `src/soothe/cli/commands.py` | Slash commands, subagent routing |
| `src/soothe/cli/tui_shared.py` | Shared TUI state/render helpers for Textual app and commands |

## Daemon Implementation

### SootheDaemon Class

The daemon wraps `SootheRunner` and accepts TUI/headless clients over a Unix domain socket.

**Key responsibilities:**
- Socket server loop: `asyncio.start_unix_server()` on `~/.soothe/soothe.sock`
- Client connection handling: `_handle_client()` accepts connections, reads newline-delimited JSON
- Event serialization: `_encode()` / `_decode()` for JSON lines
- Broadcast: all connected clients receive events; `_broadcast()` sends to all, removes dead clients
- Input queue: `_current_input_queue` with latest-client-wins semantics (single input consumer)

**Lifecycle:**
- `start()`: Create socket, start server, write PID file, broadcast initial status
- `serve_forever()`: Run until SIGTERM/SIGINT; spawns `_input_loop()` task
- `stop()`: Broadcast stopped status, close clients, close server, remove socket, cleanup PID

**PID file:**
- Path: `~/.soothe/soothe.pid`
- Written on start; removed on stop
- `is_running()`: Check PID file and `os.kill(pid, 0)` to verify process
- `stop_running()`: Send SIGTERM to PID from file

**Graceful shutdown:**
- SIGTERM and SIGINT handlers set `stop_event`
- `_input_loop()` cancelled on shutdown
- `stop()` called in `finally` block

### DaemonClient Class

Async client for TUI and headless connections to the daemon.

**Methods:**
- `connect()`: `asyncio.open_unix_connection()` to socket path
- `close()`: Close writer, wait for closed
- `send_input(text)`: Send `{"type": "input", "text": "..."}`
- `send_command(cmd)`: Send `{"type": "command", "cmd": "/help"}`
- `send_detach()`: Send `{"type": "detach"}`
- `read_event()`: Read next newline-delimited JSON; returns dict or None on EOF

### Input Queue Semantics

- Single `asyncio.Queue` for all client input
- Any connected client can send `input` or `command`; messages are queued
- `_input_loop()` consumes from queue; processes commands (e.g. `/exit` stops daemon) or runs query via `_run_query()`
- Latest-client-wins: multiple clients can send input; all are queued and processed sequentially

## Textual App Implementation

### SootheApp (App)

Textual application with a vertical three-row layout.

**Widget hierarchy:**
- `Header` — App title with keyboard shortcuts subtitle
- `ConversationPanel` (id=conversation) — RichLog with border, user turns plus final main-assistant response text (4fr height)
- `ActivityInfo` (id=activity-info) — Static, compact borderless display showing last 5 activity lines
- `PlanTree` (id=plan-tree) — Static, borderless plan tree display, toggleable with Ctrl+T (max 15 lines)
- `InfoBar` (id=info-bar) — Static, thread/events/state + compact subagent status (docked at bottom)
- `ChatInput` (id=chat-input) — Input, placeholder "soothe> Type a message or /help" (height: 6)

**CSS layout:**
- `#main-layout`: vertical layout
- `#conversation-row`: conversation panel (4fr height, with border)
- `#info-row`: vertical container for activity info and plan tree (auto height)
- `#activity-info`: last 5 activity lines, borderless (max 5 lines)
- `#plan-tree`: plan tree display, borderless, collapsible (max 15 lines)
- `#info-bar`, `#chat-input`: dock bottom

### Event Handling: Daemon Event → Widget Update

| Daemon message | Handler | Widget update |
|----------------|---------|---------------|
| `type: status` | `process_daemon_event` | InfoBar (state, thread_id); end-of-turn conversation flush when state returns to idle/stopped |
| `type: event`, mode=messages | `handle_messages_event` | ConversationPanel (final main-assistant response text), ActivityInfo (tool calls + subagent text summaries) |
| `type: event`, mode=custom, soothe.* | `_handle_protocol_event` | ActivityInfo, PlanTree (if plan.*) |
| `type: event`, mode=custom, subagent | `_handle_subagent_custom` | ActivityInfo |

**Shared state:** `TuiState` from `tui_shared.py` holds `full_response`, `activity_lines`, `current_plan`, `subagent_tracker`, `thread_id`, `plan_visible`, etc. The Textual app reuses `_handle_protocol_event`, `_handle_subagent_custom`, `_add_activity`, `render_plan_tree` from the shared helper module.

**Message surfacing rules:**
- ConversationPanel is low-noise by design: it shows user turns and final main-assistant response text only.
- ActivityInfo shows the last 5 lines of activity (protocol events, tool activity, subagent custom events, and non-main/subagent text summaries).
- Policy activity lines include `profile` context when present (e.g., `allow (profile=standard)`).
- Browser progress is surfaced through structured `browser_step` events; raw browser-use stdout/stderr is suppressed.

**Activity display:**
- ActivityInfo is updated by `_flush_new_activity()` which renders the last 5 lines from `state.activity_lines` as a Static widget.
- PlanTree is updated by `_refresh_plan()` which renders the plan tree to a string using Rich Console.

### Connection Management

- **Auto-start daemon:** `_ensure_daemon()` checks `SootheDaemon.is_running()`; if not, spawns `soothe daemon start` via subprocess, polls for socket existence (up to 5 seconds)
- **Reconnection:** On `read_event()` returning None (EOF), app sets `_connected = False` and displays "Daemon connection closed"; no automatic reconnect in current implementation

## CLI Integration

### New Commands

| Command | Implementation |
|---------|----------------|
| `soothe attach` | Check daemon running; launch Textual TUI (no auto-start) |
| `soothe daemon start` | Start daemon; `--foreground` runs in current process |
| `soothe daemon stop` | `SootheDaemon.stop_running()` sends SIGTERM |
| `soothe daemon status` | `SootheDaemon.is_running()` + PID from file |
| `soothe init` | Create `~/.soothe/config`, `sessions`, `generated_agents`, `logs`; copy config template |

### Expanded Thread Management

| Command | Implementation |
|--------|----------------|
| `soothe thread inspect <id>` | List threads, find match, show details + ThreadLogger stats |
| `soothe thread delete <id>` | Archive + delete thread file; `--yes` skips confirm |
| `soothe thread export <id>` | ThreadLogger.read_recent_records; output jsonl or md |

### Headless Mode

- `_run_headless(cfg, prompt, thread_id, output_format)` uses `SootheRunner.astream()` directly (no daemon)
- `--format jsonl`: Each stream chunk written as JSON line to stdout
- `--format text` (default): Protocol events to stderr via `_render_progress_event()`; main-assistant text to stdout
- `progress_verbosity` applies to both headless text output and TUI activity rendering
- Policy progress lines include profile context when available

## Migration Notes

- **Textual-only TUI:** `tui_app.py` is the single interactive TUI implementation.
- **Shared components:** `TuiState`, `SubagentTracker`, `_add_activity`, `_handle_protocol_event`, `_handle_subagent_custom`, `_handle_subagent_text_activity`, and `render_plan_tree` live in `tui_shared.py`.
- **Stream handlers:** The Textual TUI consumes `SootheRunner.astream()` via daemon IPC (events serialized/deserialized).

## Testing Strategy

### Unit Tests

- **Daemon protocol:** Encode/decode round-trip; message type parsing
- **DaemonClient:** Mock socket; verify send/read formats
- **SootheDaemon.is_running/stop_running:** PID file presence, stale PID handling

### Integration Tests

- **TUI lifecycle:** Start daemon, connect client, send input, receive events, disconnect
- **Headless jsonl:** Run with `--format jsonl`, assert valid JSON lines on stdout

### Regression Tests

- Thread resume semantics
- Durability create/resume/archive flows
- Slash command handling in Textual TUI

## Verification Checklist

- [ ] Daemon starts on `soothe run` when not running
- [ ] `soothe attach` connects to running daemon
- [ ] `soothe daemon start|stop|status` work correctly
- [ ] `soothe init` creates ~/.soothe structure
- [ ] Textual TUI displays conversation panel, activity info, and plan tree in vertical layout
- [ ] Conversation panel has border and shows final main-assistant responses (plus user turns)
- [ ] Activity info shows last 5 activity lines without border
- [ ] Plan tree shows hierarchical plan without border and can be toggled with Ctrl+T
- [ ] Chat input has height of 6 for better usability
- [ ] Events from daemon update correct widgets
- [ ] Policy progress lines include profile context in TUI/headless text rendering
- [ ] Raw browser-use stdout/stderr is suppressed while browser progress remains visible via structured activity events
- [ ] Slash commands (e.g. /help, /detach) work
- [ ] Headless `--format jsonl` emits valid JSONL
- [ ] Textual TUI launch path works end-to-end
- [ ] `ruff check` passes on touched files
- [ ] Targeted CLI/daemon tests pass

## Related Documents

- [RFC-500](../specs/RFC-500-cli-tui-architecture.md) - CLI TUI Architecture Design
- [RFC-000](../specs/RFC-000-system-conceptual-design.md) - System Conceptual Design
- [RFC-001](../specs/RFC-001-core-modules-architecture.md) - Core Modules Architecture Design
- [IG-007](./007-cli-tui-implementation.md) - CLI TUI Implementation
