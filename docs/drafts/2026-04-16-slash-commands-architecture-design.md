# Slash Command Architecture Refactoring Design

**Date**: 2026-04-16
**Author**: Claude (Sonnet 4.6)
**Status**: Design Draft
**RFC Reference**: RFC-400 (Daemon Communication Protocol Extension)

---

## Overview

Refactor slash command processing to establish clear architectural boundaries between CLI (presentation layer) and daemon (runtime layer). This design creates a proper API contract for daemon commands while maintaining natural user syntax.

**Goal**: Clean separation where CLI handles presentation (parsing, validating, rendering) and daemon handles execution (state queries, actions, routing), with no backward compatibility - complete cut change.

---

## Problem Statement

Current implementation after IG-176 has:
- Rich rendering moved to CLI ✓
- Daemon returns structured data ✓
- **But**: CLI rendering functions not wired to daemon events
- **But**: Command parsing logic scattered (daemon has `_parse_autonomous_command_local`, CLI has `parse_autonomous_command`)
- **But**: No clear command routing - daemon handles ALL commands in `_handle_command()`
- **But**: No API contract - commands sent as user input, daemon parses to detect commands

**Architectural violations**:
- Daemon knows about CLI-only commands like `/help`, `/keymaps` (defines locally to avoid import)
- No clear distinction between "daemon state query" vs "daemon behavior trigger"
- Mixed responsibilities: daemon both parses commands AND executes them

---

## Command Classification

### Category 1: CLI-only Commands (2 commands)
Pure presentation - no daemon communication required.

| Command | Handler | Description |
|---------|---------|-------------|
| `/help` | `show_commands()` | Display available commands from registry |
| `/keymaps` | `show_keymaps()` | Display keyboard shortcuts |

**Behavior**: CLI calls handler directly, returns immediately, no WebSocket messages.

---

### Category 2: Daemon RPC Commands (13 commands)
Structured API requests for daemon state/actions. Send `command_request`, receive `command_response`.

| Command | Type | Daemon Command | Description | Params |
|---------|------|----------------|-------------|--------|
| `/clear` | RPC | `clear` | Clear thread history | `thread_id` (required) |
| `/exit` | RPC | `exit` | Stop thread and mark for exit | `thread_id` (required) |
| `/quit` | RPC | `quit` | Stop thread and mark for exit | `thread_id` (required) |
| `/detach` | RPC | `detach` | Mark thread as detached | `thread_id` (required) |
| `/cancel` | RPC | `cancel` | Cancel running query | `thread_id` (required) |
| `/memory` | RPC | `memory` | Query memory stats | `thread_id` (required) |
| `/policy` | RPC | `policy` | Query policy profile | `thread_id` (optional) |
| `/history` | RPC | `history` | Query input history | `thread_id` (required) |
| `/config` | RPC | `config` | Query configuration | `thread_id` (optional) |
| `/review` | RPC | `review` | Query conversation history | `thread_id` (required) |
| `/thread` | RPC | `thread` | Thread operations | `action`, `id` (params) |
| `/resume` | RPC | `resume` | Resume thread | `thread_id` (from params) |
| `/autopilot` | RPC | `autopilot_dashboard` | Show autopilot dashboard | `thread_id` (required) |

**Protocol**:
```
Request:  {"type": "command_request", "command": "memory", "thread_id": "..."}
Response: {"type": "command_response", "command": "memory", "data": {"memory_stats": {...}}}
Error:    {"type": "command_response", "command": "memory", "error": "Thread not found"}
```

---

### Category 3: Daemon Routing Commands (5 commands)
Behavior indicators sent as plain text input. Daemon input parser detects prefix and routes accordingly.

| Command | Type | Behavior | Description | Query Required |
|---------|------|----------|-------------|----------------|
| `/plan` | Routing | Trigger plan mode | Activate planning behavior | No |
| `/autopilot <N> <query>` | Routing | Autonomous execution | Run query in autonomous mode | Yes |
| `/browser <query>` | Routing | Subagent routing | Route to Browser subagent | Yes |
| `/claude <query>` | Routing | Subagent routing | Route to Claude subagent | Yes |
| `/research <query>` | Routing | Subagent routing | Route to Research subagent | Yes |

**Protocol**: Plain text input, existing input path
```
CLI sends:  "/browser AI trends"  (plain text)
Daemon parses: detects /browser prefix, routes to Browser subagent
```

---

## Architecture Design

### Component Overview

```
┌─────────────────────────────────────────────────────────┐
│  CLI Package                                             │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Command Registry (COMMANDS dict)                │  │
│  │  - All command definitions with metadata         │  │
│  │  - Routing logic: CLI/RPC/routing                │  │
│  │  - Validation rules                              │  │
│  └──────────────────────────────────────────────────┘  │
│                          ↓                              │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Command Router                                  │  │
│  │  - parse_slash_command()                         │  │
│  │  - route_slash_command()                         │  │
│  │  - validate_command()                            │  │
│  └──────────────────────────────────────────────────┘  │
│                          ↓                              │
│       ┌─────────┬─────────────┬──────────────┐         │
│       │ CLI     │ RPC         │ Routing      │         │
│       │ Handler │ Request     │ Input        │         │
│       └────┬────┴─────┬───────┴──────┬───────┘         │
│            │          │              │                  │
│       Local  Send command_request  Send /cmd query     │
│       call        ↓                    ↓                │
│            │          │              │                  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  WebSocket Client                                │  │
│  │  - request_response() for RPC                    │  │
│  │  - send_input() for routing                      │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────┬───────────────────────┘
                                  │ WebSocket
                                  ↓
┌─────────────────────────────────────────────────────────┐
│  Daemon Package                                          │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Message Router                                   │  │
│  │  - handle_websocket_message()                    │  │
│  │    - "input" → _handle_input() (routing)         │  │
│  │    - "command_request" → _handle_command_request()│ │
│  └──────────────────────────────────────────────────┘  │
│                          ↓                              │
│       ┌─────────────────┬─────────────────────┐        │
│       │ Command Handler │ Input Parser        │        │
│       │ (RPC)           │ (Routing)           │        │
│       └──────┬──────────┴──────┬──────────────┘        │
│              │                 │                        │
│         Execute RPC       Parse /prefix                 │
│         Return data       Route behavior                │
│              │                 │                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Response Broadcaster                            │  │
│  │  - command_response (structured data)            │  │
│  │  - event stream (for routing)                    │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────┬───────────────────────┘
                                  │ WebSocket
                                  ↓
┌─────────────────────────────────────────────────────────┐
│  CLI Event Processor                                     │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │  EventProcessor.process_event()                  │  │
│  │  - "command_response" → _handle_command_response()│ │
│  │  - "event" → protocol event handling             │  │
│  └──────────────────────────────────────────────────┘  │
│                          ↓                              │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Rendering Functions                             │  │
│  │  - show_memory(console, data)                    │  │
│  │  - show_plan(console, data)                      │  │
│  │  - show_history(console, data)                   │  │
│  │  - etc.                                          │  │
│  └──────────────────────────────────────────────────┘  │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Implementation Details

### 1. CLI Command Registry

**Location**: `packages/soothe-cli/src/soothe_cli/shared/slash_commands.py`

**Structure**:
```python
from typing import Callable, Any
from rich.console import Console

COMMANDS: dict[str, dict[str, Any]] = {
    # CLI-only commands
    "/help": {
        "location": "cli",
        "handler": show_commands,
        "description": "Show available commands"
    },
    "/keymaps": {
        "location": "cli",
        "handler": show_keymaps,
        "description": "Show keyboard shortcuts"
    },
    
    # Daemon RPC commands
    "/clear": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "clear",
        "description": "Clear thread history",
        "requires_thread": True
    },
    "/memory": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "memory",
        "description": "Show memory stats",
        "requires_thread": True,
        "handler": show_memory
    },
    "/policy": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "policy",
        "description": "Show active policy profile",
        "handler": show_policy
    },
    "/history": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "history",
        "description": "Show recent prompt history",
        "requires_thread": True,
        "handler": show_history
    },
    "/config": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "config",
        "description": "Show active configuration summary",
        "handler": show_config
    },
    "/review": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "review",
        "description": "Review recent conversation and action history",
        "requires_thread": True,
        "handler": show_review
    },
    "/exit": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "exit",
        "description": "Stop thread and exit client"
    },
    "/quit": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "quit",
        "description": "Stop thread and exit client"
    },
    "/detach": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "detach",
        "description": "Leave thread running and exit client"
    },
    "/cancel": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "cancel",
        "description": "Cancel the current running job",
        "requires_thread": True
    },
    "/thread": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "thread",
        "description": "Thread operations (archive <id>)",
        "params_schema": {
            "action": {"type": "string", "required": True},
            "id": {"type": "string", "required": False}
        }
    },
    "/resume": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "resume",
        "description": "Resume a recent thread",
        "params_schema": {
            "thread_id": {"type": "string", "required": True}
        }
    },
    "/autopilot": {
        "location": "daemon",
        "type": "rpc",
        "daemon_command": "autopilot_dashboard",
        "description": "Show autopilot dashboard",
        "requires_thread": True,
        "handler": show_autopilot_dashboard
    },
    
    # Daemon routing commands
    "/plan": {
        "location": "daemon",
        "type": "routing",
        "description": "Trigger plan mode"
    },
    "/browser": {
        "location": "daemon",
        "type": "routing",
        "description": "Route query to Browser subagent",
        "requires_query": True
    },
    "/claude": {
        "location": "daemon",
        "type": "routing",
        "description": "Route query to Claude subagent",
        "requires_query": True
    },
    "/research": {
        "location": "daemon",
        "type": "routing",
        "description": "Route query to Research subagent",
        "requires_query": True
    }
}

KEYBOARD_SHORTCUTS: dict[str, str] = {
    "Ctrl+Q": "Quit TUI: Stop thread (confirm) and exit client",
    "Ctrl+D": "Detach TUI: Leave thread running (confirm) and exit client",
    "Ctrl+C": "Cancel running job, press twice within 1s to quit",
    "Ctrl+E": "Focus chat input",
    "Ctrl+Y": "Copy last message to clipboard",
}
```

**Metadata fields**:
- `location`: "cli" or "daemon" - determines routing
- `type`: "rpc" or "routing" - daemon command execution type
- `daemon_command`: Maps CLI syntax to daemon command name
- `handler`: CLI rendering function (for RPC responses)
- `description`: Help text for `/help` command
- `requires_thread`: Boolean - thread must be active
- `requires_query`: Boolean - query parameter required (routing commands)
- `params_schema`: Object - future parameterization support

---

### 2. CLI Command Router

**Location**: `packages/soothe-cli/src/soothe_cli/shared/command_router.py`

**Implementation**:
```python
"""Command routing logic for CLI/TUI."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from rich.console import Console
from soothe_cli.shared.slash_commands import COMMANDS

if TYPE_CHECKING:
    from soothe_sdk.client import WebSocketClient

logger = logging.getLogger(__name__)


def parse_slash_command(input_text: str) -> tuple[str, str | None]:
    """Parse slash command and extract command + query.
    
    Args:
        input_text: Full user input (e.g., "/browser AI trends")
    
    Returns:
        Tuple of (command, query) where query may be None
    """
    stripped = input_text.strip()
    if not stripped.startswith("/"):
        return ("", None)
    
    parts = stripped.split(maxsplit=1)
    command = parts[0].lower()
    query = parts[1] if len(parts) > 1 else None
    
    return (command, query)


def validate_command(
    entry: dict[str, Any],
    command: str,
    query: str | None,
    thread_id: str | None
) -> tuple[bool, str | None]:
    """Validate command before routing.
    
    Args:
        entry: Command registry entry
        command: Command name
        query: Query parameter (if present)
        thread_id: Current thread ID
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check thread requirement
    if entry.get("requires_thread") and not thread_id:
        return (False, "No active thread")
    
    # Check query requirement for routing commands
    if entry.get("requires_query") and not query:
        return (False, f"Command requires query: {command} <query>")
    
    # Check params schema (future: validate params)
    if entry.get("params_schema"):
        # TODO: Add params validation logic
        pass
    
    return (True, None)


async def route_slash_command(
    cmd_input: str,
    console: Console,
    client: WebSocketClient
) -> bool:
    """Route slash command based on registry metadata.
    
    Args:
        cmd_input: Full command input (e.g., "/memory", "/browser AI trends")
        console: Rich console for rendering
        client: WebSocket client for daemon communication
    
    Returns:
        True if command was handled, False if unknown command
    """
    command, query = parse_slash_command(cmd_input)
    
    # Not a slash command
    if not command:
        return False
    
    # Lookup command in registry
    entry = COMMANDS.get(command)
    if not entry:
        console.print(f"[red]Unknown command: {command}[/red]")
        console.print("[dim]Type /help for available commands[/dim]")
        return True  # Handled (as error)
    
    # Validate command
    is_valid, error = validate_command(entry, command, query, client.thread_id)
    if not is_valid:
        console.print(f"[red]Error: {error}[/red]")
        return True  # Handled (as error)
    
    # Route based on location and type
    if entry["location"] == "cli":
        # CLI-only: call handler directly
        handler = entry.get("handler")
        if handler:
            handler(console)
        return True
    
    elif entry["location"] == "daemon" and entry["type"] == "rpc":
        # Daemon RPC: send command_request
        await handle_rpc_command(entry, command, query, console, client)
        return True
    
    elif entry["location"] == "daemon" and entry["type"] == "routing":
        # Daemon routing: send as plain text input
        await handle_routing_command(cmd_input, console, client)
        return True
    
    return False


async def handle_rpc_command(
    entry: dict[str, Any],
    command: str,
    query: str | None,
    console: Console,
    client: WebSocketClient
) -> None:
    """Handle daemon RPC command with structured request/response.
    
    Args:
        entry: Command registry entry
        command: Command name
        query: Query/params (if present)
        console: Rich console
        client: WebSocket client
    """
    daemon_command = entry["daemon_command"]
    
    # Build request
    request = {
        "type": "command_request",
        "command": daemon_command,
        "thread_id": client.thread_id,
    }
    
    # Parse params if schema exists
    if entry.get("params_schema") and query:
        params = parse_command_params(entry, query)
        request["params"] = params
    
    # Send request and wait for response
    try:
        response = await client.request_response(
            request,
            response_type="command_response",
            timeout=5.0
        )
        
        # Handle response
        if response.get("error"):
            console.print(f"[red]Error: {response['error']}[/red]")
        elif response.get("data"):
            handler = entry.get("handler")
            if handler:
                handler(console, response["data"])
            else:
                # Default: pretty print JSON
                import json
                console.print(
                    Panel(
                        json.dumps(response["data"], indent=2, default=str),
                        title=daemon_command,
                        border_style="cyan"
                    )
                )
    
    except TimeoutError:
        console.print("[red]Error: Command request timed out[/red]")
    except Exception as exc:
        logger.exception("RPC command failed")
        console.print(f"[red]Error: {exc}[/red]")


async def handle_routing_command(
    cmd_input: str,
    console: Console,
    client: WebSocketClient
) -> None:
    """Handle daemon routing command by sending plain text input.
    
    Args:
        cmd_input: Full command input (e.g., "/browser AI trends")
        console: Rich console
        client: WebSocket client
    """
    # Send as plain text - daemon input parser will route
    await client.send_input(cmd_input)


def parse_command_params(entry: dict[str, Any], query: str) -> dict[str, Any]:
    """Parse query into structured params based on schema.
    
    Args:
        entry: Command registry entry with params_schema
        query: Query string to parse
    
    Returns:
        Dict of params
    """
    schema = entry.get("params_schema", {})
    
    # Simple parsing for common patterns
    # /thread archive <id> → {"action": "archive", "id": "..."}
    # /resume <thread_id> → {"thread_id": "..."}
    
    parts = query.strip().split()
    params = {}
    
    for key, spec in schema.items():
        if spec.get("required") and parts:
            params[key] = parts[0]
            parts = parts[1:]
        elif parts:
            params[key] = parts[0]
            parts = parts[1:]
    
    return params


__all__ = [
    "parse_slash_command",
    "route_slash_command",
    "validate_command",
]
```

---

### 3. Rendering Functions

**Location**: `packages/soothe-cli/src/soothe_cli/shared/slash_commands.py` (extend existing)

**Functions**:
```python
def show_commands(console: Console) -> None:
    """Show available slash commands."""
    table = Table(title="Available Commands", show_lines=False)
    table.add_column("Command", style="bold cyan")
    table.add_column("Description")
    
    for cmd, entry in COMMANDS.items():
        table.add_row(cmd, entry.get("description", ""))
    
    console.print(table)


def show_keymaps(console: Console) -> None:
    """Show keyboard shortcuts."""
    table = Table(title="Keyboard Shortcuts", show_lines=False)
    table.add_column("Shortcut", style="bold cyan")
    table.add_column("Action")
    
    for k, v in KEYBOARD_SHORTCUTS.items():
        table.add_row(k, v)
    
    console.print(table)


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


def show_policy(console: Console, data: dict[str, Any]) -> None:
    """Render policy profile."""
    policy = data.get("policy", {})
    console.print(f"[dim]Policy profile: {policy.get('profile', 'unknown')}[/dim]")
    console.print(f"[dim]Planner routing: {policy.get('planner_routing', 'unknown')}[/dim]")
    console.print(f"[dim]Memory backend: {policy.get('memory_backend', 'unknown')}[/dim]")


def show_history(console: Console, data: dict[str, Any]) -> None:
    """Render input history from daemon."""
    history = data.get("history", [])
    
    table = Table(title="Recent Input History", show_lines=False)
    table.add_column("Time", style="dim")
    table.add_column("Input", style="cyan")
    
    for item in history[:10]:
        timestamp = item.get("timestamp", "")
        text = item.get("text", "")
        if len(text) > 50:
            text = text[:47] + "..."
        table.add_row(timestamp, text)
    
    console.print(table)


def show_config(console: Console, data: dict[str, Any]) -> None:
    """Render configuration summary."""
    config = data.get("config", {})
    console.print(
        Panel(
            json.dumps(config, indent=2, default=str),
            title="Configuration Summary",
            border_style="cyan"
        )
    )


def show_plan(console: Console, data: dict[str, Any]) -> None:
    """Render plan data from daemon."""
    plan_data = data.get("plan")
    if not plan_data:
        console.print("[dim]No active plan.[/dim]")
        return
    
    # Convert dict to Plan schema for Rich Tree
    from soothe_sdk.protocol_schemas import Plan
    plan = Plan(**plan_data)
    console.print(render_plan_tree(plan))


def show_review(console: Console, data: dict[str, Any]) -> None:
    """Render conversation/action history."""
    history = data.get("review", [])
    
    table = Table(title="Conversation Review", show_lines=False)
    table.add_column("Time", style="dim")
    table.add_column("Type", style="cyan")
    table.add_column("Content", style="white")
    
    for item in history[:20]:
        timestamp = item.get("timestamp", "")
        item_type = item.get("type", "unknown")
        content = item.get("content", "")
        if len(content) > 60:
            content = content[:57] + "..."
        table.add_row(timestamp, item_type, content)
    
    console.print(table)


def show_autopilot_dashboard(console: Console, data: dict[str, Any]) -> None:
    """Render autopilot dashboard."""
    dashboard = data.get("autopilot_dashboard", {})
    
    table = Table(title="Autopilot Dashboard", show_lines=False)
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value", style="white")
    
    # Display key metrics
    table.add_row("Status", dashboard.get("status", "idle"))
    table.add_row("Iterations", str(dashboard.get("iterations", 0)))
    table.add_row("Goals Completed", str(dashboard.get("goals_completed", 0)))
    table.add_row("Goals Active", str(dashboard.get("goals_active", 0)))
    
    console.print(table)
    
    # Display active goals if present
    active_goals = dashboard.get("active_goals", [])
    if active_goals:
        console.print("\n[bold cyan]Active Goals:[/bold cyan]")
        for goal in active_goals:
            console.print(f"  • {goal.get('description', 'unknown')}")
```

---

### 4. Daemon Protocol Extension

**RFC-400 Protocol Update**: Add new message type `command_request`

**WebSocket Message Types** (after extension):
```typescript
// Existing types
type: "input" | "subscription" | "status" | "event" | "subscription_confirmed" | "error"

// New type for RPC commands
type: "command_request"

// Command request schema
{
  "type": "command_request",
  "command": string,         // "clear", "memory", "thread", etc.
  "thread_id": string | null,
  "params": object | null,   // Optional parameters
  "client_id": string        // Client identifier
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

### 5. Daemon Message Router

**Location**: `packages/soothe/src/soothe/daemon/_handlers.py`

**Update**: Add `command_request` handler

```python
async def handle_websocket_message(self, client_id: str, msg: dict[str, Any]) -> None:
    """Route WebSocket messages to appropriate handlers."""
    msg_type = msg.get("type")
    
    if msg_type == "input":
        await self._handle_input(client_id, msg)
    elif msg_type == "command_request":
        await self._handle_command_request(client_id, msg)
    elif msg_type == "subscription":
        await self._handle_subscription(client_id, msg)
    elif msg_type == "status":
        # Status messages handled synchronously
        pass
    else:
        logger.warning(f"Unknown message type: {msg_type}")
```

---

### 6. Daemon Command Request Handler

**Location**: `packages/soothe/src/soothe/daemon/_handlers.py`

**Implementation**:
```python
async def _handle_command_request(self, client_id: str, msg: dict[str, Any]) -> None:
    """Handle structured RPC command requests (RFC-400 extension).
    
    Args:
        client_id: Client identifier
        msg: Command request message with command, thread_id, params
    """
    import logging
    
    logger = logging.getLogger(__name__)
    
    command = msg.get("command")
    thread_id = msg.get("thread_id")
    params = msg.get("params", {})
    
    try:
        # Dispatch to command handlers
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
        
        # Execute command handler
        result = await handler(thread_id, params)
        
        # Send response
        await self._send_command_response(command, data=result)
        
    except Exception as exc:
        logger.exception(f"Command {command} failed")
        await self._send_command_response(command, error=str(exc))


async def _send_command_response(
    self,
    command: str,
    data: dict[str, Any] | None = None,
    error: str | None = None
) -> None:
    """Send structured command response.
    
    Args:
        command: Command name
        data: Response data (if successful)
        error: Error message (if failed)
    """
    response = {
        "type": "command_response",
        "command": command,
    }
    
    if data is not None:
        response["data"] = data
    if error is not None:
        response["error"] = error
    
    await self._broadcast(response)


# Individual command handlers
async def _cmd_clear(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Clear thread history."""
    if not thread_id:
        raise ValueError("Thread ID required")
    
    # Clear thread state in runner
    await self._runner.clear_thread(thread_id)
    
    # Broadcast clear event to all clients
    await self._broadcast({"type": "clear", "thread_id": thread_id})
    
    return {"cleared": True, "thread_id": thread_id}


async def _cmd_memory(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Query memory stats."""
    if not thread_id:
        raise ValueError("Thread ID required")
    
    stats = await self._runner.memory_stats(thread_id)
    return {"memory_stats": stats}


async def _cmd_policy(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Query policy profile."""
    policy_data = {
        "profile": self._runner.config.protocols.policy.profile,
        "planner_routing": self._runner.config.protocols.planner.routing,
        "memory_backend": self._runner.config.protocols.memory.backend,
    }
    return {"policy": policy_data}


async def _cmd_history(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Query input history."""
    if not thread_id:
        raise ValueError("Thread ID required")
    
    # Get history from thread state
    st = self._thread_registry.get(thread_id)
    if st and hasattr(st, "input_history"):
        history = st.input_history.get_recent(20)
    else:
        history = []
    
    return {"history": history}


async def _cmd_config(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Query configuration."""
    config_data = {
        "providers": [
            {"name": p.name, "models": list(p.models.keys()) if p.models else []}
            for p in (self._runner.config.providers or [])
        ],
        "workspace_dir": str(self._runner.config.workspace_dir or ""),
        "verbosity": str(self._runner.config.logging.verbosity),
    }
    return {"config": config_data}


async def _cmd_thread(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Thread operations."""
    action = params.get("action")
    thread_id_param = params.get("id")
    
    if action == "archive":
        if not thread_id_param:
            raise ValueError("Thread ID required for archive")
        # Archive thread
        result = await self._runner.archive_thread(thread_id_param)
        return {"archived": True, "thread_id": thread_id_param}
    else:
        raise ValueError(f"Unknown thread action: {action}")


# ... implement other handlers similarly
```

---

### 7. Routing Command Handling

**No changes needed** - existing `_handle_input()` continues to parse routing commands:

```python
async def _handle_input(self, client_id: str, msg: dict[str, Any]) -> None:
    """Handle user input (including routing commands)."""
    text = msg.get("text", "")
    
    # Parse routing commands
    if text.startswith("/plan"):
        # Trigger plan mode
        # ...
    elif text.startswith("/browser "):
        # Route to Browser subagent
        query = text.split(maxsplit=1)[1]
        await self._run_query(query, subagent="browser")
    elif text.startswith("/autopilot "):
        # Parse autonomous command
        # ...
    # ... other routing commands
    
    else:
        # Regular query
        await self._run_query(text)
```

---

### 8. CLI Event Processor Integration

**Location**: `packages/soothe-cli/src/soothe_cli/shared/event_processor.py`

**Update**: Add `command_response` handling

```python
def process_event(self, event: dict[str, Any]) -> None:
    """Process daemon event."""
    event_type = event.get("type")
    
    if event_type == "command_response":
        self._handle_command_response(event)
    elif event_type == "event":
        self._handle_protocol_event(event)
    elif event_type == "status":
        self._handle_status_event(event)
    # ... other handlers


def _handle_command_response(self, event: dict[str, Any]) -> None:
    """Handle command response from daemon."""
    command = event.get("command")
    data = event.get("data")
    error = event.get("error")
    
    if error:
        self.renderer.print_error(error)
        return
    
    # Find command entry in registry
    entry = None
    for cmd_name, cmd_entry in COMMANDS.items():
        if cmd_entry.get("daemon_command") == command:
            entry = cmd_entry
            break
    
    # Render with handler
    if entry and entry.get("handler") and data:
        handler = entry["handler"]
        handler(self.renderer.console, data)
    else:
        # Default: pretty print JSON
        import json
        self.renderer.console.print(
            Panel(
                json.dumps(data, indent=2, default=str),
                title=command,
                border_style="cyan"
            )
        )
```

---

## Error Handling

### CLI Validation Errors (Local)
- **Unknown command**: `[red]Unknown command: /xyz[/red]`
- **No active thread**: `[red]Error: No active thread[/red]`
- **Query required**: `[red]Error: Command requires query: /browser <query>[/red]`

### Daemon Execution Errors
- **Thread not found**: `{"type": "command_response", "error": "Thread not found: thread_id=xyz"}`
- **Permission denied**: `{"type": "command_response", "error": "Permission denied for action"}`
- **Internal failure**: `{"type": "command_response", "error": "Clear failed: exception details"}`

**Rendering**: CLI displays error in red, no rendering handler called.

---

## Testing Strategy

### CLI Tests
- `test_command_registry.py`: Registry structure and metadata validation
- `test_command_router.py`: Routing logic for CLI/RPC/routing commands
- `test_command_validation.py`: Validation rules (thread required, query required)
- `test_rendering_functions.py`: Each rendering function with mock data
- `test_rpc_integration.py`: Mock WebSocket client, request/response cycle

### Daemon Tests
- `test_message_router.py`: Handles `command_request` type correctly
- `test_command_handlers.py`: Each RPC command handler returns correct data
- `test_command_errors.py`: Error handling returns structured error responses
- `test_routing_commands.py`: Routing commands still work via input path

### Integration Tests
- End-to-end: CLI sends `/memory` → daemon returns stats → CLI renders table
- Error scenario: CLI sends `/clear` with no thread → daemon returns error → CLI displays error
- Routing: CLI sends `/browser AI trends` → daemon routes to Browser → events stream back

---

## Implementation Phases

### Phase 1: Remove Old Implementation
- Delete `_SLASH_COMMANDS_HELP`, `_KEYBOARD_SHORTCUTS_HELP` from daemon `_handlers.py`
- Delete `_handle_command()` method (replaced by `_handle_command_request()`)
- Delete `_parse_autonomous_command_local` from daemon `_command_parser.py`
- Remove command parsing from daemon foundation

### Phase 2: Implement CLI Registry and Router
- Create unified `COMMANDS` registry in `slash_commands.py`
- Implement `command_router.py` with routing logic
- Add rendering functions for all RPC commands
- Export router functions in `shared/__init__.py`

### Phase 3: Implement Daemon RPC Handler
- Add `command_request` to RFC-400 message types
- Update message router to handle new type
- Implement `_handle_command_request()` dispatcher
- Implement individual RPC command handlers (clear, memory, policy, etc.)
- Implement `_send_command_response()` broadcaster

### Phase 4: Wire CLI Event Processor
- Add `command_response` handling in `EventProcessor.process_event()`
- Implement `_handle_command_response()` to call rendering functions
- Update TUI/CLI modes to use command router

### Phase 5: Update Tests
- Add new tests for registry, router, handlers
- Update existing tests for new message type
- Integration tests for full flow

### Phase 6: Documentation
- Update RFC-400 spec with new message type
- Update user guide with command categories
- Document registry metadata schema

---

## Verification Criteria

**Success criteria**:
1. ✅ Daemon has NO knowledge of CLI-only commands
2. ✅ CLI has single unified command registry
3. ✅ RPC commands use structured protocol (command_request/command_response)
4. ✅ Routing commands use plain text input (existing path)
5. ✅ Zero backward compatibility code - clean cut change
6. ✅ All tests pass with new architecture
7. ✅ Daemon linting: zero errors (no UI imports)
8. ✅ CLI does not import daemon runtime

---

## Dependencies

**RFC Updates**:
- RFC-400 (Daemon Communication Protocol) - add `command_request` message type

**Package Dependencies**:
- No new dependencies required
- Uses existing `soothe_sdk.protocol_schemas` for data structures

---

## Risks and Mitigation

**Risk**: Breaking existing command usage patterns
- **Mitigation**: Clear documentation of command categories and syntax
- **Mitigation**: No syntax changes for users - `/memory` still works the same way

**Risk**: Complex command parameters (future)
- **Mitigation**: Extensible `params_schema` in registry
- **Mitigation**: Daemon handlers validate and parse params

**Risk**: Performance overhead for RPC round-trip
- **Mitigation**: RPC commands are intentional queries (not frequent)
- **Mitigation**: Request/response timeout set appropriately (5s)

---

## Future Extensions

**Parameterized commands**:
- `/thread archive <id>` → `{"params": {"action": "archive", "id": "..."}}`
- `/autopilot <N> <query>` → routing command, params extracted by CLI

**Command discovery**:
- CLI could query daemon for supported RPC commands (metadata endpoint)
- Dynamic registry updates without CLI code changes

**Batch commands**:
- Multiple RPC requests in single WebSocket frame
- Batch response with multiple command_response events

---

## Conclusion

This design establishes clear architectural boundaries for slash command processing:
- CLI is the presentation layer (registry, routing, rendering)
- Daemon is the runtime layer (RPC execution, behavior routing)
- Protocol is the contract (structured requests/responses for RPC, plain text for routing)

**No backward compatibility** - complete refactoring removes all legacy command handling code.

**Clean separation** - daemon has zero knowledge of CLI-only commands, CLI has zero daemon imports.

**Extensible** - metadata-based registry supports future command features without architectural changes.