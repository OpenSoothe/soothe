# Textual TUI and Daemon Implementation

**Guide**: IG-010
**Title**: Textual TUI and Daemon Implementation
**Created**: 2026-03-13
**Related RFCs**: RFC-0003
**Supersedes**: Original IG-010 (TUI Layout, Streaming, and Reviewable History Refresh)

## Overview

This guide documents the implementation of the new Textual-based TUI and daemon architecture for Soothe, as specified in RFC-0003. The implementation replaces the Rich Live-based stack with a daemon process that serves events over a Unix domain socket, a Textual TUI client that connects to the daemon, and a headless client for single-prompt execution.

## Prerequisites

- [x] RFC-0001 accepted (System Conceptual Design)
- [x] RFC-0002 accepted (Core Modules Architecture Design)
- [x] RFC-0003 accepted (CLI TUI Architecture Design)
- [x] IG-007 completed (CLI TUI Implementation)

## Module Scope

This guide covers the following modules:

| Module | Purpose |
|--------|---------|
| `src/soothe/cli/daemon.py` | SootheDaemon, DaemonClient, IPC protocol |
| `src/soothe/cli/tui_app.py` | SootheApp (Textual TUI) |
| `src/soothe/cli/main.py` | CLI commands, _run_tui, _run_headless |
| `src/soothe/cli/commands.py` | Slash commands, subagent routing |
| `src/soothe/cli/tui.py` | Legacy Rich TUI fallback, TuiState, render helpers |

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

Textual application with CSS grid layout.

**Widget hierarchy:**
- `Header` — App title
- `ConversationPanel` (id=conversation) — RichLog, full-width, scrollable chat
- `PlanPanel` (id=plan-panel) — RichLog, plan tree
- `SubagentPanel` (id=subagent-panel) — RichLog, subagent status
- `ActivityPanel` (id=right-sidebar) — RichLog, activity lines
- `StatusBar` (id=status-bar) — Static, thread/events/state
- `ChatInput` (id=chat-input) — Input, placeholder "soothe> Type a message or /help"
- `Footer` — Key bindings

**CSS layout:**
- `#main-layout`: grid 2x2, columns 3fr 2fr, rows 3fr 2fr
- `#conversation`: row-span 1, column-span 2
- `#left-sidebar`: Plan + Subagent stacked
- `#right-sidebar`: Activity panel
- `#status-bar`, `#chat-input`: dock bottom

### Event Handling: Daemon Event → Widget Update

| Daemon message | Handler | Widget update |
|----------------|---------|---------------|
| `type: status` | `_process_daemon_event` | StatusBar (state, thread_id) |
| `type: event`, mode=messages | `_handle_messages_event` | ConversationPanel (AIMessage text), ActivityPanel (tool calls) |
| `type: event`, mode=custom, soothe.* | `_handle_protocol_event` | ActivityPanel, PlanPanel (if plan.*) |
| `type: event`, mode=custom, subagent | `_handle_subagent_custom` | SubagentPanel, ActivityPanel |

**Shared state:** `TuiState` from `tui.py` holds `full_response`, `activity_lines`, `current_plan`, `subagent_tracker`, `thread_id`, etc. The Textual app reuses `_handle_protocol_event`, `_handle_subagent_custom`, `_add_activity`, `render_plan_tree` from the legacy TUI.

### Connection Management

- **Auto-start daemon:** `_ensure_daemon()` checks `SootheDaemon.is_running()`; if not, spawns `soothe server start` via subprocess, polls for socket existence (up to 5 seconds)
- **Reconnection:** On `read_event()` returning None (EOF), app sets `_connected = False` and displays "Daemon connection closed"; no automatic reconnect in current implementation

## CLI Integration

### New Commands

| Command | Implementation |
|---------|----------------|
| `soothe attach` | Check daemon running; launch Textual TUI (no auto-start) |
| `soothe server start` | Start daemon; `--foreground` runs in current process |
| `soothe server stop` | `SootheDaemon.stop_running()` sends SIGTERM |
| `soothe server status` | `SootheDaemon.is_running()` + PID from file |
| `soothe init` | Create `~/.soothe/config`, `sessions`, `generated_agents`, `logs`; copy config template |

### Expanded Thread Management

| Command | Implementation |
|--------|----------------|
| `soothe thread inspect <id>` | List threads, find match, show details + SessionLogger stats |
| `soothe thread delete <id>` | Archive + delete session file; `--yes` skips confirm |
| `soothe thread export <id>` | SessionLogger.read_recent_records; output jsonl or md |

### Headless Mode

- `_run_headless(cfg, prompt, thread_id, output_format)` uses `SootheRunner.astream()` directly (no daemon)
- `--format jsonl`: Each stream chunk written as JSON line to stdout
- `--format text` (default): Protocol events to stderr via `_render_progress_event()`; AIMessage text to stdout

## Migration Notes

- **Legacy TUI preserved:** `tui.py` remains as fallback when Textual is unavailable (`ImportError` on `from soothe.cli.tui_app import run_textual_tui`)
- **Shared components:** `TuiState`, `SubagentTracker`, `DynamicThinkingText`, `_add_activity`, `_handle_protocol_event`, `_handle_subagent_custom`, `render_plan_tree` are imported by both `tui.py` and `tui_app.py`
- **Stream handlers:** The legacy TUI consumes `SootheRunner.astream()` directly; the Textual TUI consumes the same stream via daemon IPC (events serialized/deserialized)

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
- Slash command handling in both legacy and Textual TUI

## Verification Checklist

- [ ] Daemon starts on `soothe run` when not running
- [ ] `soothe attach` connects to running daemon
- [ ] `soothe server start|stop|status` work correctly
- [ ] `soothe init` creates ~/.soothe structure
- [ ] Textual TUI displays conversation, plan, activity, subagent panels
- [ ] Events from daemon update correct widgets
- [ ] Slash commands (e.g. /help, /detach) work
- [ ] Headless `--format jsonl` emits valid JSONL
- [ ] Legacy TUI fallback works when Textual unavailable
- [ ] `ruff check` passes on touched files
- [ ] Targeted CLI/daemon tests pass

## Related Documents

- [RFC-0003](../specs/RFC-0003.md) - CLI TUI Architecture Design
- [RFC-0001](../specs/RFC-0001.md) - System Conceptual Design
- [RFC-0002](../specs/RFC-0002.md) - Core Modules Architecture Design
- [IG-007](./007-cli-tui-implementation.md) - CLI TUI Implementation
