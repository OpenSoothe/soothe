# IG-177: Slash Command Architecture Implementation

**Status**: Draft
**RFC**: RFC-404 (Slash Command Architecture)
**Started**: 2026-04-16
**Priority**: High - Architectural Separation
**Type**: Cut Change - No Backward Compatibility

---

## Overview

Implement RFC-404 slash command architecture with complete architectural separation between CLI (presentation) and daemon (runtime). Execute 6 phases with zero backward compatibility code.

**Goal**: Clean cut change - remove all legacy command handling, establish proper protocol contract.

---

## Implementation Phases

### Phase 1: Remove Old Code (Daemon Cleanup)

**Objective**: Delete all legacy slash command handling from daemon.

**Files to delete**:
- `packages/soothe/src/soothe/daemon/_command_parser.py` (entire file)
- Remove from `packages/soothe/src/soothe/daemon/_handlers.py`:
  - `_SLASH_COMMANDS_HELP` constant
  - `_KEYBOARD_SHORTCUTS_HELP` constant
  - `_handle_command()` method
  - All command parsing logic in `_handle_command()`

**Verification**:
```bash
grep "_SLASH_COMMANDS_HELP\|_KEYBOARD_SHORTCUTS_HELP\|_handle_command" packages/soothe/src/soothe/daemon/_handlers.py
# Should return nothing
```

---

### Phase 2: CLI Registry and Router

**Objective**: Create unified command registry and routing logic in CLI.

#### 2.1 Update Command Registry

**File**: `packages/soothe-cli/src/soothe_cli/shared/slash_commands.py`

**Actions**:
1. Replace existing `COMMANDS` dict with unified registry containing all 20 commands
2. Add metadata fields for each command (location, type, daemon_command, handler, etc.)
3. Update rendering functions to accept `data` parameter for RPC responses

**Registry structure** (from RFC-404):
```python
COMMANDS: dict[str, dict[str, Any]] = {
    # CLI-only commands (2)
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
    
    # Daemon RPC commands (13)
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
    # ... all other commands (see RFC-404)
}
```

#### 2.2 Create Command Router

**File**: `packages/soothe-cli/src/soothe_cli/shared/command_router.py` (new file)

**Functions to implement**:
1. `parse_slash_command(input_text: str) -> tuple[str, str | None]`
2. `validate_command(entry, command, query, thread_id) -> tuple[bool, str | None]`
3. `route_slash_command(cmd_input, console, client) -> bool`
4. `handle_rpc_command(entry, command, query, console, client) -> None`
5. `handle_routing_command(cmd_input, console, client) -> None`
6. `parse_command_params(entry, query) -> dict[str, Any]`
7. `find_command_by_daemon_command(daemon_command: str) -> dict | None`

**Implementation** (from RFC-404):
```python
async def route_slash_command(cmd_input, console, client):
    command, query = parse_slash_command(cmd_input)
    entry = COMMANDS.get(command)
    
    if not entry:
        console.print("[red]Unknown command[/red]")
        return True
    
    if not validate_command(entry, command, query, client.thread_id):
        console.print("[red]Validation error[/red]")
        return True
    
    if entry["location"] == "cli":
        entry["handler"](console)
        return True
    elif entry["type"] == "rpc":
        await handle_rpc_command(entry, command, query, console, client)
        return True
    elif entry["type"] == "routing":
        await handle_routing_command(cmd_input, console, client)
        return True
    
    return False
```

#### 2.3 Update Rendering Functions

**File**: `packages/soothe-cli/src/soothe_cli/shared/slash_commands.py`

**Rendering functions to implement**:
- `show_commands(console)` - CLI-only
- `show_keymaps(console)` - CLI-only
- `show_memory(console, data)` - RPC
- `show_policy(console, data)` - RPC
- `show_history(console, data)` - RPC
- `show_config(console, data)` - RPC
- `show_plan(console, data)` - RPC
- `show_review(console, data)` - RPC
- `show_autopilot_dashboard(console, data)` - RPC

**Implementation notes**:
- Each RPC rendering function takes `console` and `data` parameters
- Data comes from daemon `command_response` event
- Use Rich widgets (Table, Panel, Tree) for rendering

#### 2.4 Export Router

**File**: `packages/soothe-cli/src/soothe_cli/shared/__init__.py`

**Add exports**:
```python
from soothe_cli.shared.command_router import (
    parse_slash_command,
    route_slash_command,
    validate_command,
    find_command_by_daemon_command,
)

__all__ = [
    # ... existing exports
    "parse_slash_command",
    "route_slash_command",
    "validate_command",
    "find_command_by_daemon_command",
]
```

---

### Phase 3: Daemon RPC Handler

**Objective**: Implement structured RPC command handling in daemon.

#### 3.1 Add Command Request Handler

**File**: `packages/soothe/src/soothe/daemon/_handlers.py`

**Implementation**:

1. Add `_handle_command_request()` method:
```python
async def _handle_command_request(self, client_id: str, msg: dict[str, Any]) -> None:
    """Handle structured RPC command requests (RFC-404)."""
    command = msg.get("command")
    thread_id = msg.get("thread_id")
    params = msg.get("params", {})
    
    try:
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
```

2. Add `_send_command_response()` method:
```python
async def _send_command_response(
    self,
    command: str,
    data: dict[str, Any] | None = None,
    error: str | None = None
) -> None:
    """Send structured command response."""
    response = {
        "type": "command_response",
        "command": command,
    }
    if data is not None:
        response["data"] = data
    if error is not None:
        response["error"] = error
    await self._broadcast(response)
```

#### 3.2 Implement Individual Command Handlers

**Add 13 handler methods** (in `_handlers.py`):

```python
async def _cmd_clear(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Clear thread history."""
    if not thread_id:
        raise ValueError("Thread ID required")
    await self._runner.clear_thread(thread_id)
    await self._broadcast({"type": "clear", "thread_id": thread_id})
    return {"cleared": True, "thread_id": thread_id}

async def _cmd_exit(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Stop thread and mark for exit."""
    if not thread_id:
        raise ValueError("Thread ID required")
    # Stop thread execution
    if self._query_running:
        await self._cancel_query()
    # Mark thread as stopped
    await self._broadcast({
        "type": "status",
        "state": "stopped",
        "thread_id": thread_id,
        "exit_requested": True
    })
    return {"exit": True, "thread_id": thread_id}

async def _cmd_quit(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Stop thread and mark for exit (same as exit)."""
    return await self._cmd_exit(thread_id, params)

async def _cmd_detach(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Mark thread as detached."""
    if not thread_id:
        raise ValueError("Thread ID required")
    # Mark thread as detached (continues running)
    await self._broadcast({
        "type": "status",
        "state": "detached",
        "thread_id": thread_id,
    })
    return {"detached": True, "thread_id": thread_id}

async def _cmd_cancel(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Cancel running query."""
    if not thread_id:
        raise ValueError("Thread ID required")
    if self._query_running:
        await self._cancel_query()
    return {"cancelled": True, "thread_id": thread_id}

async def _cmd_memory(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Query memory stats."""
    if not thread_id:
        raise ValueError("Thread ID required")
    stats = await self._runner.memory_stats()
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

async def _cmd_review(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Query conversation history."""
    if not thread_id:
        raise ValueError("Thread ID required")
    # Get conversation from thread state
    state = await self._runner.aget_state({"configurable": {"thread_id": thread_id}})
    messages = state.values.get("messages", [])
    review = []
    for msg in messages[-20:]:
        review.append({
            "timestamp": "",
            "type": msg.__class__.__name__,
            "content": str(msg.content)[:200]
        })
    return {"review": review}

async def _cmd_thread(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Thread operations."""
    action = params.get("action")
    thread_id_param = params.get("id")
    
    if action == "archive":
        if not thread_id_param:
            raise ValueError("Thread ID required for archive")
        # Archive thread (mark as archived in registry)
        # TODO: Implement thread archiving
        return {"archived": True, "thread_id": thread_id_param}
    else:
        raise ValueError(f"Unknown thread action: {action}")

async def _cmd_resume(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Resume thread."""
    thread_id_param = params.get("thread_id")
    if not thread_id_param:
        raise ValueError("Thread ID required for resume")
    # Resume thread logic (similar to resume_thread message)
    # TODO: Implement thread resuming
    return {"resumed": True, "thread_id": thread_id_param}

async def _cmd_autopilot_dashboard(self, thread_id: str | None, params: dict) -> dict[str, Any]:
    """Show autopilot dashboard."""
    if not thread_id:
        raise ValueError("Thread ID required")
    # TODO: Get autopilot state from runner
    dashboard = {
        "status": "idle",
        "iterations": 0,
        "goals_completed": 0,
        "goals_active": 0,
        "active_goals": []
    }
    return {"autopilot_dashboard": dashboard}
```

#### 3.3 Update Message Router

**File**: `packages/soothe/src/soothe/daemon/_handlers.py`

**Update** `handle_websocket_message()` (or equivalent message routing method):
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

### Phase 4: Wire CLI Event Processor

**Objective**: Connect event processor to handle `command_response` events.

**File**: `packages/soothe-cli/src/soothe_cli/shared/event_processor.py`

#### 4.1 Add Command Response Handler

**Implementation**:
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
    elif event_type == "clear":
        self._handle_clear_event(event)
    elif event_type == "error":
        self._handle_error_event(event)

def _handle_command_response(self, event: dict[str, Any]) -> None:
    """Handle command response from daemon (RFC-404)."""
    command = event.get("command")
    data = event.get("data")
    error = event.get("error")
    
    if error:
        self.renderer.print_error(error)
        return
    
    # Find command entry in registry
    from soothe_cli.shared.command_router import find_command_by_daemon_command
    entry = find_command_by_daemon_command(command)
    
    # Render with handler
    if entry and entry.get("handler") and data:
        handler = entry["handler"]
        handler(self.renderer.console, data)
    else:
        # Default: pretty print JSON
        import json
        from rich.panel import Panel
        self.renderer.console.print(
            Panel(
                json.dumps(data, indent=2, default=str),
                title=command,
                border_style="cyan"
            )
        )
```

#### 4.2 Add Clear Event Handler

**Implementation**:
```python
def _handle_clear_event(self, event: dict[str, Any]) -> None:
    """Handle clear event from daemon."""
    # Clear local UI state
    self.renderer.clear()
```

---

### Phase 5: Update Tests

**Objective**: Add tests for new architecture.

#### 5.1 CLI Tests

**File**: `packages/soothe-cli/tests/unit/shared/test_command_router.py` (new file)

**Test cases**:
- Registry structure validation
- `parse_slash_command()` extracts command and query
- `validate_command()` checks thread/query requirements
- `route_slash_command()` routes CLI commands locally
- `route_slash_command()` sends RPC requests for daemon commands
- `route_slash_command()` sends plain text for routing commands
- `find_command_by_daemon_command()` finds correct entry
- Rendering functions work with mock data

#### 5.2 Daemon Tests

**File**: `packages/soothe/tests/unit/daemon/test_command_handlers.py` (new file)

**Test cases**:
- Message router handles `command_request` type
- `_handle_command_request()` dispatches to correct handler
- Each RPC handler returns correct data structure
- Error handling returns structured errors
- `_send_command_response()` formats response correctly

#### 5.3 Integration Tests

**File**: `packages/soothe-cli/tests/integration/test_command_flow.py` (new file)

**Test cases**:
- End-to-end: CLI `/memory` → daemon → CLI renders
- End-to-end: CLI `/clear` → daemon clears → CLI clears UI
- Error: CLI `/memory` no thread → daemon error → CLI displays error
- Routing: CLI `/browser query` → daemon routes → events stream

---

### Phase 6: Documentation

**Objective**: Update documentation for new architecture.

#### 6.1 Update RFC-400

**File**: `docs/specs/RFC-400-daemon-communication.md`

**Add message type**:
```typescript
// WebSocket message types (RFC-400 extension for RFC-404)
type: "input" | "command_request" | "subscription" | "status" | "event" | 
      "subscription_confirmed" | "error"

// Command request schema (RFC-404)
{
  "type": "command_request",
  "command": string,
  "thread_id": string | null,
  "params": object | null,
  "client_id": string
}

// Command response schema (RFC-404 extension)
{
  "type": "command_response",
  "command": string,
  "data": object | null,
  "error": string | null
}
```

#### 6.2 Update CLAUDE.md

**File**: `CLAUDE.md`

**Add section**: Slash Command Architecture
- CLI-only commands: `/help`, `/keymaps`
- Daemon RPC commands: 13 structured API commands
- Daemon routing commands: 5 behavior indicators
- Registry-based routing with metadata

#### 6.3 Update User Guide

**File**: `docs/user_guide.md`

**Add**: Command categories explanation for users

---

## Verification Checklist

Run after all phases complete:

```bash
# Verify daemon has no legacy command handling
grep "_SLASH_COMMANDS_HELP\|_KEYBOARD_SHORTCUTS_HELP\|_handle_command" packages/soothe/src/soothe/daemon/_handlers.py
# Should return nothing

# Verify daemon has no CLI imports
grep "from soothe_cli" packages/soothe/src/soothe/daemon/*.py
# Should return nothing

# Verify daemon has no Rich imports
grep "from rich" packages/soothe/src/soothe/daemon/*.py packages/soothe/src/soothe/foundation/*.py
# Should return nothing

# Verify CLI has unified registry
grep "COMMANDS\|command_router" packages/soothe-cli/src/soothe_cli/shared/*.py
# Should find both

# Verify daemon has RPC handlers
grep "_handle_command_request\|_cmd_clear\|_cmd_memory" packages/soothe/src/soothe/daemon/_handlers.py
# Should find all

# Verify event processor handles command_response
grep "_handle_command_response" packages/soothe-cli/src/soothe_cli/shared/event_processor.py
# Should find it

# Run full verification
./scripts/verify_finally.sh
# Should pass all checks

# Run tests
pytest packages/soothe-cli/tests/unit/shared/test_command_router.py
pytest packages/soothe/tests/unit/daemon/test_command_handlers.py
# Should pass all tests
```

---

## Implementation Notes

### Helper Functions

**Add to command_router.py**:
```python
def find_command_by_daemon_command(daemon_command: str) -> dict | None:
    """Find command entry by daemon command name."""
    for cmd_name, entry in COMMANDS.items():
        if entry.get("daemon_command") == daemon_command:
            return entry
    return None
```

### WebSocketClient.request_response()

**Verify SDK client has this method**: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`

If not, add:
```python
async def request_response(
    self,
    request: dict[str, Any],
    response_type: str,
    timeout: float = 5.0
) -> dict[str, Any]:
    """Send request and wait for specific response type."""
    await self.send(request)
    
    start_time = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start_time < timeout:
        event = await self.read_event()
        if event and event.get("type") == response_type:
            return event
    
    raise TimeoutError(f"No {response_type} received within {timeout}s")
```

### Params Parsing

**Add detailed parsing** to `parse_command_params()`:
```python
def parse_command_params(entry: dict[str, Any], query: str) -> dict[str, Any]:
    """Parse query into params based on schema."""
    schema = entry.get("params_schema", {})
    if not schema:
        return {}
    
    parts = query.strip().split()
    params = {}
    
    # Map parts to schema keys
    schema_keys = list(schema.keys())
    for i, part in enumerate(parts):
        if i < len(schema_keys):
            key = schema_keys[i]
            params[key] = part
    
    return params
```

---

## Risk Mitigation

**Risk**: Breaking existing command usage
- **Mitigation**: Cut change is intentional - clean start
- **Mitigation**: All commands categorized, no missing commands

**Risk**: WebSocketClient.request_response() missing
- **Mitigation**: Verify in SDK, add if missing (implementation notes above)

**Risk**: Params parsing incomplete
- **Mitigation**: Add detailed parsing logic (implementation notes above)

---

## Estimated Effort

**Phase 1**: 1 hour (delete files, verify)
**Phase 2**: 3 hours (registry, router, rendering functions)
**Phase 3**: 4 hours (13 RPC handlers, dispatcher)
**Phase 4**: 1 hour (event processor wiring)
**Phase 5**: 3 hours (test suite)
**Phase 6**: 1 hour (documentation)

**Total**: ~13 hours (medium-large refactoring)

---

## Success Criteria

From RFC-404 verification criteria:
1. ✅ Daemon has NO knowledge of CLI-only commands
2. ✅ CLI has single unified command registry
3. ✅ RPC commands use structured protocol
4. ✅ Routing commands use plain text input
5. ✅ Zero backward compatibility code
6. ✅ All tests pass
7. ✅ Daemon linting: zero errors
8. ✅ CLI does not import daemon runtime

---

## Next Steps

1. Execute Phase 1: Remove old code
2. Execute Phase 2: CLI registry/router
3. Execute Phase 3: Daemon RPC handlers
4. Execute Phase 4: Event processor wiring
5. Execute Phase 5: Tests
6. Execute Phase 6: Documentation
7. Run verification suite
8. Mark IG-177 as completed

---

## References

- RFC-404: Slash Command Architecture
- RFC-400: Daemon Communication Protocol
- RFC-500: CLI/TUI Architecture
- IG-176: Move Rich to CLI
- RFC-000: System Conceptual Design