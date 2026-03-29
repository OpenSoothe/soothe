# RFC-0013: Unified Daemon Communication Protocol

**RFC**: 0013
**Title**: Unified Daemon Communication Protocol for Multi-Transport IPC
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-03-19
**Updated**: 2026-03-28
**Dependencies**: RFC-0001, RFC-0002, RFC-0003

## Abstract

This RFC defines a transport-agnostic daemon communication protocol that supports Unix domain sockets, WebSockets, and HTTP REST. The protocol specifies a common JSON-based message format, security requirements, and implementation interface. This architecture enables the Soothe daemon to serve both local CLI/TUI clients (via Unix socket) and remote/web clients (via WebSocket/HTTP) using the same protocol layer, while maintaining backward compatibility with existing clients.

**Update (2026-03-29)**: Merged RFC-0023 daemon readiness architecture. Added explicit lifecycle phases, staged startup, and readiness handshake protocol.

**Update (2026-03-28)**: Added Daemon Lifecycle Semantics section clarifying daemon persistence, client detachment, and shutdown behavior across all interaction modes.

## Motivation

### Problem: Single Transport Limitation

RFC-0003 defines the daemon IPC architecture using Unix domain sockets exclusively. This design has limitations:

1. **Browser incompatibility**: Web browsers cannot connect to Unix sockets, preventing web-based UI development
2. **Remote access**: Unix sockets are local-only, requiring SSH tunneling or local presence for remote access
3. **Mobile clients**: Mobile applications cannot connect to Unix sockets
4. **Infrastructure constraints**: Cloud deployments and containerized environments may prefer HTTP-based protocols

### Problem: No Protocol Specification

The current implementation in `src/soothe/cli/daemon/protocol.py` provides encoding/decoding utilities but lacks:
- Formal message schema definitions
- Transport abstraction layer
- Security requirements for different transport modes
- Versioning and compatibility guidelines

### Design Goals

1. **Transport independence**: Same message protocol over Unix socket, WebSocket, and HTTP REST
2. **Backward compatibility**: Existing Unix socket clients continue working unchanged
3. **Simplicity by default**: No built-in authentication - handled by external services
4. **Protocol evolution**: Versioning and extension mechanisms
5. **Clear specification**: Formal message schemas and implementation requirements

### Non-Goals

- **Authentication and authorization**: Handled by external services (reverse proxies, API gateways, etc.)
- **User management**: Not within Soothe's scope
- **Multi-tenancy**: Soothe is single-tenant by design

## Guiding Principles

### Principle 1: Protocol-Transport Separation

The message protocol (what we send) is independent of the transport mechanism (how we send it). Unix socket, WebSocket, and HTTP REST all use the same JSON message format, with transport-specific framing.

### Principle 2: Minimal Wire Overhead

The protocol uses JSON for simplicity and debuggability, not binary formats. Message framing is minimal:
- Unix socket: newline-delimited JSON lines
- WebSocket: native text frames (no newline needed)
- HTTP REST: standard HTTP request/response

### Principle 3: Streaming-First Design

The protocol is designed for bidirectional streaming (Unix socket, WebSocket), not request-response. HTTP REST provides stateless CRUD operations. Clients and servers exchange asynchronous messages over persistent connections.

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────┐
│                    SootheDaemon                         │
│                                                         │
│  ┌─────────────────┐       ┌─────────────────┐        │
│  │  Unix Socket    │       │   WebSocket     │        │
│  │  Server         │       │   Server        │        │
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

**Unix Socket Server**: Serve local CLI/TUI clients. Path: `$SOOTHE_HOME/soothe.sock`. Security: OS-level file permissions. Performance: ~0.1ms latency, ~1GB/s throughput. Backward compatible with RFC-0003.

**WebSocket Server**: Serve web/remote clients. Default: `127.0.0.1:8765`. Security: CORS validation, connection limits. Performance: ~0.5ms latency (localhost), ~10-50ms (remote). For production, use reverse proxy for auth/TLS.

**Protocol Handler**: Transport-agnostic message processing, validation, routing, broadcast, client lifecycle.

**Message Router**: Route messages to SootheRunner, stream events to clients, handle slash commands, thread management.

### Data Flow

**Client → Server**:
```
Client → Transport Layer → Protocol Handler → Message Router → SootheRunner
```

**Server → Client**:
```
SootheRunner → Event Stream → Protocol Handler → Transport Layer → Client(s)
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
  → If running: Connect, create thread, execute request, thread finishes, client disconnects
  → If not running: Start daemon, connect, create thread, execute request, thread finishes, client disconnects
Daemon → Remains running in background after client disconnect
```

**TUI Mode (Interactive)**:
```
Client → Check daemon status
  → If running: Connect, create/resume thread, interactive session
  → If not running: Start daemon, connect, create thread, interactive session
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

1. **Bind phase**: Establish minimal control transport early, expose state as `starting` or `warming`
2. **Warm phase**: Initialize `SootheRunner`, thread/session support, request-serving dependencies
3. **Readiness validation**: Perform trivial internal control-path validation, transition to `ready` only on success

#### Readiness Handshake Protocol

The handshake replaces implicit socket-based readiness with explicit lifecycle query:

1. Client connects to daemon control transport
2. Client requests lifecycle/readiness state
3. Daemon returns one of: `starting`, `warming`, `ready`, `degraded`, `error`
4. Client proceeds only after `ready`
5. If `degraded` or `error`, client surfaces specific failure (not generic timeout)

**Behavioral Rules**:
- Headless execution must wait on readiness state, not raw socket liveness
- Clients may retry boundedly while daemon reports `starting` or `warming`
- Clients must not send normal query execution requests before `ready`
- If readiness never arrives, error must reflect lifecycle state where known

#### Stale Daemon Cleanup

Before daemon restart, stale daemon processes must be cleaned:
- Check for existing PID file and socket file
- If PID file exists but process is dead, remove stale files
- If daemon is truly running, client connects to existing daemon
- If daemon restart needed, ensure clean socket/PID state before spawning

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

**TransportMode**: Enumeration - `UNIX_SOCKET`, `WEBSOCKET`, `HTTP_REST`

**UnixSocketConfig**: `enabled`, `path` (default: `~/.soothe/soothe.sock`)

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

### Unix Domain Socket
**Wire Format**: Newline-delimited JSON lines (JSONL)

**Connection**: Client connects to `$SOOTHE_HOME/soothe.sock` → Server sends initial `status` → Exchange messages (each terminated with `\n`) → Close on EOF/error.

**Status**: ✅ Fully Implemented (see `src/soothe/cli/daemon/server.py`, `client.py`, `protocol.py`)

### WebSocket
**Wire Format**: WebSocket text frames (RFC 6455)

**Connection**: Client initiates handshake at `ws://host:port` → Server validates CORS → Exchange JSON messages in text frames → Close with WebSocket close frame.

**Status**: ❌ Not Implemented (Phase 2, est. 3-5 days)

### HTTP REST Server
**Wire Format**: HTTP/1.1 with JSON request/response bodies

**Connection**: Stateless HTTP request/response cycle. Base URL: `http://localhost:8766/api/v1`.

**Status**: ❌ Not Implemented (Phase 1, FastAPI + Uvicorn, est. 5-7 days). See [rest-api-spec.md](./rest-api-spec.md) for complete API specification.

## WebSocket + REST Integration

### Protocol Usage

**Use WebSocket for**: Real-time streaming, bidirectional communication, active agent execution, low-latency event updates.

**Use HTTP REST for**: CRUD operations (thread management, configuration), file operations, health checks, historical data retrieval.

**Integration Pattern**: Web applications typically use REST for thread management and file operations, then switch to WebSocket for real-time streaming during agent execution. Desktop frameworks (Tauri/Electron) use WebSocket for streaming and HTTP REST for CRUD operations, with native OS integration via the backend layer.

## Security Requirements

### Transport Security

**Unix Socket**: Default permissions `0o600` (owner-only), location `$SOOTHE_HOME/soothe.sock`. Filesystem permissions + PID lock prevent local privilege escalation.

**WebSocket Localhost**: Default bind `127.0.0.1:8765` (not externally accessible). CORS validation prevents malicious local websites.

**Production (WebSocket/HTTP)**: Use reverse proxy (nginx, Caddy, Traefik) for TLS termination, authentication (API keys, JWT, OAuth), rate limiting, CORS validation, IP whitelisting, request logging. Soothe focuses on orchestration, reverse proxy handles security.

### CORS Configuration
Pattern matching for allowed origins (e.g., `http://localhost:*`, `http://127.0.0.1:*`). Validate `Origin` header, reject invalid origins.

### Deployment Patterns

**Local Development**: No authentication. Unix Socket/WebSocket → Soothe Daemon. Filesystem permissions provide security.

**Production**: Client → Reverse Proxy (Auth + TLS) → Soothe Daemon. Reverse proxy handles all security, clear separation of concerns.

**Desktop App**: Local WebSocket (127.0.0.1), no network exposure. Optional: Desktop app manages user authentication separately.

### Input Validation
Message size limit: 10MB. Schema validation checks required fields based on message type (`input`, `command`, `resume_thread`, etc.).

## Implementation Status

### Current (Unix Socket)
- ✅ Unix socket server, client, and protocol handlers implemented in `src/soothe/cli/daemon/`
- ✅ Message serialization, broadcast mechanism, singleton lock, and socket cleanup implemented

### Planned (WebSocket)
- ❌ WebSocket server, client, protocol abstraction, CORS validation (Est. 6.5 days)
- Authentication handled by external services (not in scope)

## Naming Conventions

### Message Types

- **Format**: `snake_case` (e.g., `input`, `command`, `resume_thread`)
- **Namespace**: Client-to-server messages use simple nouns; server-to-client use descriptive names

### Event Types

- **Format**: `soothe.<component>.<action>` (e.g., `soothe.plan.step_started`)
- **Component**: Protocol name or subagent name
- **Action**: Past tense for completed actions (e.g., `projected`, `completed`), present for ongoing (e.g., `started`)

### Transport Identifiers

- **Unix socket**: Referenced as `"unix_socket"` in logs and metrics
- **WebSocket**: Referenced as `"websocket"` with connection metadata (remote_addr, origin)

## Error Handling

### Protocol Errors

**Invalid JSON**: `{"type":"error","code":"INVALID_JSON","message":"Failed to parse message as JSON","details":{"raw":"..."}}`

**Missing Required Field**: `{"type":"error","code":"INVALID_MESSAGE","message":"Message missing required field: type","details":{...}}`

**Unknown Message Type**: `{"type":"error","code":"UNKNOWN_MESSAGE_TYPE","message":"Unknown message type: unknown_type","details":{...}}`

## Examples

### Unix Socket
```
Client → ~/.soothe/soothe.sock
Server: {"type":"status","state":"idle","thread_id":"","input_history":[]}
Client: {"type":"input","text":"hello"}
Server: {"type":"status","state":"running","thread_id":"abc123"}
Server: {"type":"event","namespace":[],"mode":"messages","data":[...]}
Server: {"type":"status","state":"idle","thread_id":"abc123"}
```

### WebSocket
```
Client → ws://localhost:8765
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

### Phase 1: Core Infrastructure (Week 1)
**Goal**: Implement event bus and client session management.

**Key Changes**:
- Create `src/soothe/daemon/event_bus.py` - EventBus class with pub/sub
- Create `src/soothe/daemon/client_session.py` - ClientSession and ClientSessionManager
- Create `src/soothe/daemon/transports/base.py` - Transport protocol with `send()` method
- Add unit tests for EventBus and ClientSessionManager (>90% coverage)

### Phase 2: Daemon Server Integration (Week 2)
**Goal**: Integrate event bus into daemon server.

**Key Changes**:
- Modify `src/soothe/daemon/server.py`: Initialize EventBus/ClientSessionManager, replace `_broadcast()` with event bus publish
- Modify `src/soothe/daemon/_handlers.py`: Add `subscribe_thread` handler, pass client_id to all handlers
- Update message routing to use topics

### Phase 3: Transport Layer Updates (Week 3)
**Goal**: Update all transports to use client sessions.

**Key Changes**:
- Modify Unix socket transport: Call `session_manager.create_session()`, track client_id, implement `send()` method
- Modify WebSocket transport: Same changes as Unix socket
- Modify HTTP REST transport: Session management, event streaming endpoint

### Phase 4: Client Updates - BREAKING CHANGE (Week 4)
**Goal**: Update all clients to use thread subscriptions.

**Key Changes**:
- Modify `src/soothe/daemon/client.py`: Add `subscribe_thread()` and `receive_subscription_confirmed()`
- Modify TUI (`src/soothe/ux/tui/app.py`): Call `subscribe_thread()` after connection
- Modify CLI headless (`src/soothe/ux/cli/execution/daemon_runner.py`): Subscribe to thread
- Update WebSocket client examples
- Remove legacy broadcast code

**Migration**: Hard-cut migration with no backward compatibility. All clients updated atomically in single PR.

### Phase 5: Testing & Documentation (Week 5)
**Goal**: Comprehensive testing and documentation.

**Key Changes**:
- Integration tests: Multiple clients, thread isolation, event routing
- Stress tests: Concurrent clients, high event throughput, queue overflow
- Documentation: Protocol changes, migration guide, event bus architecture
- Observability: Client tracking, subscription status, event routing metrics

**Deliverables**: Test coverage >90%, performance benchmarks, complete migration documentation.

## Dependencies

- RFC-0001 (System Conceptual Design)
- RFC-0002 (Core Modules Architecture Design)
- RFC-0003 (CLI TUI Architecture Design - daemon IPC specification)

## Changelog

### 2026-03-29
- Merged RFC-0023 daemon readiness content
- Added explicit lifecycle states (starting, warming, ready, degraded, error)
- Added staged startup architecture and readiness handshake protocol
- Added stale daemon cleanup and DAEMON_BUSY rejection
- Added readiness error codes and startup instrumentation

### 2026-03-28
- Added Daemon Lifecycle Semantics section
- Clarified daemon persistence and client detachment behavior
- Documented /exit, /quit, /detach semantics with thread warnings

## Related Documents

- [RFC-0003](./RFC-0003.md) - CLI TUI Architecture Design (original daemon IPC)
- [RFC Index](./rfc-index.md) - All RFCs
- Implementation Guide (TBD) - WebSocket implementation guide

---

*This RFC establishes the foundation for multi-transport daemon communication while maintaining complete backward compatibility with RFC-0003's Unix socket design.*
