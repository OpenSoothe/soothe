# RFC-450: Unified Daemon Communication Protocol

**RFC**: 450
**Title**: Unified Daemon Communication Protocol for WebSocket IPC
**Status**: Draft
**Kind**: Architecture Design + Protocol Specification
**Created**: 2026-03-19
**Updated**: 2026-06-28
**Dependencies**: RFC-000, RFC-001, RFC-500, RFC-614, RFC-403, RFC-900
**Related**: RFC-620 (Channel Architecture), RFC-228 (Autopilot Job IPC), RFC-503 (Loop-First UX), RFC-504 (Loop Management CLI Commands), RFC-454 (Slash Command Architecture)

## Abstract

This RFC defines a WebSocket-based daemon communication protocol serving all clients (local CLI/TUI and remote/web) through a unified transport. HTTP REST is retained for health checks and stateless CRUD. The protocol specifies a unified message envelope, schema validation, error standardization, versioning and capability negotiation, message type taxonomy, naming conventions, and the AsyncAPI documentation strategy.

This is a **clean-break protocol design**. The protocol-1 wire contract is defined as a complete replacement for the previous ad-hoc wire format. There is no legacy compatibility layer, no dual-path dispatch, and no gradual migration window. The daemon and SDK are updated simultaneously; clients connecting with the old format are rejected at the handshake stage.

The design draws on standards research documented in `docs/analysis/ws-api-standards-comparison.md` (AsyncAPI 3.0, JSON-RPC 2.0, graphql-ws, STOMP) and the current-state review in `docs/analysis/ws-request-submit-api-design-review.md`. The protocol adopts the structural pattern — not the ecosystem — from each standard: JSON-RPC's `method`/`params`/`id` structure, graphql-ws's connection lifecycle and subscription semantics, and AsyncAPI's machine-readable specification format.

**Updates**:
- **2026-06-28**: RFC rewritten to incorporate the unified protocol-1 wire contract. New sections added: message envelope format (§5), schema validation (§6), error standardization (§7), versioning and capability negotiation (§8), message type taxonomy (§9), naming conventions (§10), and AsyncAPI documentation strategy (§11). The previous ad-hoc message format, error codes, and connection sequence are replaced. RFC-460 (the standalone specification RFC) is deleted; this RFC is now the single source of truth for the daemon WebSocket protocol.
- **2026-04-29**: Clarified stream-event payload semantics for StrangeLoop: daemon forwards tool telemetry and explicit goal-completion output events; execute-phase assistant prose suppression is enforced at emission boundary (see RFC-401 §6.6, RFC-614).
- **2026-04-14**: Added `models_list` / `models_list_response` so clients list models from the daemon host `SootheConfig`; `input` may carry optional `model` and `model_params` for a per-turn override resolved on the daemon.
- **2026-04-14**: Added `skills_list` / `skills_list_response` and `invoke_skill` / `invoke_skill_response` RPCs for remote-safe skill metadata and invocation; ordering rule for `invoke_skill` (response before stream events for that turn).
- **2026-03-29**: Simplified to WebSocket-only bidirectional streaming, removed Unix socket (stability issues)
- **2026-03-29**: Merged RFC-100 daemon readiness, added lifecycle phases and readiness handshake
- **2026-03-28**: Added daemon lifecycle semantics, client detachment behavior

---

## 1. Problem & Solution

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

**Design Goals**: Transport simplicity, local performance (~0.5ms localhost), remote capability, clear specification.

**Non-Goals**: Authentication/authorization (external services), user management, multi-tenancy.

---

## 2. Guiding Principles

1. **Protocol-Transport Separation** — Message format independent of transport
2. **Minimal Wire Overhead** — JSON for debuggability (not binary)
3. **Streaming-First Design** — WebSocket for bidirectional streaming, HTTP REST for stateless CRUD
4. **Borrow the Structural Pattern, Not the Ecosystem** — The protocol adopts the envelope shape and error model from JSON-RPC 2.0, the connection lifecycle from graphql-ws, and the spec format from AsyncAPI — but does not adopt JSON-RPC batch semantics as mandatory, GraphQL query language, or STOMP frame wire format. Each standard contributes its strongest idea; none is adopted wholesale.

---

## 3. Architecture

### Component Flow

```
WebSocket/HTTP REST → Transport Layer (decode + validate) → Message Router → SootheRunner
```

**Components**:
- **WebSocket Server**: All clients, default `127.0.0.1:8765`, CORS validation, connection limits
- **HTTP REST Server**: Health checks, CRUD, default `127.0.0.1:8766`
- **Transport Layer**: Transport-agnostic processing — JSON decode, envelope validation, Pydantic schema validation, router dispatch
- **Message Router**: Route to SootheRunner, stream events, handle commands

### Event Bus Architecture

Pub/sub event bus routes events to clients by loop subscriptions.

**Components**:
- `EventBus`: Pub/sub with `publish(topic, event)`, `subscribe(topic, queue)`
- `ClientSessionManager`: Manages sessions, client IDs, loop subscriptions
- `ClientSession`: Unique ID, event queue (maxsize=100), sender task

**Topic Routing**: Events to `loop:{loop_id}` topics via `loop_event_topic()`. Clients subscribe to specific loops only.

**Event Flow**: SootheRunner → EventBus.publish → Client queues → Sender task → Transport → Client.

### Architectural Constraints

1. Single daemon instance per user (PID lock)
2. Unified JSON message schema across transports
3. Transport abstraction (no transport-specific logic in protocol)
4. No built-in authentication (external services)
5. Loop subscription required for events
6. Client isolation enforced
7. Daemon persistent across client sessions

---

## 4. Daemon Lifecycle Semantics

### Daemon Persistence

**Startup Triggers**: Auto-start (non-TUI/TUI if daemon not running), manual `soothed start`

**Shutdown Triggers**: Explicit `soothed stop`, SIGTERM/SIGKILL, foreground Ctrl+C

**NOT Shutdown**: Client exit, disconnect, loop completion, connection loss

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
2. Sends `connection_init` with `accept_proto: ["1"]` and capabilities
3. Daemon responds with `connection_ack` including `readiness_state`
4. Proceed only after `readiness_state: "ready"`
5. Surface specific failure on `degraded`/`error`

**Rules**: Wait on readiness state (not connection liveness), boundedly retry on `starting`/`warming`, no queries before `ready`.

### Stale Daemon Cleanup

Before restart: Check PID file → Remove if process dead → Connect if running → Clean PID before spawning.

### Client Exit Semantics

**`/exit` or `/quit`** (Stop Loop + Exit):
- Stop loop (if running), exit TUI, daemon keeps running
- Confirmation required if loop running
- Loop → `suspended` or stays `idle`

**`/detach`** (Keep Loop Running + Exit):
- Exit TUI, loop continues, daemon keeps running
- Confirmation required if loop running
- Loop state unchanged

**Double Ctrl+C**: First cancels job; second within 1s triggers `/quit` with confirmation.

### Query Cancellation on Disconnect

| Disconnect | Query Behavior | Rationale |
|------------|----------------|-----------|
| Ctrl+C (no detach) | Cancel | User intent: "stop" |
| Crash/network failure | Cancel | Safe default, prevent waste |
| `/detach` | Continue | User intent: "leave running" |

**Protocol**: Track `detach_requested` flag, client thread ownership, cancel if no detach requested.

---

## 5. Message Envelope Format

### 5.1 Unified Envelope

The protocol SHALL use a unified `{proto, type, method, params, id}` envelope that combines JSON-RPC 2.0's `method`/`params`/`id` structure with graphql-ws's `type` semantics for message class distinction.

**Rationale**: No single standard covers both the RPC mode (`loop_get`, `job_create`) and the streaming subscription mode (`loop_events` → event stream). A hybrid envelope separates the *message class* (request vs subscription vs heartbeat) from the *operation name* (`loop_get` vs `loop_events`), eliminating the previous `type`/`cmd`/`command` collision.

### 5.2 Envelope Structure

```json
{
  "proto": "1",
  "type": "request",
  "method": "loop_get",
  "params": {"loop_id": "abc123", "verbose": true},
  "id": "req_001"
}
```

| Field | Required | Applies To | Description |
|-------|----------|-----------|-------------|
| `proto` | Yes | All messages | Protocol version string (`"1"`). Per-message version detection. |
| `type` | Yes | All messages | Message class: `"request"`, `"response"`, `"notification"`, `"subscribe"`, `"next"`, `"error"`, `"complete"`, `"unsubscribe"`, `"connection_init"`, `"connection_ack"`, `"ping"`, `"pong"`, `"disconnect"`, `"receipt_response"`. |
| `method` | Conditional | request, notification, subscribe | RPC method or subscription target name (e.g., `"loop_get"`, `"loop_input"`, `"loop_events"`). |
| `params` | Conditional | request, notification, subscribe, connection_init | Structured parameters object. All operation-specific fields MUST reside here. |
| `id` | Conditional | request, subscribe, response, next, error, complete | Operation correlation ID. **Present = response expected; absent = fire-and-forget.** |
| `result` | Conditional | response (success) | The result data object. |
| `error` | Conditional | error | `{code, message, data}` structured error object (see §7). |
| `payload` | Conditional | next | Event data for a subscription stream. |
| `receipt` | Optional | any notification | Receipt ID for delivery confirmation (see §5.7). |

### 5.3 Why Not Pure JSON-RPC 2.0

JSON-RPC 2.0's `{jsonrpc, method, params, id}` envelope is elegant for RPC but cannot model server-initiated streaming. A `loop_events` subscription produces N streaming events over time — JSON-RPC has no concept of "multiple results for one request." The `type` field resolves this: `type: "subscribe"` starts an operation, `type: "next"` delivers stream events, `type: "complete"` terminates it.

Pure JSON-RPC would require encoding streaming as repeated `result` objects with the same `id`, with no explicit termination signal — leaving the client unable to distinguish "stream paused" from "stream ended."

### 5.4 Why Not AsyncAPI-Style Flat Envelope

An AsyncAPI-style envelope (`{type, payload, request_id, version}`) merges the operation name into `type` (e.g., `type: "loop_get"`), which is what the previous protocol did. This causes two problems:

1. **Collision**: `type: "command"` was used by both slash commands (`{cmd: "/exit"}`) and RPC commands (`{command: "autopilot_status"}`). There was no way to distinguish them structurally.
2. **Flat params**: Operation fields sat at the top level alongside protocol fields (`type`, `request_id`), creating naming collision risk and making schema validation of the operation payload awkward.

The hybrid separates `type` (message class) from `method` (operation name), and nests operation fields in `params`.

### 5.5 Concrete Examples

**RPC Request → Response** (`loop_get`):
```json
// Client → Server
{"proto":"1", "type":"request", "method":"loop_get", "params":{"loop_id":"abc"}, "id":"r1"}

// Server → Client (success)
{"proto":"1", "type":"response", "result":{"loop_id":"abc", "status":"running"}, "id":"r1"}

// Server → Client (error)
{"proto":"1", "type":"error", "error":{"code":-32200, "message":"Loop not found", "data":{"loop_id":"abc"}}, "id":"r1"}
```

**Notification** (`loop_input`, fire-and-forget):
```json
// Client → Server (no id = no response expected)
{"proto":"1", "type":"notification", "method":"loop_input", "params":{"loop_id":"abc", "content":"hello"}}

// With receipt (client requests delivery confirmation)
{"proto":"1", "type":"notification", "method":"loop_input", "params":{"loop_id":"abc", "content":"hello"}, "receipt":"rc1"}

// Server → Client (receipt confirmation)
{"proto":"1", "type":"receipt_response", "receipt":"rc1"}
```

**Subscription Lifecycle** (`loop_events`):
```json
// Client → Server
{"proto":"1", "type":"subscribe", "method":"loop_events", "params":{"loop_id":"abc", "stream_delivery":"adaptive"}, "id":"s1"}

// Server → Client (stream event)
{"proto":"1", "type":"next", "id":"s1", "payload":{"namespace":"assistant", "mode":"text", "data":"Hello!"}}

// Server → Client (stream complete — explicit termination)
{"proto":"1", "type":"complete", "id":"s1"}

// Client → Server (unsubscribe early)
{"proto":"1", "type":"unsubscribe", "id":"s1"}
```

**Connection Handshake** (`connection_init` / `connection_ack`):
```json
// Client → Server
{"proto":"1", "type":"connection_init", "params":{"client_version":"0.5.0", "capabilities":["streaming","batch","receipts"]}}

// Server → Client
{"proto":"1", "type":"connection_ack", "result":{"server_version":"0.5.0", "protocol_version":"1", "capabilities":["streaming","batch","receipts","heartbeat"], "readiness_state":"ready"}}
```

### 5.6 Batch Support

JSON-RPC 2.0 batch semantics (array of requests → array of responses) MAY be used for CLI bulk queries (list+get+tree in one round-trip):

```json
// Client → Server
[
  {"proto":"1", "type":"request", "method":"loop_get", "params":{"loop_id":"a"}, "id":"1"},
  {"proto":"1", "type":"request", "method":"loop_get", "params":{"loop_id":"b"}, "id":"2"},
  {"proto":"1", "type":"notification", "method":"loop_detach", "params":{"loop_id":"a"}}
]

// Server → Client (responses only for items with id; notifications produce no response)
[
  {"proto":"1", "type":"response", "result":{...}, "id":"1"},
  {"proto":"1", "type":"response", "result":{...}, "id":"2"}
]
```

**Rules**:
1. A batch is a JSON array of valid protocol-1 messages.
2. The server SHALL process each item independently and return an array of responses (one per item with an `id`).
3. Notifications in a batch produce no response entries.
4. If the array is empty or not a valid JSON array, the server SHALL return a single `error` message with code `-32600` (`INVALID_REQUEST`).
5. Batch support is a capability — the client MUST declare `"batch"` in `connection_init` capabilities to use it (see §8.2).

### 5.7 Receipt Mechanism

The optional `receipt` field (inspired by STOMP's `receipt` frame) provides delivery confirmation for fire-and-forget notifications:

1. The client includes a `receipt` field (any unique string) on a notification message.
2. The server SHALL respond with `{"proto":"1", "type":"receipt_response", "receipt":"<id>"}` after the notification is accepted and enqueued.
3. Receipt support is a capability — the client MUST declare `"receipts"` in `connection_init` capabilities.
4. If the client sends a `receipt` field but did not declare the capability, the server SHALL ignore the field (no `receipt_response` is sent).

---

## 6. Schema Validation

### 6.1 Architecture

Every message SHALL be validated against a Pydantic model **at the transport boundary** — before router dispatch — on **all transport paths**.

```
┌─────────────────────────────────────────────────────────────────┐
│                    Transport Layer                               │
│  (FastAPI WebSocket / asyncio TCP / future transports)           │
│                                                                  │
│  1. Decode raw bytes → dict                                      │
│  2. Validate envelope (proto, type presence)                     │
│  3. Look up Pydantic model by (type, method)                     │
│  4. model_validate(params) → validated params or -32602 error    │
│  5. Pass validated params to router                              │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│                    Router Layer                                   │
│                                                                  │
│  - Receives validated, typed params (not raw dict)               │
│  - No inline `if not loop_id:` checks needed                     │
│  - Dispatches to handler by (type, method)                       │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│                    Handler Layer                                  │
│                                                                  │
│  - Business logic only                                           │
│  - Trusts params are schema-valid (no re-validation)             │
│  - Returns result dict or raises ProtocolError                   │
└──────────────────────────────────────────────────────────────────┘
```

**Why transport boundary, not router**: Validation MUST run on *every* transport path. The previous asyncio TCP path skipped validation entirely. Centralizing at the transport entry point (before the router) ensures all paths are covered. The router then receives already-validated params, eliminating the ~15 duplicated `if not loop_id:` checks.

### 6.2 Wire Schema Registry

A **wire schema registry** maps `(type, method)` tuples to Pydantic models. The registry is the authoritative mapping between wire message shapes and validation logic.

```python
# packages/soothe-daemon/src/soothe_daemon/protocol/schemas.py

from __future__ import annotations
from typing import Any, Literal, Union
from pydantic import BaseModel, Field


class LoopGetParams(BaseModel):
    """Params for method=loop_get, type=request."""

    loop_id: str = Field(..., min_length=1, description="Loop identifier")
    verbose: bool = Field(default=False, description="Include verbose details")
    tree: bool = Field(default=False, description="Include checkpoint tree")


class LoopInputParams(BaseModel):
    """Params for method=loop_input, type=request or notification."""

    loop_id: str = Field(..., min_length=1)
    content: str | dict[str, Any] = Field(..., description="User input text or structured content")
    autonomous: bool = False
    max_iterations: int | None = Field(default=None, gt=0)
    preferred_subagent: str | None = None
    model: str | None = Field(default=None, pattern=r"^[a-z]+:.+$")
    model_params: dict[str, Any] | None = None
    attachments: list[dict[str, str]] | None = None
    intent_hint: str | None = None
    response_schema: dict[str, Any] | None = None
    response_schema_name: str | None = None
    response_schema_strict: bool | None = None
    clarification_mode: str | None = Field(default=None, pattern=r"^(auto|manual)$")
    clarification_answer: bool = False
    clarification_answers: list[str] | None = None


class JobCreateParams(BaseModel):
    """Params for method=job_create, type=request."""

    goal: str = Field(..., min_length=1, description="Job goal text")
    workspace: str | None = None
    user_id: str | None = None
    autonomous: bool = False
    max_iterations: int | None = Field(default=None, gt=0)
    guidance: str | None = None
    intent_hint: str | None = None


class SubscribeParams(BaseModel):
    """Params for type=subscribe, method=loop_events."""

    loop_id: str = Field(..., min_length=1)
    stream_delivery: Literal["batch", "adaptive", "streaming"] = "adaptive"
    wire_tier: Literal["full", "compact"] = "full"


class ConnectionInitParams(BaseModel):
    """Params for type=connection_init."""

    client_version: str = Field(..., description="Client software version")
    capabilities: list[str] = Field(default_factory=list)
```

The registry maps `(type, method)` tuples to these models:

```python
# Maps (type, method) → params model
PARAMS_REGISTRY: dict[tuple[str, str | None], type[BaseModel]] = {
    ("request", "loop_get"): LoopGetParams,
    ("request", "loop_list"): LoopListParams,
    ("request", "loop_tree"): LoopTreeParams,
    ("request", "loop_prune"): LoopPruneParams,
    ("request", "loop_delete"): LoopDeleteParams,
    ("request", "loop_new"): LoopNewParams,
    ("request", "loop_reattach"): LoopReattachParams,
    ("request", "loop_detach"): LoopDetachParams,
    ("request", "loop_state_get"): LoopStateGetParams,
    ("request", "loop_state_update"): LoopStateUpdateParams,
    ("request", "loop_execution_state_fetch"): LoopExecutionStateFetchParams,
    ("request", "loop_cards_fetch"): LoopCardsFetchParams,
    ("notification", "loop_input"): LoopInputParams,
    ("request", "loop_input"): LoopInputParams,
    ("subscribe", "loop_events"): SubscribeParams,
    ("request", "job_create"): JobCreateParams,
    ("request", "job_status"): JobStatusParams,
    ("request", "job_pause"): JobPauseParams,
    ("request", "job_resume"): JobResumeParams,
    ("request", "job_cancel"): JobCancelParams,
    ("request", "job_dag"): JobDagParams,
    ("request", "job_guidance"): JobGuidanceParams,
    ("request", "daemon_status"): DaemonStatusParams,
    ("request", "daemon_shutdown"): DaemonShutdownParams,
    ("request", "config_get"): ConfigGetParams,
    ("request", "skills_list"): SkillsListParams,
    ("request", "models_list"): ModelsListParams,
    ("request", "invoke_skill"): InvokeSkillParams,
    ("request", "mcp_status"): McpStatusParams,
    ("request", "auth"): AuthParams,
    ("request", "auth_refresh"): AuthRefreshParams,
    ("request", "rpc_command"): RpcCommandParams,
    ("notification", "slash_command"): SlashCommandParams,
    ("subscribe", "autopilot_events"): AutopilotSubscribeParams,
    ("notification", "disconnect"): DisconnectParams,
    ("connection_init", None): ConnectionInitParams,
}
```

### 6.3 Validation Function

```python
# packages/soothe-daemon/src/soothe_daemon/protocol/validation.py

from pydantic import ValidationError


def validate_message(msg: dict[str, Any]) -> list[str]:
    """Validate a wire message against the schema registry.

    Args:
        msg: Raw decoded message dict.

    Returns:
        List of validation error strings. Empty if valid.
    """
    # 1. Envelope validation
    proto = msg.get("proto")
    if proto != "1":
        return [f"Unsupported or missing protocol version: {proto!r}. Expected '1'."]

    msg_type = msg.get("type")
    if not msg_type:
        return ["Missing required field: type"]

    if msg_type not in VALID_TYPES:
        return [f"Unknown message type: {msg_type!r}"]

    # 2. Look up params schema
    method = msg.get("method")
    schema = PARAMS_REGISTRY.get((msg_type, method))

    if schema is None:
        return [f"Unknown method {method!r} for type {msg_type!r}"]

    # 3. Validate params
    params = msg.get("params", {})
    try:
        schema.model_validate(params)
    except ValidationError as e:
        return [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]

    return []
```

### 6.4 Validation Injection Point

Validation SHALL be invoked at the transport boundary — in every transport's message receive path, *before* calling `router._handle_message()`:

```python
# channels/websocket.py (FastAPI WebSocket path)
errors = validate_message(msg_dict)
if errors:
    await ws.send_text(encode_websocket_text({
        "proto": "1", "type": "error",
        "error": {"code": -32602, "message": "Invalid params", "data": {"errors": errors}},
        "id": msg_dict.get("id"),
    }))
    return

await router._handle_message(client_id, msg_dict)

# server/core.py (asyncio dispatch path) — MUST also call validate_message
errors = validate_message(msg)
if errors:
    await self._send_client_message(client_id, create_error_response(...))
    return

await self._router._handle_message(client_id, msg)
```

**Normative requirement**: The router and handlers receive **pre-validated** messages. No handler SHALL contain `if not loop_id:` checks — those are the schema's responsibility.

### 6.5 SDK-Side Validation

The same Pydantic models SHALL be defined in (or imported from) the SDK package so that clients validate before sending. This catches malformed messages on the client side, reducing daemon-side error round-trips:

```python
# packages/soothe-sdk/src/soothe_sdk/client/schemas.py

class LoopInputRequest(BaseModel):
    """Client-side validation for loop_input messages."""

    proto: str = Field(default="1")
    type: Literal["notification"] = "notification"
    method: Literal["loop_input"] = "loop_input"
    params: LoopInputParams
    receipt: str | None = None
```

---

## 7. Error Response Standardization

### 7.1 Unified Error Envelope

The protocol SHALL use JSON-RPC 2.0's structured error object:

```json
{
  "proto": "1",
  "type": "error",
  "error": {
    "code": -32200,
    "message": "Loop not found",
    "data": {"loop_id": "abc123"}
  },
  "id": "req_001"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `code` | Yes | Integer error code (see §7.3 registry) |
| `message` | Yes | Human-readable summary string |
| `data` | No | Machine-parseable details (any JSON value: field errors, context, diagnostic info) |

**Rules**:
1. The `error` object MUST always contain `code` and `message`. It is structurally impossible to send a malformed error when using the `ProtocolError` helper (§7.4).
2. The response MUST echo the request `id` when the original request had one. If the request had no `id` (notification), the error is sent without `id`.
3. **Error terminates the operation**: for subscriptions, an `error` message ends the stream — no further `next` events SHALL be sent for that `id`.

### 7.2 Severity Taxonomy

| Severity | Meaning | Client Behavior | Logging |
|----------|---------|-----------------|---------|
| **Fatal** | Unrecoverable; connection should close or request is impossible | Close connection or surface to user | ERROR + stack trace |
| **Error** | Operation failed; client can retry with corrected params | Surface error to user; allow retry | WARNING |
| **Warn** | Transient or soft failure; client may retry after delay | Show warning; auto-retry with backoff | INFO |

### 7.3 Error Code Registry

The protocol SHALL use JSON-RPC's numeric code scheme with reserved ranges:

#### Protocol-Level Errors (reserved range -32768 to -32000)

| Code | Name | Description | Severity |
|------|------|-------------|----------|
| -32700 | `PARSE_ERROR` | Invalid JSON received | Fatal |
| -32600 | `INVALID_REQUEST` | Message is not a valid request object | Error |
| -32601 | `METHOD_NOT_FOUND` | Unknown method/type combination | Error |
| -32602 | `INVALID_PARAMS` | Invalid method parameters | Error |
| -32603 | `INTERNAL_ERROR` | Internal server error | Fatal |

#### Server State Errors (-32000 to -32099)

| Code | Name | Description | Severity |
|------|------|-------------|----------|
| -32000 | `RATE_LIMITED` | Client is rate-limited | Warn |
| -32001 | `DAEMON_STARTING` | Daemon not yet ready | Warn |
| -32002 | `DAEMON_BUSY` | Daemon at capacity | Warn |
| -32003 | `DAEMON_DEGRADED` | Subsystem unhealthy | Warn |
| -32004 | `DAEMON_ERROR` | Daemon in error state | Fatal |

#### Authorization/Session Errors (-32100 to -32199)

| Code | Name | Description | Severity |
|------|------|-------------|----------|
| -32100 | `NO_LOOP_SUBSCRIPTION` | No active loop subscription for client | Error |
| -32101 | `LOOP_NOT_SUBSCRIBED` | Client not subscribed to this loop | Error |
| -32102 | `NO_SESSION` | No active session | Error |
| -32103 | `AUTH_FAILED` | Authentication failed | Error |
| -32104 | `AUTH_EXPIRED` | Authentication token expired | Error |

#### Resource Not Found (-32200 to -32299)

| Code | Name | Description | Severity |
|------|------|-------------|----------|
| -32200 | `LOOP_NOT_FOUND` | Loop not found | Error |
| -32201 | `JOB_NOT_FOUND` | Job not found | Error |
| -32202 | `GOAL_NOT_FOUND` | Goal not found | Error |
| -32203 | `SKILL_NOT_FOUND` | Skill not found | Error |

#### State Conflicts (-32300 to -32399)

| Code | Name | Description | Severity |
|------|------|-------------|----------|
| -32300 | `JOB_ALREADY_PAUSED` | Job is already paused | Warn |
| -32301 | `JOB_NOT_PAUSED` | Job is not paused | Warn |
| -32302 | `JOB_COMPLETED` | Job already completed | Warn |
| -32303 | `LOOP_ALREADY_ACTIVE` | Loop already has an active subscriber | Warn |

#### Operation Failures (-32400 to -32499)

| Code | Name | Description | Severity |
|------|------|-------------|----------|
| -32400 | `SKILL_LOAD_FAILED` | Skill failed to load | Error |
| -32401 | `RUNNER_UNAVAILABLE` | SootheRunner not available | Fatal |
| -32402 | `AUTOPILOT_NOT_READY` | Autopilot subsystem not ready | Warn |
| -32403 | `CARD_MANAGER_UNAVAILABLE` | Card manager not available | Error |
| -32404 | `CARDS_FETCH_FAILED` | Failed to fetch cards | Error |
| -32405 | `LOOP_CONTEXT_ERROR` | Loop context operation failed | Error |
| -32406 | `LOOP_STATE_ERROR` | Loop state operation failed | Error |
| -32407 | `WORKSPACE_RESOLUTION_FAILED` | Workspace mount translation failed | Error |

#### Job Operation Failures (-32500 to -32599)

| Code | Name | Description | Severity |
|------|------|-------------|----------|
| -32500 | `JOB_CREATE_FAILED` | Job creation failed | Error |
| -32501 | `JOB_PAUSE_FAILED` | Job pause failed | Error |
| -32502 | `JOB_RESUME_FAILED` | Job resume failed | Error |
| -32503 | `JOB_CANCEL_FAILED` | Job cancellation failed | Error |
| -32504 | `LOOP_REATTACH_FAILED` | Loop reattachment failed | Error |

### 7.4 Error Helper Implementation

All error responses SHALL be constructed via the `ProtocolError` helper, making it structurally impossible to produce a malformed error. Handlers raise `ProtocolError` or call the convenience constructors; the transport layer catches and serializes them.

```python
# packages/soothe-daemon/src/soothe_daemon/protocol/error_codes.py

from enum import IntEnum


class ErrorCode(IntEnum):
    """Numeric error codes with reserved ranges.

    -32768 to -32000: Protocol-level (JSON-RPC convention)
    -32000 to -32099: Server state
    -32100 to -32199: Authorization/session
    -32200 to -32299: Resource not found
    -32300 to -32399: State conflicts
    -32400 to -32499: Operation failures
    -32500 to -32599: Job operation failures
    """

    # Protocol-level
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # Server state
    RATE_LIMITED = -32000
    DAEMON_STARTING = -32001
    DAEMON_BUSY = -32002
    DAEMON_DEGRADED = -32003
    DAEMON_ERROR = -32004

    # Authorization/session
    NO_LOOP_SUBSCRIPTION = -32100
    LOOP_NOT_SUBSCRIBED = -32101
    NO_SESSION = -32102
    AUTH_FAILED = -32103
    AUTH_EXPIRED = -32104

    # Resource not found
    LOOP_NOT_FOUND = -32200
    JOB_NOT_FOUND = -32201
    GOAL_NOT_FOUND = -32202
    SKILL_NOT_FOUND = -32203

    # State conflicts
    JOB_ALREADY_PAUSED = -32300
    JOB_NOT_PAUSED = -32301
    JOB_COMPLETED = -32302
    LOOP_ALREADY_ACTIVE = -32303

    # Operation failures
    SKILL_LOAD_FAILED = -32400
    RUNNER_UNAVAILABLE = -32401
    AUTOPILOT_NOT_READY = -32402
    CARD_MANAGER_UNAVAILABLE = -32403
    CARDS_FETCH_FAILED = -32404
    LOOP_CONTEXT_ERROR = -32405
    LOOP_STATE_ERROR = -32406
    WORKSPACE_RESOLUTION_FAILED = -32407

    # Job operation failures
    JOB_CREATE_FAILED = -32500
    JOB_PAUSE_FAILED = -32501
    JOB_RESUME_FAILED = -32502
    JOB_CANCEL_FAILED = -32503
    LOOP_REATTACH_FAILED = -32504
```

```python
# packages/soothe-daemon/src/soothe_daemon/protocol/errors.py

from __future__ import annotations
from typing import Any

from soothe_daemon.protocol.error_codes import ErrorCode


class ProtocolError(Exception):
    """Structured protocol error with numeric code and severity."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        data: dict[str, Any] | None = None,
        severity: str = "error",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}
        self.severity = severity

    def to_envelope(self, *, proto: str = "1", request_id: str | None = None) -> dict[str, Any]:
        """Build a wire-ready error message envelope."""
        msg: dict[str, Any] = {
            "proto": proto,
            "type": "error",
            "error": {
                "code": self.code.value,
                "message": self.message,
            },
        }
        if self.data:
            msg["error"]["data"] = self.data
        if request_id is not None:
            msg["id"] = request_id
        return msg


# Convenience constructors
def loop_not_found(loop_id: str) -> ProtocolError:
    return ProtocolError(
        ErrorCode.LOOP_NOT_FOUND,
        f"Loop {loop_id} not found",
        data={"loop_id": loop_id},
    )

def invalid_params(field: str, reason: str) -> ProtocolError:
    return ProtocolError(
        ErrorCode.INVALID_PARAMS,
        f"Invalid parameter: {field}",
        data={"field": field, "reason": reason},
    )
```

---

## 8. Versioning and Capability Negotiation

### 8.1 Protocol Version Field

Every message SHALL carry a `"proto"` field:

```json
{"proto": "1", "type": "request", "method": "loop_get", ...}
```

- `"1"` is the protocol version. The value is a string, not a float, to allow future versions like `"1.1"` or `"2"` without ambiguity.
- The `proto` field is **mandatory**. Messages without it SHALL be rejected at validation with code `-32600` (`INVALID_REQUEST`).
- Future protocol versions (`"2"`, etc.) SHALL be negotiated via the connection handshake (§8.2).

### 8.2 Connection Handshake

The connection SHALL begin with a bidirectional `connection_init`/`connection_ack` exchange:

```
Client                                         Server
  |                                              |
  |--- connection_init ------------------------->|
  |    {client_version, capabilities,            |
  |     accept_proto: ["1"]}                     |
  |                                              |
  |<----------------------- connection_ack ------|
  |    {server_version, protocol_version: "1",   |
  |     capabilities, readiness_state}           |
  |                                              |
  |--- request/subscribe/notification ---------->|
  |<----------------------- response/next -------|
  |                                              |
  |--- ping ------------------------------------>|  (either direction)
  |<----------------------- pong ----------------|
  |                                              |
  |--- disconnect ------------------------------>|  (clean disconnect)
```

**`connection_init` (client → server)**:
```json
{
  "proto": "1",
  "type": "connection_init",
  "params": {
    "client_version": "0.5.0",
    "client_name": "soothe-cli",
    "accept_proto": ["1"],
    "capabilities": ["streaming", "batch", "receipts"]
  }
}
```

**`connection_ack` (server → client)**:
```json
{
  "proto": "1",
  "type": "connection_ack",
  "result": {
    "server_version": "0.5.0",
    "protocol_version": "1",
    "capabilities": ["streaming", "batch", "receipts", "heartbeat"],
    "readiness_state": "ready",
    "heartbeat_interval_ms": 30000
  }
}
```

**Negotiation rules**:
1. `connection_init` SHALL be the **first message** the client sends after the WebSocket upgrade. No other messages SHALL be accepted until `connection_ack` is received.
2. The client SHALL declare `accept_proto: ["1"]` — the protocol versions it supports.
3. The server SHALL pick the highest version both parties support and echo it in `protocol_version`.
4. If no compatible version is available, the server SHALL send `connection_ack` with `readiness_state: "incompatible"` and close the connection with WebSocket close code 1001 (Going Away).
5. If the daemon is not ready (`starting`/`warming`), `readiness_state` SHALL reflect the current state; the client SHOULD bounded-retry `connection_init`.
6. Capabilities SHALL be **intersected**: only capabilities declared by *both* parties are active. If the client does not declare `batch`, the server SHALL NOT accept batch arrays even if it supports them.
7. Messages sent before `connection_init` SHALL be rejected with `-32600` (`INVALID_REQUEST`) and a message indicating the handshake must complete first.

### 8.3 Heartbeat

The protocol SHALL adopt bidirectional `ping`/`pong` heartbeat:

```json
// Either direction
{"proto": "1", "type": "ping"}

// Response (within heartbeat_timeout_ms)
{"proto": "1", "type": "pong"}
```

- The `connection_ack` SHALL declare `heartbeat_interval_ms` (default: 30000).
- Either party MAY send `ping`; the receiver MUST respond with `pong` within `heartbeat_timeout_ms` (default: 10000).
- If no `pong` arrives within timeout, the connection SHALL be considered dead and closed with WebSocket close code 1001 (Going Away).
- This enables dead-connection detection from both client and server sides.

### 8.4 Deprecation Strategy

The protocol SHALL use a two-tier deprecation model (aligned with RFC-900):

| Tier | Meaning | Wire Signal | Duration |
|------|---------|-------------|----------|
| **Active** | Method is current and fully supported | None | Indefinite |
| **Removed** | Method no longer exists; returns -32601 | Method not in registry → `-32601` (`METHOD_NOT_FOUND`) | After removal |

**Deprecation approach**: The protocol does not support wire-level deprecation signaling. When a method is deprecated and removed from the daemon, clients calling that method receive a standard `-32601` (`METHOD_NOT_FOUND`) error response. This simplifies the protocol and avoids complexity of signaling deprecated-but-still-functional methods.

**Migration guidance**: When methods are removed, migration documentation SHALL be provided in release notes and the project wiki. Clients should update to use replacement methods before the removal release.

---

## 9. Message Type Taxonomy

### 9.1 Message Classes (`type` field values)

| `type` | Direction | Purpose |
|--------|-----------|---------|
| `connection_init` | C→S | Connection handshake (client caps + version) |
| `connection_ack` | S→C | Connection handshake (server caps + version) |
| `request` | C→S | RPC request (expects response) |
| `response` | S→C | RPC success response |
| `notification` | C→S | Fire-and-forget (no response) |
| `subscribe` | C→S | Start a subscription |
| `next` | S→C | Stream event for a subscription |
| `error` | S→C | Error response (terminates operation) |
| `complete` | S→C | Stream complete (no more events) |
| `unsubscribe` | C→S | Cancel a subscription |
| `ping` | Bidirectional | Heartbeat |
| `pong` | Bidirectional | Heartbeat response |
| `receipt_response` | S→C | Delivery confirmation for notification |
| `disconnect` | C→S | Clean connection close |

The `method` field (within request/notification/subscribe) carries the operation name. The full method catalog is defined in the schema registry (§6.2).

### 9.2 Method Catalog

#### Loop RPC Methods

| Method | `type` | Description |
|--------|--------|-------------|
| `loop_list` | `request` | List loops with optional filter |
| `loop_get` | `request` | Get loop details |
| `loop_tree` | `request` | Get checkpoint tree visualization |
| `loop_prune` | `request` | Prune old branches |
| `loop_delete` | `request` | Delete a loop (idempotent) |
| `loop_new` | `request` | Create a new loop |
| `loop_reattach` | `request` | Reconstruct event history and replay |
| `loop_input` | `notification` or `request` | Submit user input (notification = fire-and-forget; request = with delivery confirmation) |
| `loop_messages` | `request` | Fetch persisted conversation/activity rows |
| `loop_state_get` | `request` | Get checkpoint channel values |
| `loop_state_update` | `request` | Apply partial checkpoint values |
| `loop_execution_state_fetch` | `request` | Get focused execution-progress snapshot (plan, step_index, iteration, status) |
| `loop_cards_fetch` | `request` | Fetch display card ledger snapshot (deprecated — use `loop_history_fetch`) |
| `loop_history_fetch` | `request` | Fetch goal display snapshots + live card tail (RFC-631) |

#### Subscription Methods

| Method | `type` | Description |
|--------|--------|-------------|
| `loop_events` | `subscribe` | Subscribe to loop event stream |
| `autopilot_events` | `subscribe` | Subscribe to autopilot worker events |

Subscription lifecycle: `subscribe` (start) → `next` (stream events) → `complete` (explicit termination) or `unsubscribe` (client cancel) or `error` (stream error, terminates).

#### Job RPC Methods

| Method | `type` | Description |
|--------|--------|-------------|
| `job_create` | `request` | Submit root goal |
| `job_status` | `request` | Query job state |
| `job_pause` | `request` | Pause job |
| `job_resume` | `request` | Resume paused job |
| `job_cancel` | `request` | Cancel job |
| `job_dag` | `request` | Get DAG snapshot |
| `job_guidance` | `request` | Send guidance to job/goal |

#### Daemon & Config Methods

| Method | `type` | Description |
|--------|--------|-------------|
| `daemon_status` | `request` | Get daemon status (running, readiness, version) |
| `daemon_shutdown` | `request` | Request daemon shutdown |
| `config_get` | `request` | Get config section |

#### Skills & Models Methods

| Method | `type` | Description |
|--------|--------|-------------|
| `skills_list` | `request` | List skills metadata |
| `invoke_skill` | `request` | Invoke a skill |
| `models_list` | `request` | List models from daemon config |
| `mcp_status` | `request` | Get MCP server status |

#### Auth Methods

| Method | `type` | Description |
|--------|--------|-------------|
| `auth` | `request` | AKSK authentication |
| `auth_refresh` | `request` | Token refresh |

#### Command Methods

| Method | `type` | Description |
|--------|--------|-------------|
| `slash_command` | `notification` | Slash command (e.g., `/exit`, `/cancel`, `/plan`) |
| `rpc_command` | `request` | Structured RPC command (e.g., `autopilot_status`) |

#### Connection Methods

| Method | `type` | Description |
|--------|--------|-------------|
| `disconnect` | `notification` | Client clean disconnect (loops keep running) |

### 9.3 Skill RPC Ordering

For `invoke_skill`, the daemon MUST send a single `response` (matching `id` when present) **before** any `next` stream events for that turn. Clients may block on `request_response` until the response arrives; stream chunks must not precede it on the same connection.

### 9.4 Design Decisions

#### `command` → `slash_command` + `rpc_command`

The previous protocol had two structurally different messages sharing `type: "command"`:
- **Slash commands** (TUI): `{"type": "command", "cmd": "/exit"}` — enqueues raw slash command to loop dispatcher.
- **RPC commands** (headless CLI): `{"type": "command", "command": "autopilot_status", "request_id": "cmd_1", "payload": {}}` — structured RPC with correlation.

In protocol-1, these are structurally separated:
- `slash_command` (notification, no `id`): `{"method": "slash_command", "params": {"cmd": "/exit"}}`
- `rpc_command` (request, with `id`): `{"method": "rpc_command", "params": {"command": "autopilot_status", "payload": {}}}`

The `type` field distinguishes notification vs request, and `method` distinguishes the operation. The collision is structurally eliminated.

#### `loop_subscribe` → `subscribe` + `method: "loop_events"`

The previous `loop_subscribe` produced a double response (`subscription_confirmed` + `loop_subscribe_response`). In protocol-1, the subscription lifecycle is:

1. Client sends `{"type": "subscribe", "method": "loop_events", "params": {"loop_id": ...}, "id": "s1"}`
2. Server delivers stream events as `{"type": "next", "id": "s1", "payload": {...}}`
3. Stream ends with `{"type": "complete", "id": "s1"}` (explicit termination)
4. Client can cancel early with `{"type": "unsubscribe", "id": "s1"}`
5. Errors during stream: `{"type": "error", "error": {...}, "id": "s1"}`

No double response. The `subscribe` message itself implies subscription confirmation; if the server cannot subscribe (e.g., loop not found), it sends an `error` with the subscription's `id`.

#### `detach` → `disconnect`; `loop_detach` → `unsubscribe`

- `disconnect` (connection-level notification): signals the client is leaving. The daemon keeps loops running.
- `unsubscribe` (operation-level): cancels a specific subscription by `id`.

This cleanly separates connection-level from operation-level concerns.

#### `daemon_ready` → `connection_init` / `connection_ack`

The one-directional `daemon_ready` is replaced by the bidirectional `connection_init`/`connection_ack` handshake (§8.2). The `connection_ack` includes `readiness_state`, subsuming `daemon_ready`'s function. `daemon_status` remains as an RPC method for detailed status queries.

#### `loop_input` / `input` Internal Type Confusion

The wire method is `loop_input`. The internal queue payload uses a distinct key (`"_kind": "user_input"`) to avoid confusion with the wire `type` field. This is an internal implementation detail with no wire impact.

---

## 10. Naming Conventions

### 10.1 Canonical Names

| Concept | Canonical | Context |
|---------|-----------|---------|
| Loop identifier | `loop_id` | Wire-level (all messages) |
| User input text | `content` | `params.content` in `loop_input`, `job_guidance` |
| Slash command string | `cmd` | `params.cmd` in `slash_command` |
| RPC command name | `command` | `params.command` in `rpc_command` |
| Workspace path | `workspace` | `params.workspace` in `loop_new`, `job_create` |
| User identifier | `user_id` | `params.user_id` in `loop_new` |
| Correlation ID | `id` | Top-level envelope field |
| Response type | `type: "response"` | Envelope `type` field |

### 10.2 Design Rationale

**`loop_id` (not `thread_id`)**: The codebase has already converged on `loop_id` for all client-facing messages. `QueryEngine._loop_scoped_client_message()` explicitly strips `thread_id` and injects `loop_id`. `thread_id` is internal only (LangGraph checkpoint keys).

**`content` (not `text`)**: `loop_input` uses `content` as the primary field. All user input text across all methods uses `content` uniformly. The `text`/`prompt`/`message`/`input` fallback keys from the old `_coerce_loop_input_text()` are removed; `content` is the sole field name.

**`cmd` vs `command`**: In the new envelope, `type` distinguishes notification vs request, and `method` distinguishes the operation. The `cmd` and `command` field names live in different `params` schemas (`slash_command` vs `rpc_command`), so there is no collision. The field names are kept as-is because they are semantically appropriate within their respective contexts.

**`workspace` (not `client_workspace`)**: `loop_new` and `job_create` both use `workspace` as the field name. The `client_workspace` alias is removed.

**`user_id` (not `user`)**: `loop_new` uses `user_id`. The `user` alias is removed.

**`id` (not `request_id`)**: The envelope's top-level `id` field replaces the old `request_id`. All request/response correlation uses `id`.

**No `_response` suffix**: Responses use `type: "response"` with the same `method` as the request. The `id` field correlates request to response. The `{type}_response` pattern (e.g., `loop_get_response`, `loop_cards_fetch_response`) is eliminated.

---

## 11. Documentation Strategy

### 11.1 AsyncAPI Specification as Single Source of Truth

The protocol SHALL adopt **AsyncAPI 3.0** as the machine-readable specification format. The AsyncAPI document is the single source of truth for:
1. Message types, schemas, and correlation IDs
2. Human-readable documentation (generated from the spec)
3. Pydantic model generation (from JSON Schema components)
4. Client SDK binding generation (from the spec)

Hand-written RFCs are retained for architecture and design rationale but are no longer the authoritative source for message type tables. This RFC points to the AsyncAPI spec for the wire contract.

### 11.2 AsyncAPI Document Structure

```yaml
asyncapi: 3.0.0
info:
  title: Soothe Daemon WebSocket API
  version: 1.0.0
  description: |
    Bidirectional WebSocket protocol for daemon communication.
    Hybrid RPC + streaming subscription model.

    Protocol version 1 — see RFC-450 for design rationale.
servers:
  daemon:
    host: 127.0.0.1:8765
    pathname: /
    protocol: ws
    protocolVersion: '1'
    description: Local daemon WebSocket endpoint
channels:
  main:
    address: /
    title: Main bidirectional channel
    bindings:
      ws:
        method: GET
    operations:
      send:
        action: send
        title: Server-to-client messages
        channel:
          $ref: '#/channels/main'
        messages:
          - $ref: '#/components/messages/connectionAck'
          - $ref: '#/components/messages/response'
          - $ref: '#/components/messages/next'
          - $ref: '#/components/messages/error'
          - $ref: '#/components/messages/complete'
          - $ref: '#/components/messages/receiptResponse'
          - $ref: '#/components/messages/pong'
      receive:
        action: receive
        title: Client-to-server messages
        channel:
          $ref: '#/channels/main'
        messages:
          - $ref: '#/components/messages/connectionInit'
          - $ref: '#/components/messages/request'
          - $ref: '#/components/messages/notification'
          - $ref: '#/components/messages/subscribe'
          - $ref: '#/components/messages/unsubscribe'
          - $ref: '#/components/messages/ping'
          - $ref: '#/components/messages/disconnect'
components:
  correlationIds:
    operationId:
      location: $message.payload#/id
      description: Operation correlation ID
  messages:
    connectionInit:
      title: Connection initialization
      payload:
        $ref: '#/components/schemas/connectionInitEnvelope'
    connectionAck:
      title: Connection acknowledgment
      payload:
        $ref: '#/components/schemas/connectionAckEnvelope'
    request:
      title: RPC request
      correlationId:
        $ref: '#/components/correlationIds/operationId'
      payload:
        oneOf:
          - $ref: '#/components/schemas/loopGetRequest'
          - $ref: '#/components/schemas/loopListRequest'
          - $ref: '#/components/schemas/loopNewRequest'
          - $ref: '#/components/schemas/loopInputRequest'
          - $ref: '#/components/schemas/jobCreateRequest'
          - $ref: '#/components/schemas/jobStatusRequest'
          # ... one entry per method
    notification:
      title: Fire-and-forget notification
      payload:
        oneOf:
          - $ref: '#/components/schemas/loopInputNotification'
          - $ref: '#/components/schemas/slashCommandNotification'
          - $ref: '#/components/schemas/disconnectNotification'
    subscribe:
      title: Subscription start
      correlationId:
        $ref: '#/components/correlationIds/operationId'
      payload:
        oneOf:
          - $ref: '#/components/schemas/loopEventsSubscribe'
          - $ref: '#/components/schemas/autopilotEventsSubscribe'
    next:
      title: Stream event
      correlationId:
        $ref: '#/components/correlationIds/operationId'
      payload:
        $ref: '#/components/schemas/streamEvent'
  schemas:
    # ── Envelope schemas ──────────────────────────
    baseEnvelope:
      type: object
      required: [proto, type]
      properties:
        proto: {type: string, const: "1"}
        type: {type: string}
    connectionInitEnvelope:
      allOf:
        - $ref: '#/components/schemas/baseEnvelope'
        - properties:
            type: {const: "connection_init"}
            params: {$ref: '#/components/schemas/connectionInitParams'}
    connectionAckEnvelope:
      allOf:
        - $ref: '#/components/schemas/baseEnvelope'
        - properties:
            type: {const: "connection_ack"}
            result: {$ref: '#/components/schemas/connectionAckResult'}
    # ── Method-specific request schemas ───────────
    loopGetRequest:
      allOf:
        - $ref: '#/components/schemas/baseEnvelope'
        - properties:
            type: {const: "request"}
            method: {const: "loop_get"}
            params: {$ref: '#/components/schemas/loopGetParams'}
            id: {type: string}
    loopGetParams:
      type: object
      required: [loop_id]
      properties:
        loop_id: {type: string, minLength: 1}
        verbose: {type: boolean, default: false}
        tree: {type: boolean, default: false}
    # ... (one schema per method; see full spec at docs/specs/asyncapi.yaml)
```

### 11.3 Tooling Pipeline

```
┌────────────────────────────────────────────────────────────────┐
│                    docs/specs/asyncapi.yaml                     │
│              (AsyncAPI 3.0 — single source of truth)            │
└───────────┬────────────────────────┬───────────────────────────┘
            │                        │
            ▼                        ▼
┌───────────────────────┐     ┌──────────────────────────────────┐
│  asyncapi CLI          │     │  datamodel-code-generator         │
│  (docs generation)     │     │  (JSON Schema → Pydantic)         │
└───────────┬───────────┘     └──────────────┬───────────────────┘
            │                                │
            ▼                                ▼
┌───────────────────────┐     ┌──────────────────────────────────┐
│  HTML documentation   │     │  packages/soothe-daemon/.../      │
│  (human-readable,     │     │  protocol/schemas_gen.py          │
│   published to docs)  │     │  (auto-generated Pydantic models) │
└───────────────────────┘     └──────────────────────────────────┘
```

**Tools**:
- **`asyncapi` CLI**: Validates the spec, generates HTML documentation.
- **`datamodel-code-generator`**: Converts JSON Schema components to Pydantic models. The generated models are checked into the repo (not generated at runtime) and used by the validation layer. A CI check regenerates and diffs against the committed version to detect drift.
- **Client bindings**: `asyncapi generate` can produce Python/TypeScript client stubs. The SDK's hand-written `WebSocketClient` is the primary client; generated stubs are optional.

### 11.4 What NOT to Adopt

| Standard | Feature Excluded | Rationale |
|----------|-----------------|-----------|
| STOMP | Frame-based wire format (command+headers+body) | JSON is already used; STOMP's text frame format adds parsing complexity without benefit |
| STOMP | ACK/NACK delivery guarantees | Soothe's events are ephemeral stream chunks, not durable messages requiring redelivery |
| STOMP | Destination-based routing | Soothe already has `loop_id`-based routing; STOMP destinations add unnecessary indirection |
| graphql-ws | GraphQL query language | Soothe does not use GraphQL; the protocol structure is borrowed, not the query language |
| graphql-ws | Socket closure on invalid messages | Too aggressive — a single bad message should not kill the entire connection (which may have active streams). Send an error response instead. |
| JSON-RPC | Positional params (array) | Object params are always used in Soothe; positional params add ambiguity |
| JSON-RPC | `jsonrpc: "2.0"` literal | The envelope uses `proto: "1"` — it is a hybrid, not pure JSON-RPC. Using `"2.0"` would imply full JSON-RPC compliance. |
| AsyncAPI | Full broker messaging semantics | Soothe is a direct WebSocket connection, not a pub/sub broker |

---

## 12. Transport Specification

### WebSocket

- **Wire**: WebSocket text frames (RFC 6455)
- **URL**: `ws://127.0.0.1:8765` (configurable)
- **Flow**: WebSocket upgrade → `connection_init`/`connection_ack` handshake → JSON exchange → `disconnect` → Close frame
- **Status**: ✅ Implemented (`packages/soothe-daemon/src/soothe_daemon/transports/websocket.py`)

### HTTP REST

- **Wire**: HTTP/1.1 with JSON bodies
- **URL**: `http://localhost:8766/api/v1`
- **Use**: Health checks, CRUD, thread listing, config, historical data
- **Status**: ✅ Implemented (`packages/soothe-daemon/src/soothe_daemon/transports/http_rest.py`)

**Integration**: WebSocket for streaming, HTTP REST for CRUD.

---

## 13. Security Requirements

### Transport Security

- **Local**: Bind `127.0.0.1` (no external access), CORS validation
- **Production**: Reverse proxy for TLS, auth (API keys/JWT/OAuth), rate limiting, IP whitelist, logging
- **Desktop**: Local WebSocket only, optional separate auth

### CORS

Pattern matching (`http://localhost:*`, `http://127.0.0.1:*`), validate `Origin` header.

### Input Validation

Message size limit: 10MB. Schema validation on required fields (Pydantic models at transport boundary, §6).

---

## 14. Decision Summary

| Dimension | Decision | Source Standard |
|-----------|----------|-----------------|
| **Envelope** | `{proto, type, method, params, id}` hybrid | JSON-RPC (method/params/id) + graphql-ws (type) |
| **Schema validation** | Pydantic models per message type, validated at transport boundary | AsyncAPI (JSON Schema) + Pydantic |
| **Error model** | `{code, message, data}` with numeric codes, reserved ranges, severity taxonomy | JSON-RPC 2.0 |
| **Versioning** | Per-message `proto` field (mandatory) + `connection_init`/`connection_ack` handshake | JSON-RPC (per-message) + graphql-ws/STOMP (handshake) |
| **Capability negotiation** | Bidirectional `connection_init`/`connection_ack` with capability intersection | graphql-ws + STOMP |
| **Deprecation** | Three-tier (active/deprecated/removed) with wire signaling | RFC-900 + custom |
| **Message taxonomy** | `command`→`slash_command`, `command_request`→`rpc_command`, `detach`→`disconnect`, `loop_subscribe`→`subscribe`+`loop_events` | — |
| **Naming** | `loop_id` (not `thread_id`), `content` (not `text`), `workspace` (not `client_workspace`), `id` (not `request_id`) | — |
| **Documentation** | AsyncAPI 3.0 spec as single source of truth; RFCs for rationale | AsyncAPI |
| **Heartbeat** | Bidirectional `ping`/`pong` | graphql-ws |
| **Stream termination** | Explicit `complete` message | graphql-ws |
| **Receipt** | Optional `receipt` field for delivery confirmation | STOMP |
| **Batch** | JSON array of requests | JSON-RPC |
| **Compatibility** | Clean break — no legacy format support | — |

---

## 15. Future Considerations

1. **AsyncAPI spec location**: The AsyncAPI YAML is a machine-readable artifact, not a prose RFC. It SHALL reside at `docs/specs/asyncapi.yaml` and be referenced from the RFC index.

2. **Generated Pydantic model management**: Generated models SHALL be checked into the repo (not generated at runtime) for IDE support and debugging. A CI check SHALL regenerate and diff against the committed version to detect drift.

3. **Receipt scope**: The `receipt` mechanism is available for all notifications, but is primarily useful for `loop_input` (the primary fire-and-forget message where delivery confirmation matters). Other notifications (`slash_command`, `disconnect`) are less critical.

4. **Protocol version mismatch handling**: Since this is a clean-break design, `proto` mismatch SHALL close the connection. The server sends `connection_ack` with `readiness_state: "incompatible"` and closes gracefully with WebSocket close code 1001.

---

## Appendix A: Message Type Mapping (Previous Wire Format → Protocol-1)

This appendix provides an informative mapping from the previous wire format to the protocol-1 wire format. It is not normative — the AsyncAPI spec is the authoritative source for message schemas.

| Old `type` | Old Direction | New `type` | New `method` | Notes |
|------------|---------------|------------|-------------|-------|
| `daemon_ready` | C→S | `connection_init` | — | Subsumed by handshake |
| (none) | S→C | `connection_ack` | — | New handshake response |
| `daemon_status` | C→S | `request` | `daemon_status` | |
| `daemon_shutdown` | C→S | `request` | `daemon_shutdown` | |
| `config_get` | C→S | `request` | `config_get` | |
| `auth` | C→S | `request` | `auth` | |
| `auth_refresh` | C→S | `request` | `auth_refresh` | |
| `loop_list` | C→S | `request` | `loop_list` | |
| `loop_get` | C→S | `request` | `loop_get` | |
| `loop_tree` | C→S | `request` | `loop_tree` | |
| `loop_prune` | C→S | `request` | `loop_prune` | |
| `loop_delete` | C→S | `request` | `loop_delete` | |
| `loop_new` | C→S | `request` | `loop_new` | |
| `loop_reattach` | C→S | `request` | `loop_reattach` | |
| `loop_subscribe` | C→S | `subscribe` | `loop_events` | Lifecycle change |
| `loop_detach` | C→S | `unsubscribe` | — | Uses `id` from subscribe |
| `loop_input` | C→S | `notification` or `request` | `loop_input` | Notification if no `id` |
| `loop_messages` | C→S | `request` | `loop_messages` | |
| `loop_state_get` | C→S | `request` | `loop_state_get` | |
| `loop_state_update` | C→S | `request` | `loop_state_update` | |
| `loop_execution_state_fetch` | C→S | `request` | `loop_execution_state_fetch` | Returns plan, step_index, iteration, status |
| `loop_cards_fetch` | C→S | `request` | `loop_cards_fetch` | |
| `job_create` | C→S | `request` | `job_create` | |
| `job_status` | C→S | `request` | `job_status` | |
| `job_pause` | C→S | `request` | `job_pause` | |
| `job_resume` | C→S | `request` | `job_resume` | |
| `job_cancel` | C→S | `request` | `job_cancel` | |
| `job_dag` | C→S | `request` | `job_dag` | |
| `job_guidance` | C→S | `request` | `job_guidance` | |
| `autopilot_subscribe` | C→S | `subscribe` | `autopilot_events` | Lifecycle change |
| `autopilot_unsubscribe` | C→S | `unsubscribe` | — | Uses `id` from subscribe |
| `skills_list` | C→S | `request` | `skills_list` | |
| `models_list` | C→S | `request` | `models_list` | |
| `invoke_skill` | C→S | `request` | `invoke_skill` | |
| `mcp_status` | C→S | `request` | `mcp_status` | |
| `command` (slash) | C→S | `notification` | `slash_command` | Renamed |
| `command_request` (RPC) | C→S | `request` | `rpc_command` | Renamed |
| `detach` | C→S | `notification` | `disconnect` | Renamed |
| `*_response` | S→C | `response` | (same as request) | `id` correlation |
| `event` | S→C | `next` | — | `id` from subscribe |
| `subscription_confirmed` | S→C | (eliminated) | — | Subsumed by `subscribe` lifecycle |
| `status` | S→C | `next` or `response` | — | Context-dependent |
| `error` | S→C | `error` | — | Unified structure |
| `command_response` | S→C | `response` | — | Unified with standard response |

---

## Appendix B: Error Code Mapping (String → Numeric)

This appendix provides an informative mapping from the previous string error codes to the protocol-1 numeric error codes. It is not normative — the `ErrorCode` IntEnum (§7.4) is the authoritative source.

| Old String Code | New Numeric Code | Name | Range |
|-----------------|-----------------|------|-------|
| `INVALID_MESSAGE` | -32600 | `INVALID_REQUEST` | Protocol |
| `INVALID_REQUEST` | -32602 | `INVALID_PARAMS` | Protocol |
| `UNKNOWN_MESSAGE_TYPE` | -32601 | `METHOD_NOT_FOUND` | Protocol |
| `INTERNAL_ERROR` | -32603 | `INTERNAL_ERROR` | Protocol |
| `RATE_LIMITED` | -32000 | `RATE_LIMITED` | Server state |
| `DAEMON_STARTING` | -32001 | `DAEMON_STARTING` | Server state |
| `DAEMON_BUSY` | -32002 | `DAEMON_BUSY` | Server state |
| `DAEMON_DEGRADED` | -32003 | `DAEMON_DEGRADED` | Server state |
| `DAEMON_ERROR` | -32004 | `DAEMON_ERROR` | Server state |
| `NO_LOOP_SUBSCRIPTION` | -32100 | `NO_LOOP_SUBSCRIPTION` | Auth/session |
| `LOOP_NOT_SUBSCRIBED` | -32101 | `LOOP_NOT_SUBSCRIBED` | Auth/session |
| `NO_SESSION` | -32102 | `NO_SESSION` | Auth/session |
| `LOOP_NOT_FOUND` | -32200 | `LOOP_NOT_FOUND` | Not found |
| `JOB_NOT_FOUND` | -32201 | `JOB_NOT_FOUND` | Not found |
| `GOAL_NOT_FOUND` | -32202 | `GOAL_NOT_FOUND` | Not found |
| `SKILL_NOT_FOUND` | -32203 | `SKILL_NOT_FOUND` | Not found |
| `JOB_ALREADY_PAUSED` | -32300 | `JOB_ALREADY_PAUSED` | State conflict |
| `JOB_NOT_PAUSED` | -32301 | `JOB_NOT_PAUSED` | State conflict |
| `JOB_COMPLETED` | -32302 | `JOB_COMPLETED` | State conflict |
| `SKILL_LOAD_FAILED` | -32400 | `SKILL_LOAD_FAILED` | Operation failure |
| `RUNNER_UNAVAILABLE` | -32401 | `RUNNER_UNAVAILABLE` | Operation failure |
| `AUTOPILOT_NOT_READY` | -32402 | `AUTOPILOT_NOT_READY` | Operation failure |
| `CARD_MANAGER_UNAVAILABLE` | -32403 | `CARD_MANAGER_UNAVAILABLE` | Operation failure |
| `CARDS_FETCH_FAILED` | -32404 | `CARDS_FETCH_FAILED` | Operation failure |
| `LOOP_CONTEXT` | -32405 | `LOOP_CONTEXT_ERROR` | Operation failure |
| `LOOP_STATE` | -32406 | `LOOP_STATE_ERROR` | Operation failure |
| (malformed at router.py:1414) | -32407 | `WORKSPACE_RESOLUTION_FAILED` | Operation failure |
| `JOB_CREATE_FAILED` | -32500 | `JOB_CREATE_FAILED` | Job failure |
| `JOB_PAUSE_FAILED` | -32501 | `JOB_PAUSE_FAILED` | Job failure |
| `JOB_RESUME_FAILED` | -32502 | `JOB_RESUME_FAILED` | Job failure |
| `JOB_CANCEL_FAILED` | -32503 | `JOB_CANCEL_FAILED` | Job failure |
| `LOOP_REATTACH_FAILED` | -32504 | `LOOP_REATTACH_FAILED` | Job failure |

---

## 14. Stream Degradation Signaling (IG-534)

When the client or daemon cannot keep pace with the event stream, implementations MUST surface degradation to the user rather than silently dropping user-visible content.

### Custom event: `stream_degraded`

Delivered as a standard streaming frame (`type: event`, `mode: custom`):

```json
{
  "type": "event",
  "loop_id": "019f1b8a-8385-70f1-9248-c40213b8b036",
  "mode": "custom",
  "data": {
    "type": "stream_degraded",
    "reason": "inbound_queue_overflow",
    "dropped_count": 42,
    "recoverable": true
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `reason` | string | Machine-readable cause (`inbound_queue_overflow`, `event_bus_overflow`, …) |
| `dropped_count` | int | Cumulative frames lost or evicted since stream start |
| `recoverable` | bool | Whether `/resume` or ledger fetch may restore content |

**Client behavior**: Display a non-blocking banner; do not abort the turn unless paired with `error` or connection loss.

**Daemon behavior**: Emit when daemon-side client queue drops user-visible frames after blocking timeout (optional; client-local detection is sufficient for inbound overflow).

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| v1.1 | 2026-07-01 | IG-534: `stream_degraded` custom event schema |
| v1.0 | 2026-06-28 | Protocol-1 envelope (`proto: 1`, `next`/`complete`, JSON-RPC hybrid) |

---

## References

- `docs/analysis/ws-api-standards-comparison.md` — Standards research (AsyncAPI, JSON-RPC, graphql-ws, STOMP)
- `docs/analysis/ws-request-submit-api-design-review.md` — Current-state API review
- `docs/specs/RFC-614-unified-streaming-messaging.md` — Streaming messaging framework
- `docs/specs/RFC-403-unified-event-naming.md` — Event naming conventions
- `docs/specs/RFC-900-deprecation-reclassification-scheme.md` — Deprecation framework
- `docs/specs/RFC-620-channel-architecture.md` — Channel architecture (transport layer)
