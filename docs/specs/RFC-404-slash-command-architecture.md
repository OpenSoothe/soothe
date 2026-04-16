# RFC-404: Slash Command Architecture

**Status**: Draft
**Created**: 2026-04-16
**Author**: Claude (Sonnet 4.6)
**Extends**: RFC-400 (Daemon Communication Protocol)
**Related**: RFC-500 (CLI/TUI Architecture), IG-176 (Move Rich to CLI)

---

## Abstract

Establish clear architectural boundaries for slash command processing where CLI is the presentation layer (parsing, validating, rendering) and daemon is the runtime layer (RPC execution, behavior routing). This RFC extends RFC-400 with a new `command_request` message type for structured RPC commands, while routing commands continue via plain text input path.

**Key Principle**: No backward compatibility - complete cut change to enforce architectural separation.

---

## Motivation

After IG-176 moved Rich rendering to CLI, slash commands have:
- ✓ Rich rendering in CLI package
- ✓ Daemon returns structured data
- ❌ CLI rendering functions not wired to daemon events
- ❌ Command parsing logic scattered (daemon and CLI both parse)
- ❌ No clear routing - daemon handles ALL commands in `_handle_command()`
- ❌ No API contract - commands sent as user input, daemon parses to detect

**Architectural Violations**:
- Daemon knows about CLI-only commands (`/help`, `/keymaps`) - defines locally to avoid CLI import
- No distinction between "daemon state query" vs "daemon behavior trigger"
- Mixed responsibilities: daemon parses commands AND executes them

**Goal**: CLI handles presentation, daemon handles execution, proper protocol contract.

---

## Command Classification

### Category 1: CLI-only Commands (2)

Pure presentation, no daemon communication.

| Command | Description | Handler |
|---------|-------------|---------|
| `/help` | Display command registry | `show_commands()` |
| `/keymaps` | Display keyboard shortcuts | `show_keymaps()` |

**Behavior**: CLI calls handler directly, no WebSocket messages.

---

### Category 2: Daemon RPC Commands (13)

Structured API requests for daemon state/actions via `command_request` message type.

| Command | Daemon Command | Description | Params |
|---------|---------------|-------------|--------|
| `/clear` | `clear` | Clear thread history | `thread_id` (required) |
| `/exit` | `exit` | Stop thread, mark for exit | `thread_id` (required) |
| `/quit` | `quit` | Stop thread, mark for exit | `thread_id` (required) |
| `/detach` | `detach` | Mark thread as detached | `thread_id` (required) |
| `/cancel` | `cancel` | Cancel running query | `thread_id` (required) |
| `/memory` | `memory` | Query memory stats | `thread_id` (required) |
| `/policy` | `policy` | Query policy profile | `thread_id` (optional) |
| `/history` | `history` | Query input history | `thread_id` (required) |
| `/config` | `config` | Query configuration | `thread_id` (optional) |
| `/review` | `review` | Query conversation history | `thread_id` (required) |
| `/thread` | `thread` | Thread operations | `action`, `id` (params) |
| `/resume` | `resume` | Resume thread | `thread_id` (from params) |
| `/autopilot` | `autopilot_dashboard` | Show autopilot dashboard | `thread_id` (required) |

**Protocol** (RFC-400 extension):
```
Request:  {"type": "command_request", "command": "memory", "thread_id": "..."}
Response: {"type": "command_response", "command": "memory", "data": {"memory_stats": {...}}}
Error:    {"type": "command_response", "command": "memory", "error": "Thread not found"}
```

---

### Category 3: Daemon Routing Commands (5)

Behavior indicators sent as plain text via existing input path. Daemon input parser detects prefix and routes.

| Command | Description | Query Required |
|---------|-------------|----------------|
| `/plan` | Trigger plan mode | No |
| `/autopilot <N> <query>` | Autonomous execution | Yes |
| `/browser <query>` | Route to Browser subagent | Yes |
| `/claude <query>` | Route to Claude subagent | Yes |
| `/research <query>` | Route to Research subagent | Yes |

**Protocol**: Plain text input (no changes to RFC-400)
```
CLI sends:  "/browser AI trends" (plain text)
Daemon parses: detects /browser prefix, routes to Browser subagent
```

---

## Architecture

### Layer Separation

**CLI Package (Presentation Layer)**:
- Unified command registry with metadata (`COMMANDS` dict)
- Command router: parse, validate, dispatch
- Rendering functions: Rich widgets (Table, Panel, Tree)
- Zero daemon imports

**Daemon Package (Runtime Layer)**:
- RPC command handlers: execute actions, return structured data
- Routing command parser: detect prefixes, route behaviors
- Zero CLI imports
- Zero UI library imports (no Rich, no Textual)

**WebSocket Protocol** (RFC-400 extension):
- New message type: `command_request` (RPC commands)
- Response type: `command_response` (structured data)
- Existing input path: routing commands as plain text

---

### Data Flow

**CLI-only commands**:
```
User types "/help"
→ CLI registry lookup
→ CLI calls show_commands(console)
→ Display rendered table
→ No daemon communication
```

**Daemon RPC commands**:
```
User types "/memory"
→ CLI registry lookup (location="daemon", type="rpc")
→ CLI validates (thread_id exists)
→ CLI sends {"type": "command_request", "command": "memory", "thread_id": "..."}
→ Daemon executes _cmd_memory()
→ Daemon returns {"type": "command_response", "command": "memory", "data": {...}}
→ CLI event processor receives response
→ CLI calls show_memory(console, data)
→ Display rendered panel
```

**Daemon routing commands**:
```
User types "/browser AI trends"
→ CLI registry lookup (location="daemon", type="routing")
→ CLI validates (query required)
→ CLI sends "/browser AI trends" (plain text input)
→ Daemon input parser detects /browser prefix
→ Daemon routes to Browser subagent
→ Daemon streams events back
→ CLI event processor handles events
```

---

## CLI Implementation

### Command Registry

**Location**: `packages/soothe-cli/src/soothe_cli/shared/slash_commands.py`

**Structure**:
```python
COMMANDS: dict[str, dict[str, Any]] = {
    "/help": {
        "location": "cli",
        "handler": show_commands,
        "description": "Show available commands"
    },
    "/memory": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "memory",
        "description": "Show memory stats",
        "requires_thread": True,
        "handler": show_memory  # Rendering function
    },
    "/browser": {
        "location": "daemon",
        "type": "routing",
        "description": "Route to Browser subagent",
        "requires_query": True
    },
    # ... all other commands
}
```

**Metadata fields**:
- `location`: "cli" or "daemon" (routing decision)
- `type`: "rpc" or "routing" (daemon command execution mode)
- `daemon_command`: Maps CLI syntax to daemon command name
- `handler`: Rendering function for RPC responses
- `description`: Help text for `/help` command
- `requires_thread`: Validation - active thread required
- `requires_query`: Validation - query parameter required (routing commands)
- `params_schema`: Object - parameter structure for future extensibility

---

### Command Router

**Location**: `packages/soothe-cli/src/soothe_cli/shared/command_router.py`

**Functions**:
- `parse_slash_command(input_text)`: Extract command + query from input
- `validate_command(entry, command, query, thread_id)`: Check validation rules
- `route_slash_command(cmd_input, console, client)`: Main routing dispatcher
- `handle_rpc_command(entry, command, query, console, client)`: Send RPC request, handle response
- `handle_routing_command(cmd_input, console, client)`: Send plain text input
- `parse_command_params(entry, query)`: Parse params from query string

**Routing logic**:
```python
async def route_slash_command(cmd_input, console, client):
    command, query = parse_slash_command(cmd_input)
    entry = COMMANDS.get(command)
    
    if not entry:
        console.print("[red]Unknown command[/red]")
        return
    
    if not validate_command(entry, command, query, client.thread_id):
        console.print("[red]Validation error[/red]")
        return
    
    if entry["location"] == "cli":
        entry["handler"](console)
    elif entry["type"] == "rpc":
        await handle_rpc_command(entry, command, query, console, client)
    elif entry["type"] == "routing":
        await handle_routing_command(cmd_input, console, client)
```

---

### Rendering Functions

**Location**: `packages/soothe-cli/src/soothe_cli/shared/slash_commands.py`

Each RPC command has a rendering function that takes structured data and renders with Rich:

```python
def show_memory(console: Console, data: dict[str, Any]) -> None:
    """Render memory stats from daemon."""
    stats = data.get("memory_stats", {})
    console.print(
        Panel(
            json.dumps(stats, indent=2, default=str),
            title="Memory Stats",
            border_style="cyan"
        )
    )

def show_plan(console: Console, data: dict[str, Any]) -> None:
    """Render plan data from daemon."""
    plan_data = data.get("plan")
    if not plan_data:
        console.print("[dim]No active plan.[/dim]")
        return
    
    from soothe_sdk.protocol_schemas import Plan
    plan = Plan(**plan_data)
    console.print(render_plan_tree(plan))

def show_history(console: Console, data: dict[str, Any]) -> None:
    """Render input history from daemon."""
    history = data.get("history", [])
    table = Table(title="Recent Input History")
    table.add_column("Time", style="dim")
    table.add_column("Input", style="cyan")
    for item in history[:10]:
        table.add_row(item.get("timestamp", ""), item.get("text", ""))
    console.print(table)
```

**Rendering functions for**:
- `show_commands`, `show_keymaps` (CLI-only)
- `show_memory`, `show_policy`, `show_history`, `show_config`
- `show_plan`, `show_review`, `show_autopilot_dashboard`

---

### Event Processor Integration

**Location**: `packages/soothe-cli/src/soothe_cli/shared/event_processor.py`

**Update**: Handle `command_response` events

```python
def process_event(self, event: dict[str, Any]) -> None:
    event_type = event.get("type")
    
    if event_type == "command_response":
        self._handle_command_response(event)
    elif event_type == "event":
        self._handle_protocol_event(event)
    # ... other handlers

def _handle_command_response(self, event: dict[str, Any]) -> None:
    command = event.get("command")
    data = event.get("data")
    error = event.get("error")
    
    if error:
        self.renderer.print_error(error)
        return
    
    # Find rendering handler from registry
    entry = find_command_by_daemon_command(command)
    if entry and entry.get("handler"):
        entry["handler"](self.renderer.console, data)
    else:
        # Default: pretty print JSON
        console.print(Panel(json.dumps(data, indent=2), title=command))
```

---

## Daemon Implementation

### RFC-400 Protocol Extension

**New message type**: `command_request`

```typescript
// WebSocket message types (RFC-400 extension)
type: "input" | "command_request" | "subscription" | "status" | "event" | 
      "subscription_confirmed" | "error"

// Command request schema
{
  "type": "command_request",
  "command": string,         // "clear", "memory", "thread", etc.
  "thread_id": string | null,
  "params": object | null,   // Optional parameters
  "client_id": string
}

// Command response schema
{
  "type": "command_response",
  "command": string,         // Echo back command name
  "data": object | null,     // Structured data response
  "error": string | null     // Error message if failed
}
```

---

### Message Router

**Location**: `packages/soothe/src/soothe/daemon/_handlers.py`

**Update**: Add `command_request` handler

```python
async def handle_websocket_message(self, client_id: str, msg: dict[str, Any]) -> None:
    msg_type = msg.get("type")
    
    if msg_type == "input":
        await self._handle_input(client_id, msg)
    elif msg_type == "command_request":
        await self._handle_command_request(client_id, msg)
    elif msg_type == "subscription":
        await self._handle_subscription(client_id, msg)
    # ... other handlers
```

---

### RPC Command Handler

**Location**: `packages/soothe/src/soothe/daemon/_handlers.py`

**Implementation**:
```python
async def _handle_command_request(self, client_id: str, msg: dict[str, Any]) -> None:
    """Handle structured RPC command requests."""
    command = msg.get("command")
    thread_id = msg.get("thread_id")
    params = msg.get("params", {})
    
    try:
        # Dispatch to handlers
        handler_map = {
            "clear": self._cmd_clear,
            "exit": self._cmd_exit,
            "quit": self._cmd_quit,
            "detach": self._cmd_detach,
            "cancel": self._cmd_cancel,
            "memory": self._cmd_memory,
            "policy": self._cmd_policy,
            "history": self._cmd_history,
            "config": self._cmd_config,
            "review": self._cmd_review,
            "thread": self._cmd_thread,
            "resume": self._cmd_resume,
            "autopilot_dashboard": self._cmd_autopilot_dashboard,
        }
        
        handler = handler_map.get(command)
        if not handler:
            await self._send_command_response(command, error=f"Unknown command: {command}")
            return
        
        result = await handler(thread_id, params)
        await self._send_command_response(command, data=result)
        
    except Exception as exc:
        logger.exception(f"Command {command} failed")
        await self._send_command_response(command, error=str(exc))

async def _send_command_response(self, command: str, data: dict | None = None, error: str | None = None):
    """Send structured command response."""
    response = {
        "type": "command_response",
        "command": command,
    }
    if data:
        response["data"] = data
    if error:
        response["error"] = error
    await self._broadcast(response)
```

---

### Individual Command Handlers

Each RPC command has a dedicated handler that returns structured data:

```python
async def _cmd_clear(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Clear thread history."""
    if not thread_id:
        raise ValueError("Thread ID required")
    await self._runner.clear_thread(thread_id)
    await self._broadcast({"type": "clear", "thread_id": thread_id})
    return {"cleared": True, "thread_id": thread_id}

async def _cmd_memory(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Query memory stats."""
    if not thread_id:
        raise ValueError("Thread ID required")
    stats = await self._runner.memory_stats(thread_id)
    return {"memory_stats": stats}

async def _cmd_thread(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Thread operations."""
    action = params.get("action")
    thread_id_param = params.get("id")
    
    if action == "archive":
        if not thread_id_param:
            raise ValueError("Thread ID required for archive")
        await self._runner.archive_thread(thread_id_param)
        return {"archived": True, "thread_id": thread_id_param}
    else:
        raise ValueError(f"Unknown thread action: {action}")
```

**Handlers for**: clear, exit, quit, detach, cancel, memory, policy, history, config, review, thread, resume, autopilot_dashboard

---

### Routing Command Handling

**No changes**: Existing `_handle_input()` continues to parse routing commands

```python
async def _handle_input(self, client_id: str, msg: dict[str, Any]) -> None:
    text = msg.get("text", "")
    
    if text.startswith("/plan"):
        # Trigger plan mode
        # ... existing logic
    elif text.startswith("/browser "):
        # Route to Browser subagent
        query = text.split(maxsplit=1)[1]
        await self._run_query(query, subagent="browser")
    elif text.startswith("/autopilot "):
        # Parse autonomous command
        # ... existing logic
    else:
        # Regular query
        await self._run_query(text)
```

---

## Removed Code (Cut Change)

**Deleted from daemon**:
- `_SLASH_COMMANDS_HELP`, `_KEYBOARD_SHORTCUTS_HELP` constants
- `_handle_command()` method (replaced by `_handle_command_request()`)
- `_parse_autonomous_command_local` from `_command_parser.py`
- All command parsing logic in daemon foundation

**Deleted from CLI**:
- No backward compatibility code
- All legacy command handling removed

**Result**: Clean separation, zero duplication.

---

## Testing

### CLI Tests
- Command registry structure and metadata
- Routing logic (CLI/RPC/routing decision)
- Validation rules (thread required, query required)
- Rendering functions with mock data
- RPC request/response cycle (mock WebSocket)

### Daemon Tests
- Message router handles `command_request` type
- Each RPC handler returns correct data structure
- Error handling returns structured errors
- Routing commands continue via input path

### Integration Tests
- End-to-end: CLI `/memory` → daemon stats → CLI renders table
- Error: CLI `/clear` no thread → daemon error → CLI displays error
- Routing: CLI `/browser query` → daemon routes → events stream

---

## Implementation Phases

1. **Remove old code** - Delete `_handle_command`, `_SLASH_COMMANDS_HELP`, etc.
2. **CLI registry/router** - Create `COMMANDS` dict, command_router.py
3. **Daemon RPC handler** - Implement `_handle_command_request` and individual handlers
4. **Wire CLI event processor** - Add `command_response` handling
5. **Update tests** - New tests for registry, router, handlers
6. **Documentation** - Update RFC-400 spec, user guide

---

## Verification

**Success criteria**:
1. ✅ Daemon has NO knowledge of CLI-only commands
2. ✅ CLI has single unified command registry
3. ✅ RPC commands use structured protocol (`command_request`/`command_response`)
4. ✅ Routing commands use plain text input (existing path)
5. ✅ Zero backward compatibility code
6. ✅ All tests pass
7. ✅ Daemon linting: zero errors (no UI imports)
8. ✅ CLI does not import daemon runtime

---

## Future Extensions

- **Parameterized commands**: `/thread archive <id>` with params schema
- **Command discovery**: CLI queries daemon for supported RPC commands
- **Batch commands**: Multiple RPC requests in single frame

---

## References

- RFC-400: Daemon Communication Protocol
- RFC-500: CLI/TUI Architecture
- IG-176: Move Rich to CLI
- RFC-000: System Conceptual Design