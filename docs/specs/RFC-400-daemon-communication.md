# RFC-400: Unified Daemon Communication Protocol

**RFC**: 0013
**Title**: Unified Daemon Communication Protocol for WebSocket IPC
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-03-19
**Updated**: 2026-04-14
**Dependencies**: RFC-000, RFC-001, RFC-500

## Abstract

This RFC defines a WebSocket-based daemon communication protocol serving all clients (local CLI/TUI and remote/web) through a unified transport. HTTP REST retained for health checks and stateless CRUD. The protocol specifies JSON message format, security requirements, and implementation interface, eliminating Unix domain socket complexity while enabling local and remote connectivity.

**Updates**:
- **2026-04-14**: Added `skills_list` / `skills_list_response` and `invoke_skill` / `invoke_skill_response` RPCs for remote-safe skill metadata and invocation; ordering rule for `invoke_skill` (response before stream events for that turn).
- **2026-03-29**: Simplified to WebSocket-only bidirectional streaming, removed Unix socket (stability issues)
- **2026-03-29**: Merged RFC-100 daemon readiness, added lifecycle phases and readiness handshake
- **2026-03-28**: Added daemon lifecycle semantics, client detachment behavior

## Problem & Solution

### Problem: Multi-Transport Complexity
- Stale socket files after crashes blocked connections
- Large payload disconnects on Unix socket streaming
- Dual transport debugging/testing/maintenance burden
- Different failure modes confused users

### Solution: WebSocket-Only Transport
- Port-based binding, no filesystem cleanup
- Proven stability for large payloads
- Single code path for all clients
- Browser compatible, network-accessible

**Design Goals**: Transport simplicity, local performance (~0.5ms localhost), remote capability, backward compatibility, clear specification.

**Non-Goals**: Authentication/authorization (external services), user management, multi-tenancy.

## Guiding Principles

1. **Protocol-Transport Separation** - Message format independent of transport
2. **Minimal Wire Overhead** - JSON for debuggability (not binary)
3. **Streaming-First Design** - WebSocket for bidirectional streaming, HTTP REST for stateless CRUD

## Architecture

### Component Flow

```
WebSocket/HTTP REST → Protocol Handler → Message Router → SootheRunner
```

**Components**:
- **WebSocket Server**: All clients, default `127.0.0.1:8765`, CORS validation, connection limits
- **HTTP REST Server**: Health checks, CRUD, default `127.0.0.1:8766`
- **Protocol Handler**: Transport-agnostic processing, validation, routing
- **Message Router**: Route to SootheRunner, stream events, handle commands

### Event Bus Architecture

Pub/sub event bus routes events to clients by thread subscriptions.

**Components**:
- `EventBus`: Pub/sub with `publish(topic, event)`, `subscribe(topic, queue)`
- `ClientSessionManager`: Manages sessions, client IDs, thread subscriptions
- `ClientSession`: Unique ID, event queue (maxsize=100), sender task

**Topic Routing**: Events to `thread:{thread_id}` topics. Clients subscribe to specific threads only.

**Event Flow**: SootheRunner → EventBus.publish → Client queues → Sender task → Transport → Client.

### Architectural Constraints

1. Single daemon instance per user (PID lock)
2. Unified JSON message schema across transports
3. Transport abstraction (no transport-specific logic in protocol)
4. No built-in authentication (external services)
5. Thread subscription required for events (BREAKING)
6. Client isolation enforced
7. Daemon persistent across client sessions

## Daemon Lifecycle Semantics

### Daemon Persistence

**Startup Triggers**: Auto-start (non-TUI/TUI if daemon not running), manual `soothe daemon start`

**Shutdown Triggers**: Explicit `soothe daemon stop`, SIGTERM/SIGKILL, foreground Ctrl+C

**NOT Shutdown**: Client exit, disconnect, thread completion, connection loss

### Lifecycle States

| State | Meaning | Client Action |
|-------|---------|---------------|
| `starting` | Process exists, startup begun | No requests |
| `warming` | Transports/core initializing | Bounded retry |
| `ready` | Runner warmup complete | Proceed with queries |
| `degraded` | Subsystem unhealthy | May reject requests |
| `error` | Startup/runtime failure | Surface error |

### Startup Phases

1. **Bind**: Establish WebSocket, expose `starting` or `warming`
2. **Warm**: Initialize SootheRunner, thread/session support
3. **Readiness validation**: Internal validation, transition to `ready`

### Readiness Handshake

1. Client connects WebSocket
2. Requests lifecycle/readiness state
3. Daemon returns state
4. Proceed only after `ready`
5. Surface specific failure on `degraded`/`error`

**Rules**: Wait on readiness state (not connection liveness), boundedly retry on `starting`/`warming`, no queries before `ready`.

### Stale Daemon Cleanup

Before restart: Check PID file → Remove if process dead → Connect if running → Clean PID before spawning.

### Client Exit Semantics

**`/exit` or `/quit`** (Stop Thread + Exit):
- Stop thread (if running), exit TUI, daemon keeps running
- Confirmation required if thread running
- Thread → `suspended` or stays `idle`

**`/detach`** (Keep Thread Running + Exit):
- Exit TUI, thread continues, daemon keeps running
- Confirmation required if thread running
- Thread state unchanged

**Double Ctrl+C**: First cancels job; second within 1s triggers `/quit` with confirmation.

### Query Cancellation on Disconnect

| Disconnect | Query Behavior | Rationale |
|------------|----------------|-----------|
| Ctrl+C (no detach) | Cancel | User intent: "stop" |
| Crash/network failure | Cancel | Safe default, prevent waste |
| `/detach` | Continue | User intent: "leave running" |

**Protocol**: Track `detach_requested` flag, client thread ownership, cancel if no detach requested.

## Protocol Specification

### Message Format

All messages JSON with required `type` field.

### Client → Server Messages

| Type | Fields | Description |
|------|--------|-------------|
| `input` | `text` (req), `autonomous` (opt), `max_iterations` (opt) | User input |
| `command` | `cmd` (req) | Slash command (`/help`, `/exit`, `/quit`, `/detach`, `/plan`, `/memory`, `/context`, `/policy`, `/history`, `/review`, `/resume`, `/clear`, `/config`) |
| `resume_thread` | `thread_id` (req) | Resume thread (doesn't auto-subscribe) |
| `subscribe_thread` | `thread_id` (req) | Subscribe to thread events |
| `detach` | None | Notify daemon client detaching |
| `skills_list` | `request_id` (opt) | List skills configured for the daemon agent (wire-safe metadata, no paths) |
| `invoke_skill` | `skill` (req), `args` (opt string), `request_id` (opt) | Resolve `SKILL.md` on the daemon host, acknowledge client, then run one agent turn with the composed prompt |

### Server → Client Messages

| Type | Fields | Description |
|------|--------|-------------|
| `status` | `state` (req), `thread_id` (req), `client_id` (req), `input_history` (opt) | Daemon state (`idle`, `running`, `stopped`, `stopping`, `detached`) |
| `subscription_confirmed` | `thread_id` (req), `client_id` (req) | Thread subscription confirmed |
| `event` | `thread_id` (req), `namespace` (req), `mode` (req), `data` (req) | Stream event from SootheRunner |
| `command_response` | `content` (req) | Slash command output |
| `error` | `code` (req), `message` (req), `details` (opt) | Protocol error |
| `skills_list_response` | `skills` (req, array of `{name, description, source?, version?}`), `request_id` (opt) | Catalog rows for autocomplete and listings |
| `invoke_skill_response` | `echo` (req, object: `skill_name`, `description`, `source`, `body`, `args`), `request_id` (opt) | Echo for UI (`SkillMessage`) before the turn streams |

**Error Codes**: `INVALID_MESSAGE`, `RATE_LIMITED`, `INTERNAL_ERROR`, `DAEMON_STARTING`, `DAEMON_BUSY`, `DAEMON_DEGRADED`, `DAEMON_ERROR`, `SKILL_NOT_FOUND`, `SKILL_LOAD_FAILED`.

### Skill RPC ordering

For `invoke_skill`, the daemon MUST send a single `invoke_skill_response` (matching `request_id` when present) **before** any `event` stream messages for that turn. Clients may block on `request_response` until the response arrives; stream chunks must not precede it on the same connection.

### Required Sequence

Connect → `new_thread` or `resume_thread` → `subscribe_thread` → `subscription_confirmed` → Receive events.

## Transport Specification

### WebSocket

- **Wire**: WebSocket text frames (RFC 6455)
- **URL**: `ws://127.0.0.1:8765` (configurable)
- **Flow**: Handshake → CORS validation → JSON exchange → Close frame
- **Status**: ✅ Implemented (`src/soothe/daemon/transports/websocket.py`)

### HTTP REST

- **Wire**: HTTP/1.1 with JSON bodies
- **URL**: `http://localhost:8766/api/v1`
- **Use**: Health checks, CRUD, thread listing, config, historical data
- **Status**: ✅ Implemented (`src/soothe/daemon/transports/http_rest.py`)

**Integration**: WebSocket for streaming, HTTP REST for CRUD.

## Security Requirements

### Transport Security

- **Local**: Bind `127.0.0.1` (no external access), CORS validation
- **Production**: Reverse proxy for TLS, auth (API keys/JWT/OAuth), rate limiting, IP whitelist, logging
- **Desktop**: Local WebSocket only, optional separate auth

### CORS

Pattern matching (`http://localhost:*`, `http://127.0.0.1:*`), validate `Origin` header.

### Input Validation

Message size limit: 10MB. Schema validation on required fields.

## Breaking Changes (v2.0)

### Mandatory Thread Subscription

**Before**: All clients received all events (global broadcast), no subscription, event mixing.

**After**: MUST send `subscribe_thread`, no global broadcast, client isolation.

### Client Migration

**TUI**: Connect → new_thread/resume_thread → receive thread_id → **subscribe_thread** (NEW) → events.

**CLI**: Connect → new_thread → receive thread_id → **subscribe_thread** (NEW) → input → events.

**WebSocket**: On `status` message → send `subscribe_thread` with `thread_id`.

### Event Message Changes

**Added**: `thread_id` field (required for routing).

### Status Message Changes

**Added**: `client_id` field (unique per client).

### Migration Strategy

**Hard-Cut**: Remove broadcast code, update all clients atomically, reject events without subscription, no backward compatibility.

**Rationale**: Complexity reduction, security/correctness (event mixing), clean architecture.

## Implementation Checklist

### Core
- [ ] WebSocket server/client (`src/soothe/daemon/transports/websocket.py`, `websocket_client.py`)
- [ ] HTTP REST server for CRUD (`src/soothe/daemon/transports/http_rest.py`)
- [ ] Message serialization, broadcast, singleton lock
- [ ] CORS validation, connection limits

### Lifecycle
- [ ] Lifecycle states (starting, warming, ready, degraded, error)
- [ ] Staged startup (bind, warm, readiness validation)
- [ ] Readiness handshake protocol
- [ ] Stale daemon cleanup (PID file)
- [ ] DAEMON_BUSY rejection

### Event Bus
- [ ] EventBus pub/sub
- [ ] ClientSessionManager
- [ ] ClientSession with sender task
- [ ] Thread subscription mechanism
- [ ] Client isolation

### Migration
- [ ] Remove Unix socket client references
- [ ] Remove UnixSocketConfig
- [ ] Delete `unix_socket.py`, `client.py`
- [ ] Remove stale socket cleanup
- [ ] Update documentation

## Changelog

### 2026-03-29
- BREAKING: Removed Unix socket, WebSocket-only
- Merged RFC-100 readiness architecture
- Added lifecycle states, startup phases, handshake
- Added DAEMON_BUSY, readiness error codes

### 2026-03-28
- Added daemon lifecycle semantics
- Documented exit/detach behavior with thread warnings

## References

- RFC-000: System Conceptual Design
- RFC-001: Core Modules Architecture
- RFC-500: CLI TUI Architecture
- RFC-100: Coreagent Runtime (merged)

---

*WebSocket as sole bidirectional transport, eliminating Unix socket complexity while enabling local and remote connectivity.*