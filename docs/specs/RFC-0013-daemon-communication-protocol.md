# RFC-0013: Unified Daemon Communication Protocol

**RFC**: 0013
**Title**: Unified Daemon Communication Protocol for WebSocket IPC
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-03-19
**Updated**: 2026-03-29
**Dependencies**: RFC-0001, RFC-0002, RFC-0003

## Abstract

This RFC defines a WebSocket-based daemon communication protocol that serves all clients (local CLI/TUI and remote/web) through a unified transport. The protocol specifies a JSON-based message format, security requirements, and implementation interface. HTTP REST is retained for health checks and stateless CRUD operations. This architecture eliminates Unix domain socket complexity while enabling both local and remote client connectivity.

**Update (2026-03-29)**: Simplified transport architecture to WebSocket-only bidirectional streaming. Removed Unix domain socket transport due to stability issues (stale socket files, large payload disconnects). HTTP REST retained for health checks.

**Update (2026-03-29)**: Merged RFC-0023 daemon readiness architecture. Added explicit lifecycle phases, staged startup, and readiness handshake protocol.

**Update (2026-03-28)**: Added Daemon Lifecycle Semantics section clarifying daemon persistence, client detachment, and shutdown behavior across all interaction modes.

## Motivation

### Problem: Multi-Transport Complexity

The previous architecture supported both Unix domain sockets and WebSockets, creating:
1. **Stale socket files** - After daemon crashes, socket files remained and blocked new connections
2. **Large payload disconnects** - Unix socket streaming failed during large event payloads
3. **Maintenance burden** - Two transports required dual debugging, testing, and code paths
4. **Inconsistent behavior** - Different failure modes between transports confused users

### Solution: WebSocket-Only Transport

WebSocket provides:
1. **No stale files** - Port-based binding, no filesystem cleanup required
2. **Proven stability** - WebSocket handles large payloads reliably
3. **Single code path** - One transport for all clients (local and remote)
4. **Browser compatible** - Web browsers connect directly
5. **Remote access** - Network-accessible for remote CLI/web clients

### Design Goals

1. **Transport simplicity**: Single bidirectional transport (WebSocket) for all streaming
2. **Local performance**: localhost WebSocket has negligible overhead vs Unix socket
3. **Remote capability**: Same transport works for local and remote clients
4. **Backward compatibility**: Message protocol unchanged, only transport differs
5. **Clear specification**: Formal message schemas and implementation requirements

### Non-Goals

- **Authentication and authorization**: Handled by external services (reverse proxies, API gateways, etc.)
- **User management**: Not within Soothe's scope
- **Multi-tenancy**: Soothe is single-tenant by design

## Guiding Principles

### Principle 1: Protocol-Transport Separation

The message protocol (what we send) is independent of the transport mechanism (how we send it). WebSocket and HTTP REST use the same JSON message format, with transport-specific framing.

### Principle 2: Minimal Wire Overhead

The protocol uses JSON for simplicity and debuggability, not binary formats. Message framing:
- **WebSocket**: Native text frames (no delimiter needed)
- **HTTP REST**: Standard HTTP request/response

### Principle 3: Streaming-First Design

WebSocket is designed for bidirectional streaming. HTTP REST provides stateless CRUD operations. Clients and servers exchange asynchronous messages over persistent WebSocket connections.

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────┐
│                    SootheDaemon                         │
│                                                         │
│  ┌─────────────────┐       ┌─────────────────┐        │
│  │   WebSocket     │       │   HTTP REST     │        │
│  │   Server        │       │   Server        │        │
│  └────────┬────────┘       └────────┬────────┘        │
│           └────────┬────────────────┘                  │
│           ┌────────▼────────┐                          │
│           │  Protocol       │                          │
│           │  Handler        │                          │
│           └────────┬────────┘                          │
│           ┌────────▼────────┐                          │
│           │  Message Router │                          │
│           └────────┬────────┘                          │
│           ┌────────▼────────┐                          │
│           │  SootheRunner   │                          │
│           └─────────────────┘                          │
└─────────────────────────────────────────────────────────┘
```

### Component Responsibilities

**WebSocket Server**: Serve all clients (CLI, TUI, browser, remote). Default: `127.0.0.1:8765`. Security: CORS validation, connection limits. Performance: ~0.5ms latency (localhost), ~10-50ms (remote). For production, use reverse proxy for auth/TLS.

**HTTP REST Server**: Health checks, daemon status, CRUD operations. Default: `127.0.0.1:8766`. Stateless request/response. For production, use reverse proxy for auth/TLS.

**Protocol Handler**: Transport-agnostic message processing, validation, routing, broadcast, client lifecycle.

**Message Router**: Route messages to SootheRunner, stream events to clients, handle slash commands, thread management.

### Data Flow

**Client → Server (WebSocket)**:
```
Client → WebSocket Transport → Protocol Handler → Message Router → SootheRunner
```

**Server → Client (WebSocket)**:
```
SootheRunner → Event Stream → Protocol Handler → WebSocket Transport → Client(s)
```

**Client → Server (HTTP REST)**:
```
Client → HTTP REST → Protocol Handler → Response
```

### Event Bus Architecture

The daemon uses a pub/sub event bus to route events to connected clients based on thread subscriptions, providing client isolation and preventing event mixing.

**Components**:
- **EventBus**: Pub/sub with `publish(topic, event)`, `subscribe(topic, queue)`, `unsubscribe(topic, queue)`
- **ClientSessionManager**: Manages sessions, creates client IDs, handles thread subscriptions
- **ClientSession**: Unique `client_id`, transport reference, thread subscriptions set, event queue (maxsize=100), sender task

**Topic-Based Routing**: Events published to `thread:{thread_id}` topics. Clients subscribe to specific threads, only receiving events for subscribed threads.

**Client Isolation**: Each client has unique ID, dedicated event queue, independent sender task, and thread subscription set. Events from different threads never mix.

**Event Flow**: SootheRunner emits event → EventBus.publish(`thread:{thread_id}`, event) → Routes to subscribed client queues → ClientSession.sender_task sends to transport → Client receives event.

### Architectural Constraints

1. **Single daemon instance**: Only one daemon per user (PID lock)
2. **Unified message schema**: All transports use identical JSON format
3. **Transport abstraction**: Protocol layer has no transport-specific logic
4. **No built-in authentication**: Security handled by external services
5. **Thread subscription required**: All clients MUST subscribe to threads to receive events (BREAKING CHANGE)
6. **Client isolation enforced**: Events routed to subscribed clients only
7. **Daemon persistence**: Daemon remains running across client sessions; only explicit shutdown stops it

### Daemon Lifecycle Semantics

The daemon follows a persistent lifecycle model where it remains running across multiple client sessions. This design provides seamless user experience without requiring manual daemon management.

#### Daemon Persistence Behavior

**Daemon Startup Triggers**:
- **Auto-start (Non-TUI)**: When running `soothe -p "prompt"` and daemon not running, daemon auto-starts
- **Auto-start (TUI)**: When launching TUI and daemon not running, daemon auto-starts
- **Manual start**: `soothe daemon start` explicitly starts daemon (foreground or background mode)

**Daemon Shutdown Triggers**:
- **Explicit stop**: Only `soothe daemon stop` command shuts down daemon
- **SIGTERM/SIGKILL**: System signals to daemon process (manual intervention)
- **Foreground Ctrl+C**: When daemon runs with `--foreground`, Ctrl+C shuts it down

**NOT Shutdown Triggers**:
- Client exit (TUI `/exit`, `/quit`, `/detach`, double Ctrl+C)
- Client disconnect (non-TUI request completion)
- Thread completion
- Client connection loss

#### Client-Server Interaction Patterns

**Non-TUI Mode (Headless Single-Prompt)**:
```
Client → Check daemon status
  → If running: Connect via WebSocket, create thread, execute request, thread finishes, client disconnects
  → If not running: Start daemon, connect via WebSocket, create thread, execute request, thread finishes, client disconnects
Daemon → Remains running in background after client disconnect
```

**TUI Mode (Interactive)**:
```
Client → Check daemon status
  → If running: Connect via WebSocket, create/resume thread, interactive session
  → If not running: Start daemon, connect via WebSocket, create thread, interactive session
Interactive session:
  → /exit or /quit → Client exits, daemon keeps running
  → /detach → Client detaches, daemon keeps running
  → Ctrl+C once → Cancel current job, stay in TUI
  → Ctrl+C twice (within 1s) → Client exits, daemon keeps running
Daemon → Remains running after TUI exits
```

#### Daemon State Transitions

| Trigger | Previous State | New State | Notes |
|---------|---------------|-----------|-------|
| `soothe daemon start` | None | `running` | Daemon initialized, serving requests |
| Client connects | `running` | `running` | No state change, client attached |
| Client disconnects | `running` | `running` | No state change, client detached |
| Thread finishes | `running` | `running` | No state change, thread complete |
| `soothe daemon stop` | `running` | `stopped` | Explicit shutdown |
| SIGTERM | `running` | `stopping` → `stopped` | Graceful shutdown |
| SIGKILL | `running` | `stopped` | Immediate termination |

#### Client Exit Semantics

**`/exit` and `/quit` Commands** (Stop Thread + Exit Client):
- **Behavior**: Stop running thread (if any), exit TUI client, daemon remains running
- **Confirmation Required**: YES - Must prompt user for confirmation before stopping thread
- **Protocol**:
  1. Check if thread is running
  2. If running: Show confirmation dialog "Thread {id} is running. Stop thread and exit? (y/n)"
  3. If user confirms: Send stop/cancel to daemon, wait for thread to stop, then detach
  4. If user declines: Stay in TUI
  5. If thread idle: Exit immediately without confirmation
- **Thread State**: Thread transitions to `suspended` (if was running) or stays `idle`
- **User Message**: "Thread stopped. TUI exited. Daemon running (PID: XXX). Use 'soothe daemon stop' to shutdown."
- **Keymap**: `Ctrl+Q` (same as `/quit`)

**`/detach` Command** (Keep Thread Running + Exit Client):
- **Behavior**: Detach TUI client, thread keeps running, daemon remains running
- **Confirmation Required**: YES - Must prompt user for confirmation if thread is running
- **Protocol**:
  1. Check if thread is running
  2. If running: Show confirmation dialog "Thread {id} is running. Detach and leave it running? (y/n)"
  3. If user confirms: Send `detach` message, close connection immediately
  4. If user declines: Stay in TUI
  5. If thread idle: Exit immediately without confirmation
- **Thread State**: Thread continues running (no state change)
- **User Message**: "Detached from thread. Thread still running. Daemon running (PID: XXX). Reconnect with 'soothe thread continue'."
- **Keymap**: `Ctrl+D` (same as `/detach`)

**Double Ctrl+C (TUI Mode)**:
- **Behavior**: First Ctrl+C cancels current job; second Ctrl+C within 1s triggers `/quit` behavior (stop thread + exit)
- **Protocol**:
  1. First Ctrl+C: Cancel current job
  2. Second Ctrl+C (within 1s): Trigger `/quit` behavior with confirmation
  3. If user confirms: Stop thread and exit
  4. If user declines: Stay in TUI
- **User Message** (after first Ctrl+C): "Job cancelled. Press Ctrl+C again within 1s to quit."
- **User Message** (after second Ctrl+C): Show confirmation: "Thread {id} is running. Stop thread and exit? (y/n)"
- **Timing**: 1 second window between Ctrl+C presses to prevent accidental exit
- **Keymap**: `Ctrl+C` (twice)

#### Thread Warning on Exit

**For `/exit` and `/quit`** (Stop Thread + Exit):
When TUI client executes `/exit` or `/quit` while thread is in `running` state:
- **Warning Prompt**: "Thread {id} is running. Stop thread and exit? (y/n)"
- **User Response 'y'**: Stop thread (cancel query), exit TUI, daemon keeps running, thread transitions to `suspended`
- **User Response 'n'**: Stay in TUI, thread continues running
- **Idle Thread**: No warning, exit immediately

**For `/detach`** (Keep Thread Running + Exit):
When TUI client executes `/detach` while thread is in `running` state:
- **Warning Prompt**: "Thread {id} is running. Detach and leave it running? (y/n)"
- **User Response 'y'**: Exit TUI, daemon keeps running, thread continues running
- **User Response 'n'**: Stay in TUI, thread continues running
- **Idle Thread**: No warning, exit immediately

This prevents accidental exit during active execution while respecting user intent and providing clear distinction between stop-and-exit vs detach-and-continue.

#### Client Disconnect Query Cancellation

When a client disconnects from the daemon, the daemon must decide whether to cancel the active query or let it continue running.

**Cancellation Behavior**:

| Disconnect Type | Query Behavior | Rationale |
|-----------------|----------------|-----------|
| Ctrl+C (no detach) | Cancel immediately | User intent: "stop and exit" |
| Client crash | Cancel immediately | Safe default, prevent orphan queries |
| Network failure | Cancel immediately | Safe default, avoid API waste |
| `/detach` or Ctrl+D | Continue running | User intent: "leave it running" |

**Protocol Implementation**:

1. **ClientSession** tracks `detach_requested: bool` flag (default: `False`)
2. **ClientSessionManager** tracks `_client_thread_ownership: dict[str, str]` (client_id → thread_id)
3. On `detach` message: set `session.detach_requested = True`, send acknowledgment
4. On query start: `claim_thread_ownership(client_id, thread_id)`
5. On session removal: if `not detach_requested` and client owns thread, cancel it

**Cancel Flow**:
```
Client disconnects (no detach)
  → remove_session(client_id)
  → Check: detach_requested?
     → False
  → Get owned thread_id
  → _cancel_thread(thread_id)
  → Query cancelled (asyncio.Task.cancel)
  → Thread transitions to "idle" or "suspended"
```

**Detach Flow**:
```
Client sends "detach" message
  → session.detach_requested = True
  → Send acknowledgment
  → Client closes connection
  → remove_session(client_id)
  → Check: detach_requested?
     → True
  → Skip cancel, query continues
```

This ensures that:
- Accidental disconnects (Ctrl+C, crashes) don't waste API credits
- Intentional detachment (`/detach`) preserves long-running queries
- Daemon persistence is maintained (IG-085 compliance)

### Daemon Startup Readiness

The daemon startup follows explicit lifecycle phases to avoid false readiness signals.

#### Lifecycle States

The daemon SHALL expose the following lifecycle states:

| State | Meaning | Client Behavior |
|-------|---------|-----------------|
| `starting` | Process exists, startup begun | No request-serving assumed |
| `warming` | Transports/core initializing, not query-ready | Boundedly retry |
| `ready` | Runner warmup complete, query execution safe | Proceed with thread/input |
| `degraded` | Reachable but subsystem unhealthy | May reject or limit requests |
| `error` | Startup/runtime failure prevents servicing | Surface explicit error |

#### Startup Phases

1. **Bind phase**: Establish WebSocket transport early, expose state as `starting` or `warming`
2. **Warm phase**: Initialize `SootheRunner`, thread/session support, request-serving dependencies
3. **Readiness validation**: Perform trivial internal control-path validation, transition to `ready` only on success

#### Readiness Handshake Protocol

The handshake replaces implicit readiness with explicit lifecycle query:

1. Client connects to daemon WebSocket transport
2. Client requests lifecycle/readiness state
3. Daemon returns one of: `starting`, `warming`, `ready`, `degraded`, `error`
4. Client proceeds only after `ready`
5. If `degraded` or `error`, client surfaces specific failure (not generic timeout)

**Behavioral Rules**:
- Headless execution must wait on readiness state, not raw connection liveness
- Clients may retry boundedly while daemon reports `starting` or `warming`
- Clients must not send normal query execution requests before `ready`
- If readiness never arrives, error must reflect lifecycle state where known

#### Stale Daemon Cleanup

Before daemon restart, stale daemon processes must be cleaned:
- Check for existing PID file
- If PID file exists but process is dead, remove stale PID file
- If daemon is truly running, client connects to existing daemon
- If daemon restart needed, ensure clean PID state before spawning

No socket file cleanup required (WebSocket uses port binding, not filesystem).

#### DAEMON_BUSY Rejection

When a daemon is already processing a request for a thread:
- New requests for that thread return `DAEMON_BUSY` error code
- Client should surface "thread is busy" message, not retry blindly
- This prevents request queueing and overlap on single-thread execution

#### Readiness Error Codes

Error codes related to daemon lifecycle:

| Code | Meaning |
|------|---------|
| `DAEMON_STARTING` | Daemon is warming up, not yet ready |
| `DAEMON_BUSY` | Thread already processing a request |
| `DAEMON_DEGRADED` | Daemon reachable but subsystem unhealthy |
| `DAEMON_ERROR` | Startup or runtime failure |

#### Startup Instrumentation

The daemon SHOULD record timings for:
- bind start/end
- runner warmup
- transport readiness
- readiness validation
- lifecycle transition reason for `degraded` or `error`

This supports startup timeout diagnosis and regression detection.

### Abstract Schemas

**TransportMode**: Enumeration - `WEBSOCKET`, `HTTP_REST`

**WebSocketConfig**: `enabled`, `host` (default: `127.0.0.1`), `port` (default: `8765`), `tls_enabled`, `tls_cert`, `tls_key`, `cors_origins`

**HttpRestConfig**: `enabled`, `host` (default: `127.0.0.1`), `port` (default: `8766`), `tls_enabled`, `tls_cert`, `tls_key`, `cors_origins`

## Protocol Specification

### Message Format

All messages are JSON objects with a required `type` field.

#### Base Message Schema

```json
{
  "type": "string (required)",
  "...": "additional fields based on type"
}
```

### Client → Server Messages

#### Input Message
Send user input for processing.

```json
{
  "type": "input",
  "text": "string (required)",
  "autonomous": "boolean (optional, default: false)",
  "max_iterations": "integer (optional, default: null)"
}
```

#### Command Message
Send slash command.

```json
{
  "type": "command",
  "cmd": "string (required)"
}
```

Valid commands: `/help`, `/exit`, `/quit`, `/detach`, `/plan`, `/memory`, `/context`, `/policy`, `/history`, `/review`, `/resume`, `/clear`, `/config`.

#### Resume Thread Message
Resume specific conversation thread.

```json
{
  "type": "resume_thread",
  "thread_id": "string (required)"
}
```

Loads thread state, sets as active. Does NOT auto-subscribe client to thread.

#### Subscribe Thread Message
Subscribe to receive events for a thread.

```json
{
  "type": "subscribe_thread",
  "thread_id": "string (required)"
}
```

**Required Sequence**: Connect → `resume_thread` or `new_thread` → `subscribe_thread` → `subscription_confirmed` → Receive events.

#### Detach Message
Notify daemon client is detaching.

```json
{
  "type": "detach"
}
```

### Server → Client Messages

#### Status Message
Daemon state notification (sent on connect and state transitions).

```json
{
  "type": "status",
  "state": "string (idle|running|stopped|stopping|detached)",
  "thread_id": "string (required, may be empty)",
  "client_id": "string (required, assigned on connection)",
  "input_history": "array of strings (optional, last 100 entries)"
}
```

States: `idle` (ready), `running` (processing query), `stopped` (shutting down), `stopping` (received stop signal), `detached` (client detached).

#### Subscription Confirmed Message
Confirms successful thread subscription.

```json
{
  "type": "subscription_confirmed",
  "thread_id": "string (required)",
  "client_id": "string (required)"
}
```

#### Event Message
Stream event from SootheRunner.

```json
{
  "type": "event",
  "thread_id": "string (required)",
  "namespace": "array of strings (required)",
  "mode": "string (messages|updates|custom)",
  "data": "any (required)"
}
```

Events published to `thread:{thread_id}` topics. Only subscribed clients receive events. See RFC-0003 for complete event taxonomy.

#### Command Response Message
Output from slash command.

```json
{
  "type": "command_response",
  "content": "string (required)"
}
```

#### Error Message
Protocol error notification.

```json
{
  "type": "error",
  "code": "string (required)",
  "message": "string (required)",
  "details": "object (optional)"
}
```

Error codes: `INVALID_MESSAGE`, `RATE_LIMITED`, `INTERNAL_ERROR`.

## Transport Layer Specification

### WebSocket (Bidirectional Streaming)

**Wire Format**: WebSocket text frames (RFC 6455)

**Connection**: Client initiates handshake at `ws://host:port` → Server validates CORS → Exchange JSON messages in text frames → Close with WebSocket close frame.

**Default URL**: `ws://127.0.0.1:8765` (localhost), configurable via `SOOTHE_TRANSPORTS__WEBSOCKET__PORT`

**Status**: ✅ Fully Implemented (see `src/soothe/daemon/transports/websocket.py`, `websocket_client.py`)

### HTTP REST (Stateless CRUD)

**Wire Format**: HTTP/1.1 with JSON request/response bodies

**Connection**: Stateless HTTP request/response cycle. Base URL: `http://localhost:8766/api/v1`.

**Use Cases**: Health checks, daemon status, thread listing, configuration CRUD, historical data retrieval.

**Status**: ✅ Implemented (see `src/soothe/daemon/transports/http_rest.py`)

## WebSocket + REST Integration

### Protocol Usage

**Use WebSocket for**: Real-time streaming, bidirectional communication, active agent execution, low-latency event updates.

**Use HTTP REST for**: CRUD operations (thread management, configuration), file operations, health checks, historical data retrieval.

**Integration Pattern**: Web applications typically use REST for thread management and file operations, then switch to WebSocket for real-time streaming during agent execution. Desktop frameworks (Tauri/Electron) use WebSocket for streaming and HTTP REST for CRUD operations, with native OS integration via the backend layer.

## Security Requirements

### Transport Security

**WebSocket Localhost**: Default bind `127.0.0.1:8765` (not externally accessible). CORS validation prevents malicious local websites.

**Production (WebSocket/HTTP)**: Use reverse proxy (nginx, Caddy, Traefik) for TLS termination, authentication (API keys, JWT, OAuth), rate limiting, CORS validation, IP whitelisting, request logging. Soothe focuses on orchestration, reverse proxy handles security.

### CORS Configuration
Pattern matching for allowed origins (e.g., `http://localhost:*`, `http://127.0.0.1:*`). Validate `Origin` header, reject invalid origins.

### Deployment Patterns

**Local Development**: No authentication. WebSocket → Soothe Daemon. localhost binding provides security.

**Production**: Client → Reverse Proxy (Auth + TLS) → Soothe Daemon. Reverse proxy handles all security, clear separation of concerns.

**Desktop App**: Local WebSocket (127.0.0.1), no network exposure. Optional: Desktop app manages user authentication separately.

### Input Validation
Message size limit: 10MB. Schema validation checks required fields based on message type (`input`, `command`, `resume_thread`, etc.).

## Implementation Status

### Current (WebSocket)
- ✅ WebSocket server and client implemented in `src/soothe/daemon/transports/websocket.py`, `websocket_client.py`
- ✅ Message serialization, broadcast mechanism, singleton lock
- ✅ CORS validation, connection limits

### HTTP REST
- ✅ HTTP REST server for health checks and CRUD operations

## Naming Conventions

### Message Types

- **Format**: `snake_case` (e.g., `input`, `command`, `resume_thread`)
- **Namespace**: Client-to-server messages use simple nouns; server-to-client use descriptive names

### Event Types

- **Format**: `soothe.<component>.<action>` (e.g., `soothe.plan.step_started`)
- **Component**: Protocol name or subagent name
- **Action**: Past tense for completed actions (e.g., `projected`, `completed`), present for ongoing (e.g., `started`)

### Transport Identifiers

- **WebSocket**: Referenced as `"websocket"` in logs and metrics with connection metadata (remote_addr, origin)

## Error Handling

### Protocol Errors

**Invalid JSON**: `{"type":"error","code":"INVALID_JSON","message":"Failed to parse message as JSON","details":{"raw":"..."}}`

**Missing Required Field**: `{"type":"error","code":"INVALID_MESSAGE","message":"Message missing required field: type","details":{...}}`

**Unknown Message Type**: `{"type":"error","code":"UNKNOWN_MESSAGE_TYPE","message":"Unknown message type: unknown_type","details":{...}}`

## Examples

### WebSocket Connection (Local CLI/TUI)
```
Client → ws://127.0.0.1:8765
Server: {"type":"status","state":"idle","thread_id":"","client_id":"uuid-123"}
Client: {"type":"new_thread"}
Server: {"type":"status","state":"idle","thread_id":"abc123"}
Client: {"type":"subscribe_thread","thread_id":"abc123"}
Server: {"type":"subscription_confirmed","thread_id":"abc123"}
Client: {"type":"input","text":"hello"}
Server: {"type":"status","state":"running","thread_id":"abc123"}
Server: {"type":"event","thread_id":"abc123","namespace":[],"mode":"messages","data":[...]}
Server: {"type":"status","state":"idle","thread_id":"abc123"}
```

### WebSocket Connection (Remote/Web)
```
Client → wss://soothe.example.com (via reverse proxy with TLS/auth)
Server: {"type":"status","state":"idle",...}
Client: {"type":"input","text":"analyze code"}
Server: {"type":"event",...}
Server: {"type":"status","state":"idle","thread_id":"xyz789"}
```

**Production**: Use reverse proxy (wss://) with external authentication.

## Breaking Changes

### Version 2.0 Protocol Changes

**This RFC introduces BREAKING CHANGES to the daemon protocol.** All existing clients must be updated.

#### Mandatory Thread Subscription

**Before (v1.x)**:
- All clients received all events via global broadcast
- No subscription mechanism
- Events mixed when multiple clients connected

**After (v2.0)**:
- Clients MUST send `subscribe_thread` message to receive events
- No global broadcast - only subscribed clients receive events
- Complete client isolation between threads

#### Client Migration Required

**TUI Client** (`src/soothe/ux/tui/app.py`):
```python
# OLD: Just connect
await client.connect()

# NEW: Connect + subscribe
await client.connect()
await client.send_new_thread()  # or send_resume_thread(thread_id)
thread_id = await client.receive_thread_id()  # from status message
await client.subscribe_thread(thread_id)  # NEW: required
```

**CLI Headless** (`src/soothe/ux/cli/execution/daemon_runner.py`):
```python
# OLD: Just send input
await client.send_input(text)

# NEW: Subscribe first
await client.connect()
await client.send_new_thread()
thread_id = await client.receive_thread_id()
await client.subscribe_thread(thread_id)  # NEW: required
await client.send_input(text)
```

**WebSocket Clients**:
```javascript
// OLD: Just connect and listen
const ws = new WebSocket('ws://localhost:8765');
ws.onmessage = (event) => console.log(event.data);

// NEW: Subscribe after connection
const ws = new WebSocket('ws://localhost:8765');
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === 'status') {
    // Subscribe to thread
    ws.send(JSON.stringify({
      type: 'subscribe_thread',
      thread_id: msg.thread_id
    }));
  }
};
```

#### Event Message Changes

**Before (v1.x)**:
```json
{
  "type": "event",
  "namespace": [],
  "mode": "messages",
  "data": [...]
}
```

**After (v2.0)**:
```json
{
  "type": "event",
  "thread_id": "abc123",  // NEW: required for routing
  "namespace": [],
  "mode": "messages",
  "data": [...]
}
```

#### Status Message Changes

**Before (v1.x)**:
```json
{
  "type": "status",
  "state": "running",
  "thread_id": "abc123"
}
```

**After (v2.0)**:
```json
{
  "type": "status",
  "state": "running",
  "thread_id": "abc123",
  "client_id": "client-uuid-12345"  // NEW: unique per client
}
```

### Migration Strategy

**Hard-Cut Migration** - No backward compatibility:

1. **Remove old broadcast code** - Delete legacy `_broadcast()` fan-out logic
2. **Update all clients atomically** - TUI, CLI, WebSocket in single PR
3. **Require subscription** - Reject events without subscription
4. **Clean break** - No gradual migration, no fallback

**Rationale**:
- Maintaining backward compatibility adds complexity
- Event mixing is a security and correctness issue
- Clean architecture preferred over transitional code
- Single atomic update ensures consistency

## Migration Path

### Phase 1: WebSocket Client Update
**Goal**: Update CLI/TUI to use WebSocket client.

**Key Changes**:
- Modify `src/soothe/ux/cli/execution/daemon.py`: Use WebSocket client for all connections
- Remove Unix socket client references
- Ensure WebSocket client handles localhost connections correctly

### Phase 2: Transport Manager Simplification
**Goal**: Remove Unix socket from transport building.

**Key Changes**:
- Modify `src/soothe/daemon/transport_manager.py`: Remove Unix socket transport, WebSocket required
- Modify `src/soothe/daemon/server.py`: Remove Unix socket references
- Update error handling for WebSocket-only configuration

### Phase 3: Configuration Cleanup
**Goal**: Remove Unix socket configuration.

**Key Changes**:
- Modify `src/soothe/config.py`: Remove `UnixSocketConfig` section
- Update `config/config.yml`: Remove `transports.unix_socket` section
- Update `config/env.example`: Remove Unix socket environment variables
- Add deprecation warnings for old Unix socket env vars

### Phase 4: File Removal
**Goal**: Remove Unix socket implementation files.

**Key Changes**:
- Delete `src/soothe/daemon/transports/unix_socket.py`
- Delete `src/soothe/daemon/client.py` (Unix socket client)
- Remove stale socket cleanup logic from singleton.py

### Phase 5: Documentation Update
**Goal**: Update all documentation.

**Key Changes**:
- Update RFC-0013 (this document): Reflect WebSocket-only transport
- Update user guide: Daemon connection instructions
- Update changelog: Transport simplification entry

## Dependencies

- RFC-0001 (System Conceptual Design)
- RFC-0002 (Core Modules Architecture Design)
- RFC-0003 (CLI TUI Architecture Design - daemon IPC specification)

## Changelog

### 2026-03-29
- **BREAKING**: Removed Unix domain socket transport
- Simplified to WebSocket-only bidirectional streaming
- Removed stale socket file cleanup (no longer applicable)
- Removed UnixSocketConfig from abstract schemas
- Updated architecture diagram to single WebSocket transport
- Updated all examples to WebSocket-only
- Merged RFC-0023 daemon readiness content
- Added explicit lifecycle states (starting, warming, ready, degraded, error)
- Added staged startup architecture and readiness handshake protocol
- Added DAEMON_BUSY rejection and readiness error codes

### 2026-03-28
- Added Daemon Lifecycle Semantics section
- Clarified daemon persistence and client detachment behavior
- Documented /exit, /quit, /detach semantics with thread warnings

## Related Documents

- [RFC-0003](./RFC-0003.md) - CLI TUI Architecture Design (original daemon IPC)
- [RFC Index](./rfc-index.md) - All RFCs
- [Design Draft](../drafts/2026-03-29-websocket-only-transport-design.md) - WebSocket-only design rationale

---

*This RFC establishes WebSocket as the sole bidirectional transport for daemon communication, eliminating Unix socket complexity while enabling local and remote client connectivity.*