# Soothe CLI Architecture

## Overview

The Soothe CLI provides a multi-agent orchestration system with persistent threads and real-time streaming. It supports multiple execution modes (TUI, headless, daemon, standalone) and manages agent interactions through a sophisticated daemon-client architecture.

**Key Features:**
- Multi-agent orchestration with specialized subagents (Scout, Planner, etc.)
- Persistent thread management with checkpoint/resume
- Real-time event streaming via Unix socket IPC
- Multiple execution modes for different workflows
- Rich terminal UI with Textual framework

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          User Input                                  │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
                      ▼
            ┌─────────────────┐
            │   main.py       │  Typer CLI entry point
            │   (commands/)   │  Command handlers
            └────────┬────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
   ┌─────────┐ ┌──────────┐ ┌───────────┐
   │   TUI   │ │ Headless │ │  Daemon   │
   │  Mode   │ │   Mode   │ │   Mode    │
   └────┬────┘ └─────┬────┘ └─────┬─────┘
        │            │            │
        │            │            │
        └────────────┼────────────┘
                     │
                     ▼
            ┌─────────────────┐
            │  daemon/        │  IPC Server
            │  - server.py    │  SootheDaemon
            │  - client.py    │  DaemonClient
            └────────┬────────┘
                     │
                     ▼
            ┌─────────────────┐
            │   SootheRunner  │  Core orchestration
            │   (core/)       │  Agent execution
            └─────────────────┘
```

## Directory Structure

```
src/soothe/cli/
├── main.py                      (236 lines) - Typer CLI entry point
├── slash_commands.py            (453 lines) - Slash command handlers
├── thread_logger.py             (183 lines) - Thread logging utilities
├── tui_shared.py                (128 lines) - Shared TUI utilities
│
├── commands/                    - Command handlers (Typer)
│   ├── __init__.py              (15 lines)
│   ├── attach_cmd.py            (127 lines) - Attach to running daemon
│   ├── config_cmd.py            (89 lines) - Configuration management
│   ├── init_cmd.py              (76 lines) - Initialize new project
│   ├── run_cmd.py               (142 lines) - Run agent (TUI/headless)
│   ├── server_cmd.py            (145 lines) - Daemon lifecycle management
│   ├── status_cmd.py            (68 lines) - System status display
│   ├── subagent_names.py        (23 lines) - Subagent name constants
│   └── thread_cmd.py            (215 lines) - Thread management
│
├── core/                        - Core utilities
│   ├── __init__.py              (10 lines)
│   ├── config_loader.py         (89 lines) - Config file loading
│   ├── logging_setup.py         (123 lines) - Logging configuration
│   └── migrations.py            (156 lines) - Schema migrations
│
├── daemon/                      - Daemon subpackage (IPC server)
│   ├── __init__.py              (15 lines) - Public API re-exports
│   ├── client.py                (102 lines) - DaemonClient class
│   ├── entrypoint.py            (52 lines) - run_daemon() function
│   ├── paths.py                 (28 lines) - Path utilities
│   ├── protocol.py              (87 lines) - IPC encode/decode
│   ├── server.py                (492 lines) - SootheDaemon class
│   └── singleton.py             (71 lines) - PID file management
│
├── execution/                   - Execution modes
│   ├── __init__.py              (10 lines)
│   ├── daemon_runner.py         (112 lines) - Run via daemon
│   ├── headless.py              (94 lines) - Non-interactive mode
│   ├── postgres_check.py        (47 lines) - PostgreSQL checks
│   ├── standalone_runner.py     (89 lines) - Direct execution
│   └── tui.py                   (156 lines) - Textual UI runner
│
├── rendering/                   - Output rendering
│   ├── __init__.py              (10 lines)
│   └── progress_renderer.py     (245 lines) - Progress display
│
└── tui/                         - Textual UI subpackage
    ├── __init__.py              (12 lines)
    ├── app.py                   (423 lines) - Main TUI app
    ├── event_processors.py      (156 lines) - Event handling
    ├── renderers.py             (234 lines) - UI renderers
    ├── state.py                 (89 lines) - State management
    └── widgets.py               (312 lines) - Custom widgets

Total: ~30 files, ~4,200 lines of code
```

## Execution Modes

### TUI Mode (Interactive Terminal UI)

**When to use:** Interactive sessions with rich terminal UI, real-time streaming, and visual feedback.

**How it works:**
1. Checks if daemon is running, starts it if needed
2. Launches Textual TUI app that connects to daemon via `DaemonClient`
3. User input sent to daemon, events streamed back to TUI
4. Supports slash commands, thread switching, and rich formatting

**Example commands:**
```bash
soothe run                    # Launch TUI (auto-starts daemon)
soothe run --no-tui           # Headless mode (direct execution)
```

**Data flow:**
```
User Input → TUI App → DaemonClient → Unix Socket → SootheDaemon → SootheRunner
     ↓                                                                    ↓
  Display  ←  TUI App  ←  Events  ←  Unix Socket  ←  SootheDaemon ← Events
```

### Headless Mode (Non-interactive Execution)

**When to use:** Single-shot execution, scripting, CI/CD pipelines, or when TUI is unavailable.

**How it works:**
1. Connects to running daemon (or starts daemon in background)
2. Sends prompt to daemon via `DaemonClient`
3. Streams events to stdout until completion
4. Detaches and exits

**Example commands:**
```bash
soothe run "analyze the codebase"              # Run via daemon
soothe run "fix bug #123" --no-tui            # Force headless mode
soothe run "implement feature" --autonomous   # Autonomous mode
```

### Daemon Mode (Background Server)

**When to use:** Persistent background service for multiple clients, thread management across sessions.

**How it works:**
1. `SootheDaemon` listens on Unix socket (`~/.soothe/soothe.sock`)
2. Accepts multiple client connections (TUI, headless, attach)
3. Maintains singleton lock via PID file (`~/.soothe/soothe.pid`)
4. Streams events to all connected clients
5. Manages thread lifecycle and checkpointing

**Example commands:**
```bash
soothe server start           # Start daemon in background
soothe server status          # Check daemon status
soothe server stop            # Stop daemon gracefully
soothe server restart         # Restart daemon
```

**Daemon lifecycle:**
```
start() → Acquire PID lock → Create socket → Initialize runner → Accept clients
    ↓
serve_forever() → Process input loop → Handle commands → Stream events
    ↓
stop() → Cleanup runner → Close clients → Release lock → Remove socket
```

### Standalone Mode (Fallback)

**When to use:** When daemon is unavailable or not desired (e.g., debugging, isolated environments).

**How it works:**
1. Runs `SootheRunner` directly in-process
2. No socket communication, no background server
3. Events rendered directly to stdout
4. No thread persistence across runs

**Example commands:**
```bash
soothe run "test prompt" --standalone   # Force standalone mode
```

## Data Flow

### Request Flow (User Input → Agent Execution)

```
┌─────────────┐
│ User Input  │
└──────┬──────┘
       │
       ▼
┌──────────────────┐
│ Input Validation │  Check for slash commands, thread IDs
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Daemon Message   │  {"type": "input", "text": "...", "autonomous": false}
│ Encoding         │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Unix Socket      │  Send to ~/.soothe/soothe.sock
│ Transmission     │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ SootheDaemon     │  _handle_client_message() → _input_loop()
│ Processing       │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ SootheRunner     │  astream(text, thread_id=..., autonomous=...)
│ Execution        │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Agent Pipeline   │  Scout → Planner → Executor → Validator
│ Orchestration    │
└──────────────────┘
```

### Event Streaming Architecture

```
SootheRunner.astream()
       │
       ├──► namespace: [], mode: "messages", data: (AIMessage, metadata)
       ├──► namespace: ["scout"], mode: "tool_calls", data: [...]
       ├──► namespace: ["planner"], mode: "custom", data: {"type": "plan", ...}
       ├──► namespace: ["executor"], mode: "tool_calls", data: [...]
       └──► ...
       │
       ▼
SootheDaemon._run_query()
       │
       ├──► ThreadLogger.log(namespace, mode, data)  # Persist to disk
       ├──► _broadcast(event_msg)                    # Send to all clients
       │         │
       │         ├──► client1.writer.write(encode(event_msg))
       │         ├──► client2.writer.write(encode(event_msg))
       │         └──► ...
       │
       ▼
DaemonClient.read_event()
       │
       ├──► decode(line) → {"type": "event", "namespace": [...], ...}
       │
       ▼
TUI/Headless Renderer
       │
       ├──► TUI: Update widgets, scroll to bottom, show progress
       └──► Headless: Print to stdout with formatting
```

### Thread Management Lifecycle

```
┌────────────────────────────────────────────────────────────────┐
│                    Thread Lifecycle                             │
└────────────────────────────────────────────────────────────────┘

1. Creation
   ┌──────────────┐
   │ User Input   │ → SootheRunner creates new thread
   └──────────────┘   → Generates thread_id (UUID)
                      → Creates ~/.soothe/runs/<thread_id>/
                      → Initializes checkpoint.json

2. Execution
   ┌──────────────┐
   │ Running      │ → Events logged to ThreadLogger
   └──────────────┘   → Checkpoint updated after each step
                      → Status: "in_progress"

3. Completion
   ┌──────────────┐
   │ Done         │ → Status: "completed"
   └──────────────┘   → Final checkpoint saved
                      → ThreadLogger closed

4. Recovery (on daemon restart)
   ┌──────────────────┐
   │ Detect Incomplete│ → Scan ~/.soothe/runs/*/checkpoint.json
   └──────────────────┘   → Find threads with status: "in_progress"
                          → Log to daemon startup

5. Resume
   ┌──────────────────┐
   │ Resume Thread    │ → soothe thread resume <thread_id>
   └──────────────────┘   → Load checkpoint into SootheRunner
                          → Continue execution from last state

6. Cleanup
   ┌──────────────────┐
   │ Periodic Cleanup │ → ThreadLogger.cleanup_old_threads()
   └──────────────────┘   → Delete threads older than retention_days
```

## Key Modules

| Module | Responsibility | Key Exports |
|--------|---------------|-------------|
| `main.py` | CLI entry point | `app` (Typer), command registration |
| `commands/run_cmd.py` | Run command handler | `run` function |
| `commands/server_cmd.py` | Server lifecycle | `start`, `stop`, `status` commands |
| `commands/thread_cmd.py` | Thread management | `list`, `resume`, `export`, `delete` |
| `execution/tui.py` | TUI execution mode | `run_tui_mode` |
| `execution/headless.py` | Headless execution | `run_headless_mode` |
| `execution/daemon_runner.py` | Daemon mode | `run_via_daemon` |
| `daemon/server.py` | IPC server | `SootheDaemon` |
| `daemon/client.py` | IPC client | `DaemonClient` |
| `daemon/protocol.py` | Message encoding | `encode`, `decode` |
| `daemon/singleton.py` | PID management | `acquire_pid_lock`, `release_pid_lock` |
| `tui/app.py` | Textual TUI app | `SootheTUI` |
| `tui/widgets.py` | Custom widgets | `InputWidget`, `MessageList`, `StatusBar` |
| `core/logging_setup.py` | Logging config | `setup_logging` |
| `core/config_loader.py` | Config loading | `load_config` |
| `thread_logger.py` | Thread persistence | `ThreadLogger` |

## Common Workflows

### Starting an Interactive Session

```bash
# Option 1: Let `soothe run` auto-start daemon
soothe run

# Option 2: Explicit daemon management
soothe server start
soothe run
```

**What happens:**
1. `run_cmd.py` checks if daemon is running via `SootheDaemon.is_running()`
2. If not running, starts daemon in background via `soothe server start`
3. Launches Textual TUI app
4. TUI connects to daemon via `DaemonClient`
5. User can interact with agents, switch threads, run slash commands

### Running a Single Prompt

```bash
# Headless mode (via daemon)
soothe run "analyze the codebase structure"

# Standalone mode (no daemon)
soothe run "analyze the codebase structure" --standalone

# Autonomous mode
soothe run "implement user authentication" --autonomous --max-iterations 50
```

**What happens:**
1. `run_cmd.py` detects non-interactive mode (prompt provided)
2. Connects to daemon via `DaemonClient` (or runs standalone)
3. Sends input with `send_input(text, autonomous=True, max_iterations=N)`
4. Streams events to stdout via `read_event()` loop
5. Detaches when `status: idle` received

### Managing the Daemon

```bash
# Start daemon
soothe server start

# Check status
soothe server status
# Output: Daemon running (PID 12345)
#         Socket: /Users/you/.soothe/soothe.sock
#         Threads: 3 total, 1 in_progress

# Stop daemon gracefully
soothe server stop

# Force stop if unresponsive
soothe server stop --force
```

**What happens:**
1. `server_cmd.py` calls `SootheDaemon.is_running()` to check status
2. `start` creates daemon process via `subprocess.Popen`
3. `stop` sends SIGTERM via `SootheDaemon.stop_running()`
4. Daemon catches signal, runs cleanup, exits gracefully
5. If timeout, escalates to SIGKILL

### Managing Threads

```bash
# List all threads
soothe thread list

# Output:
# Thread ID                              Status      Created              Query
# a1b2c3d4-e5f6-7890-abcd-ef1234567890  completed   2024-01-15 10:30    Analyze codebase
# b2c3d4e5-f6a7-8901-bcde-f12345678901  in_progress 2024-01-15 11:45    Fix bug #123
# c3d4e5f6-a7b8-9012-cdef-123456789012  completed   2024-01-14 09:15    Implement feature

# Resume a thread
soothe thread resume a1b2c3d4-e5f6-7890-abcd-ef1234567890

# Export thread logs
soothe thread export a1b2c3d4-e5f6-7890-abcd-ef1234567890 --output thread.json

# Delete old threads
soothe thread delete c3d4e5f6-a7b8-9012-cdef-123456789012
```

### Configuration Management

```bash
# Show current config
soothe config show

# Set config value
soothe config set model.default_provider openai

# Edit config file
soothe config edit
```

## Development

### Adding New Commands

**Step 1:** Create command handler in `commands/`

```python
# src/soothe/cli/commands/new_cmd.py
import typer
from typing_extensions import Annotated

app = typer.Typer()

@app.command("new-command")
def new_command(
    arg1: Annotated[str, typer.Argument(help="First argument")],
    option1: Annotated[bool, typer.Option("--flag", help="A flag")] = False,
) -> None:
    """Description of new command."""
    # Implementation
    pass
```

**Step 2:** Register in `commands/__init__.py`

```python
from soothe.cli.commands.new_cmd import app as new_cmd_app

# Add to CLI registry
```

**Step 3:** Import in `main.py`

```python
from soothe.cli.commands import new_cmd_app

app.add_typer(new_cmd_app, name="new-command")
```

**Step 4:** Test

```bash
soothe new-command --help
soothe new-command "test"
```

### Testing Commands

```bash
# Run CLI-related unit tests
pytest tests/unit_tests/test_cli_commands*.py -v

# Test daemon lifecycle
pytest tests/unit_tests/test_cli_session.py -v

# Test specific command
pytest tests/unit_tests/test_init_command.py -v
```

### Debugging Daemon Issues

**Check daemon status:**
```bash
soothe server status
```

**Check PID file:**
```bash
cat ~/.soothe/soothe.pid
# Should contain running daemon's PID
```

**Check socket:**
```bash
ls -la ~/.soothe/soothe.sock
# Should exist if daemon running
```

**Check daemon logs:**
```bash
# Logs are in ~/.soothe/logs/daemon.log
tail -f ~/.soothe/logs/daemon.log
```

**Force cleanup:**
```bash
# If daemon is stuck, manually remove files
rm ~/.soothe/soothe.pid
rm ~/.soothe/soothe.sock
```

**Debug mode:**
```bash
# Run daemon in foreground with debug logging
soothe server start --foreground --log-level DEBUG
```

**Test daemon communication:**
```python
import asyncio
from soothe.cli.daemon import DaemonClient

async def test():
    client = DaemonClient()
    await client.connect()
    await client.send_input("test prompt")
    event = await client.read_event()
    print(event)
    await client.close()

asyncio.run(test())
```

## Architecture Principles

### Separation of Concerns

- **Commands/**: User-facing command handlers (thin layer)
- **Execution/**: Execution mode orchestration (how to run)
- **Daemon/**: IPC infrastructure (socket, protocol, server)
- **TUI/**: Presentation layer (widgets, rendering, state)
- **Core/**: Cross-cutting concerns (logging, config, migrations)

### Dependency Direction

```
main.py → commands/ → execution/ → daemon/ → core/
                                     ↓
                                   tui/ → core/
```

- Commands depend on execution modes
- Execution modes depend on daemon client
- Daemon server depends on core utilities
- TUI depends on daemon client and core utilities
- Core has no dependencies on other CLI modules

### Error Handling

- **User input errors**: Caught in commands, display helpful message
- **Daemon errors**: Logged to daemon.log, events broadcast to clients
- **Connection errors**: Handled in DaemonClient, automatic retry/reconnect
- **Runner errors**: Wrapped in error events, broadcast to clients

### Thread Safety

- `SootheDaemon.request_stop()`: Thread-safe shutdown via `threading.Event`
- `asyncio.Queue`: Thread-safe input queue for client messages
- File locking: `fcntl.flock()` for PID file singleton

## Performance Considerations

- **Large events**: Socket limit set to 10MB for search results
- **Heavy initialization**: `SootheRunner` init runs in thread pool via `asyncio.to_thread()`
- **Periodic cleanup**: Daemon runs cleanup every 24 hours
- **Event batching**: Events streamed individually, not batched

## Security

- **Socket permissions**: Unix socket uses default permissions (user-only by default)
- **PID lock**: Exclusive lock via `fcntl.flock()` prevents multiple daemons
- **Input validation**: Commands validate input before sending to daemon
- **No authentication**: Socket is local-only, relies on OS permissions

## Future Improvements

- [ ] Add authentication/authorization for remote daemon access
- [ ] Implement event batching for better performance
- [ ] Add daemon clustering for horizontal scaling
- [ ] Implement rate limiting for client connections
- [ ] Add metrics/monitoring endpoints
- [ ] Support remote daemon connections via TCP
