# WebSocket API Standards Comparison & Recommendations for Soothe Daemon

**Date**: 2026-06-28  
**Scope**: Research established industry standards for WebSocket-based API specification design and map their principles against Soothe's current daemon WebSocket API  
**Context**: Builds on the prior API review (`docs/analysis/ws-request-submit-api-design-review.md`) which identified 37 message types, ad-hoc `dict.get` validation, 20+ undocumented error codes, no versioning, and no schema models

---

## Executive Summary

Soothe's daemon WebSocket API is a **bidirectional streaming + RPC hybrid** — it serves both long-lived event subscriptions (agent output streams) and request/response RPCs (loop management, job control, skill invocation). No single industry standard covers both modes perfectly, but each standard contributes critical design principles that address specific deficiencies in Soothe's current protocol.

**Recommended approach**: A **JSON-RPC 2.0 envelope + graphql-ws subscription lifecycle + AsyncAPI specification** hybrid. Specifically:

| Layer | Borrow From | What It Solves |
|-------|-------------|----------------|
| Message envelope | JSON-RPC 2.0 | Unified `{jsonrpc, method, params, id}` structure; eliminates `type`/`cmd`/`command` collision; `id` field is the canonical correlation ID |
| Error model | JSON-RPC 2.0 | Structured `{code, message, data}` error object with numeric codes; reserved ranges for protocol vs application errors |
| Notification vs request | JSON-RPC 2.0 | `id` absent = notification (fire-and-forget); `id` present = request (response expected). Eliminates Soothe's `send_*` vs `request_response` duality |
| Subscription lifecycle | graphql-ws | `connection_init`/`connection_ack` handshake with capability negotiation; `subscribe`/`next`/`error`/`complete` operation lifecycle with per-operation IDs |
| Capability negotiation | graphql-ws + STOMP | `connection_init` payload declares client capabilities; `CONNECTED` response declares server capabilities + protocol version |
| Versioning | STOMP + JSON-RPC | `accept-version` header (STOMP) + `jsonrpc: "2.0"` version field (JSON-RPC) |
| Receipt/acknowledgment | STOMP | `receipt` mechanism for fire-and-forget messages that need delivery confirmation |
| Schema & documentation | AsyncAPI 3.0 | Channel/operation/message model for formal spec; `correlationId` for request tracking; `oneOf` message schemas per channel; auto-generated docs |
| Schema validation | AsyncAPI + JSON-RPC | Pydantic models generated from AsyncAPI message schemas; validated before dispatch |

---

## 1. AsyncAPI Specification (v3.0.0)

### 1.1 Overview

AsyncAPI is the leading open standard for event-driven and message-based APIs, analogous to what OpenAPI is for REST. It is transport-agnostic but includes protocol-specific bindings for WebSocket, Kafka, AMQP, HTTP, and more. The core model separates **channels** (logical destinations), **operations** (publish/subscribe actions), and **messages** (typed payloads with schemas).

### 1.2 Key Architectural Concepts

| Concept | Description |
|---------|-------------|
| **Channel** | A logical address/path through which messages flow. In WebSocket, typically maps to a connection or sub-path. Example: `loops/{loop_id}/events` |
| **Operation** | An action on a channel: `send` (server→client) or `receive` (client→server, from server's perspective). Each operation has an `operationId`. |
| **Message** | A typed payload with a `messageId`, `headers`, and `payload` (JSON Schema). A channel can accept `oneOf` multiple message types. |
| **Bindings** | Protocol-specific metadata attached to servers, channels, operations, and messages. The `ws` binding adds WebSocket-specific config (method, query, headers, heartbeat). |
| **Correlation ID** | A `correlationId` object on a message that defines where to find the correlation key (e.g., `$message.header#request_id`). This is a first-class concept, not an afterthought. |
| **Server** | Connection endpoint with `host`, `pathname`, `protocol` (`ws`/`wss`), and protocol version. |
| **Components** | Reusable schema definitions: `messages`, `schemas`, `correlationIds`, `parameters`, `messageBindings`, `operationBindings`, `channelBindings`. |

### 1.3 WebSocket Binding Specifics

AsyncAPI 3.0 defines a `ws` operation binding with:
- **method**: WebSocket sub-protocol identifier
- **query**: URL query parameters for the WS handshake
- **headers**: HTTP headers sent during the WS upgrade
- **heartbeat**: Interval for heartbeat/ping-pong messages

A channel can have both `send` and `receive` operations (bidirectional), making it suitable for Soothe's full-duplex WebSocket.

### 1.4 Design Principles Extracted

| # | Principle | Description |
|---|-----------|-------------|
| A1 | **Channel-based routing** | Messages are organized by logical channels, not flat global namespaces. Each channel has defined operations and accepted message types. |
| A2 | **OneOf message schemas** | A channel declares `oneOf: [{$ref: MsgA}, {$ref: MsgB}, ...]` — every possible message type on that channel is explicitly listed and schema-validated. No undocumented message types. |
| A3 | **First-class correlation ID** | The `correlationId` object declares which field carries the correlation key and where it lives (header or payload). It is a structural part of the spec, not a convention. |
| A4 | **Reusable component model** | Message schemas, correlation IDs, and bindings are defined once in `components` and referenced by `$ref`. Eliminates duplication. |
| A5 | **Protocol versioning at server level** | The `server.protocolVersion` field declares the wire protocol version. Clients can negotiate before connecting. |
| A6 | **Heartbeat as a binding** | Heartbeat/keepalive is a first-class configuration in the WebSocket binding, not an ad-hoc implementation. |
| A7 | **Specification-as-documentation** | The AsyncAPI document itself is human-readable documentation AND machine-parseable for code generation (client SDKs, test stubs, docs). |

### 1.5 Applicability to Soothe

| Soothe Issue | AsyncAPI Principle | Fit |
|--------------|-------------------|-----|
| 37 message types, only 8 in RFC-450 | A2 (OneOf schemas) | **Strong** — AsyncAPI would require every message type to be formally declared with a schema |
| No Pydantic models / ad-hoc `dict.get` | A2 + A4 (Component schemas) | **Strong** — JSON Schema definitions can be converted to Pydantic models |
| `request_id` used inconsistently | A3 (Correlation ID) | **Strong** — AsyncAPI makes correlation ID a structural requirement |
| No protocol version | A5 (Server protocolVersion) | **Strong** — Direct fit |
| RFC-450 is stale / incomplete | A7 (Spec-as-docs) | **Strong** — AsyncAPI document replaces ad-hoc RFC tables |
| `cmd`/`command` collision | A2 (OneOf per channel) | **Partial** — AsyncAPI would force separate channels or message types, but doesn't prescribe envelope design |
| No heartbeat mechanism | A6 (Heartbeat binding) | **Moderate** — Soothe could benefit from heartbeat for dead-connection detection |

**Limitation**: AsyncAPI is a *specification format*, not a *protocol*. It describes APIs but doesn't define runtime behavior (handshake sequences, error semantics, subscription lifecycle). It must be paired with a protocol convention (JSON-RPC or graphql-ws) for behavioral rules.

---

## 2. JSON-RPC 2.0 over WebSocket

### 2.1 Overview

JSON-RPC 2.0 is a stateless, lightweight remote procedure call protocol using JSON as data format. It is transport-agnostic — the spec explicitly notes it can be used "over sockets" — making it a natural fit for WebSocket. It defines a minimal but complete request/response/error model with built-in correlation.

### 2.2 Core Specification

**Request object**:
```json
{
  "jsonrpc": "2.0",
  "method": "loop_input",
  "params": {"loop_id": "abc", "content": "hello"},
  "id": "req_123"
}
```

- `jsonrpc`: Always `"2.0"` — version field, enables protocol negotiation
- `method`: The procedure name (replaces Soothe's `type` field)
- `params`: Structured (object) or positional (array) parameters (replaces flat field sprawl)
- `id`: Client-established identifier (String, Number, or Null). **If absent, the request is a notification** (no response expected)

**Response object (success)**:
```json
{
  "jsonrpc": "2.0",
  "result": {"loop_id": "abc", "success": true},
  "id": "req_123"
}
```

**Response object (error)**:
```json
{
  "jsonrpc": "2.0",
  "error": {"code": -32600, "message": "Invalid Request", "data": {"detail": "loop_id is required"}},
  "id": "req_123"
}
```

**Error object structure**:
- `code`: Integer error code (reserved ranges defined by spec)
- `message`: Human-readable summary string
- `data`: Optional additional details (any JSON value)

### 2.3 Error Code Taxonomy

JSON-RPC 2.0 defines a **reserved error code range** from -32768 to -32000:

| Code | Meaning | Description |
|------|---------|-------------|
| -32700 | Parse error | Invalid JSON received |
| -32600 | Invalid Request | The JSON sent is not a valid Request object |
| -32601 | Method not found | The method does not exist / is not available |
| -32602 | Invalid params | Invalid method parameters |
| -32603 | Internal error | Internal JSON-RPC error |
| -32000 to -32099 | Server error | Reserved for implementation-defined server errors |

The range -31999 to -1 is **available for application-defined errors**. This gives Soothe a structured namespace: protocol errors in the reserved range, application errors (LOOP_NOT_FOUND, JOB_NOT_FOUND, etc.) in the custom range.

### 2.4 Notification vs Request Distinction

This is JSON-RPC's most elegant design decision:

- **Request** (`id` present): Server MUST respond with a `result` or `error` object containing the same `id`
- **Notification** (`id` absent): Server MUST NOT respond. The message is fire-and-forget.

This eliminates the need for separate "send" vs "request_response" client methods. The caller decides at call time whether to include `id`.

### 2.5 Batch Support

JSON-RPC 2.0 supports **batch requests** — an array of Request/Notification objects sent in a single message, with responses returned as an array:

```json
[
  {"jsonrpc": "2.0", "method": "loop_get", "params": {"loop_id": "a"}, "id": "1"},
  {"jsonrpc": "2.0", "method": "loop_get", "params": {"loop_id": "b"}, "id": "2"},
  {"jsonrpc": "2.0", "method": "loop_detach", "params": {"loop_id": "a"}}
]
```

Response:
```json
[
  {"jsonrpc": "2.0", "result": {...}, "id": "1"},
  {"jsonrpc": "2.0", "result": {...}, "id": "2"}
]
```

(The third item is a notification — no response entry.)

### 2.6 Design Principles Extracted

| # | Principle | Description |
|---|-----------|-------------|
| J1 | **Version field is mandatory** | `jsonrpc: "2.0"` in every message. Enables version detection and negotiation at the message level. |
| J2 | **Method + params envelope** | All requests use `method` (string) + `params` (structured object). No flat field sprawl. No type-vs-field-name collisions. |
| J3 | **ID-based correlation is structural** | `id` is a required field for requests; its presence/absence defines request vs notification semantics. No ambiguity about whether a response is expected. |
| J4 | **Unified error object** | Errors always have `{code, message, data}` with numeric codes. Reserved ranges prevent conflicts. `data` is optional for machine-parseable details. |
| J5 | **Reserved vs application error ranges** | Protocol-level errors use reserved codes (-32700 to -32000). Application errors use custom codes. Clean separation. |
| J6 | **Batch support** | Multiple operations in one message reduce round-trips for bulk operations. |
| J7 | **Response symmetry** | Response always echoes the request `id`. Client can match responses to requests unambiguously, even with interleaved streaming. |
| J8 | **Stateless protocol** | Each request is independent. No required server-side session state for RPC (though the application may maintain sessions). |

### 2.7 Applicability to Soothe

| Soothe Issue | JSON-RPC Principle | Fit |
|--------------|-------------------|-----|
| `cmd`/`command` collision (two `type: "command"` formats) | J2 (method+params) | **Strong** — `method: "command"` with `params: {cmd: "/exit"}` vs `method: "rpc_command"` with `params: {command: "autopilot_status"}` — no collision |
| `send_*` vs `request_response` duality | J3 (id = request, no id = notification) | **Strong** — eliminates the two API styles; caller includes `id` when they want a response |
| 20+ ad-hoc error codes, no taxonomy | J4 + J5 (structured errors, reserved ranges) | **Strong** — numeric codes with reserved ranges; `INVALID_REQUEST` → -32602, `LOOP_NOT_FOUND` → -31001 (custom) |
| Malformed error at router.py:1414 (`"error"` instead of `"code"`) | J4 (unified error object) | **Strong** — structurally impossible to have inconsistent error format |
| `request_id` inconsistency on errors | J7 (response echoes id) | **Strong** — error response MUST include the request `id` |
| No protocol version | J1 (mandatory version field) | **Strong** — `jsonrpc: "2.0"` in every message |
| No schema validation | J2 (structured params) | **Moderate** — `params` as a structured object makes validation natural, but JSON-RPC doesn't mandate schema |
| Bulk loop operations (list+get+tree) | J6 (batch) | **Moderate** — useful for CLI batch queries, but not critical for TUI streaming |
| Unknown message types silently ignored | J4 + spec rule (method not found = -32601) | **Strong** — JSON-RPC spec requires returning -32601 for unknown methods |

**Limitation**: JSON-RPC is fundamentally a **request/response** protocol. It does not natively model **server-initiated streaming** (agent output events pushed to the client without a corresponding request). Soothe needs a subscription model for streaming events — JSON-RPC alone cannot express "subscribe to this loop and receive N events over time."

---

## 3. GraphQL Subscriptions over WebSocket (graphql-ws Protocol)

### 3.1 Overview

The graphql-ws protocol (sub-protocol `graphql-transport-ws`) defines a minimal but complete message flow for bidirectional WebSocket communication with subscription lifecycle. It separates **connection-level** concerns (init, ack, heartbeat) from **operation-level** concerns (subscribe, next, error, complete). This two-level model is directly relevant to Soothe's daemon connection lifecycle.

### 3.2 Message Types

| Message | Direction | Purpose |
|---------|-----------|---------|
| `connection_init` | Client → Server | Initialize connection; optional `payload` for auth/capability declaration |
| `connection_ack` | Server → Client | Acknowledge connection; optional `payload` for server capabilities |
| `ping` | Bidirectional | Heartbeat / latency detection |
| `pong` | Bidirectional | Heartbeat response |
| `subscribe` | Client → Server | Start a subscription operation; carries `id` (operation ID) + `payload` (operation details) |
| `next` | Server → Client | Stream event for an active subscription; carries `id` + `payload` (result data) |
| `error` | Server → Client | Operation error; terminates the operation; carries `id` + `payload` (error array) |
| `complete` | Bidirectional | End an operation (server: stream complete; client: unsubscribe); carries `id` |

### 3.3 Connection Lifecycle

```
Client                          Server
  |                               |
  |--- connection_init ---------->|  (auth, capabilities)
  |<---------- connection_ack ----|  (server capabilities)
  |                               |
  |--- subscribe (id=1) --------->|  (start operation)
  |<---------- next (id=1) -------|  (stream event 1)
  |<---------- next (id=1) -------|  (stream event 2)
  |<---------- complete (id=1) ---|  (stream ended)
  |                               |
  |--- subscribe (id=2) --------->|  (another operation, interleaved)
  |<---------- next (id=2) -------|
  |<---------- error (id=2) ------|  (operation failed, terminated)
  |                               |
  |--- ping --------------------->|
  |<--------------------- pong ---|
  |                               |
  |--- complete (id=1) ---------->|  (client unsubscribes early)
  |                               |
  |--- close frame -------------->|  (normal closure)
```

### 3.4 Key Design Decisions

1. **Operation IDs are client-generated and unique per active subscription**. The server rejects duplicate IDs with a socket close (`4409`). IDs can be reused after completion.

2. **Multiple operations can be interleaved** on a single connection. Each `next`/`error`/`complete` message carries the operation `id`, so the client can route events to the correct handler.

3. **Connection init is mandatory before operations**. If the client sends `subscribe` before `connection_ack`, the server closes the socket with `4401: Unauthorized`.

4. **Invalid messages cause immediate socket closure** with `4400: <error-message>`. There is no "silently ignore unknown message type" behavior — strict validation.

5. **`complete` is idempotent and race-safe**. The protocol explicitly notes: "the asynchronous nature of the full-duplex connection means that a client can send a `complete` message even when messages are in-flight... Both client and server must be prepared to receive (and ignore) messages for operations that they consider already completed."

6. **Heartbeat is bidirectional**. Either party can send `ping` at any time; the receiver MUST respond with `pong`. This enables dead-connection detection from either end.

### 3.5 Design Principles Extracted

| # | Principle | Description |
|---|-----------|-------------|
| G1 | **Two-level lifecycle (connection + operation)** | Connection-level handshake (init/ack) is separate from operation-level lifecycle (subscribe/next/complete). This cleanly separates "is the connection valid?" from "is this operation active?" |
| G2 | **Capability negotiation in connection_init** | The `connection_init` payload carries client capabilities/auth. The `connection_ack` payload carries server capabilities. This is a structured negotiation, not a one-way readiness check. |
| G3 | **Per-operation correlation IDs** | Each subscription has a client-generated `id`. All stream events carry this `id`. Multiple operations can be active and interleaved on one connection. |
| G4 | **Explicit stream termination** | `complete` message marks the end of a stream. The client knows when no more events will arrive. No ambiguous "stream ended because of timeout vs stream ended because it's done." |
| G5 | **Bidirectional heartbeat** | `ping`/`pong` from either party enables dead-connection detection from both client and server. |
| G6 | **Strict validation = connection termination** | Invalid/unknown messages close the connection immediately. This prevents protocol drift and forces clients to be spec-compliant. |
| G7 | **Race-safe completion** | In-flight messages for completed operations are explicitly defined as "ignore, not error." This handles the async reality of full-duplex connections. |
| G8 | **Error terminates the operation** | An `error` message ends the subscription — no further events for that `id`. This is cleaner than Soothe's "error then maybe more events then maybe a response" ambiguity. |

### 3.6 Applicability to Soothe

| Soothe Issue | graphql-ws Principle | Fit |
|--------------|---------------------|-----|
| `daemon_ready` is one-way, no capability negotiation | G2 (connection_init/ack) | **Strong** — `connection_init` payload could carry client version, supported features; `connection_ack` carries server version, capabilities |
| No heartbeat / dead-connection detection | G5 (bidirectional ping/pong) | **Strong** — direct fit; daemon and client can both detect dead connections |
| Unknown message types silently ignored | G6 (strict validation) | **Strong** — graphql-ws closes connection on invalid messages; Soothe should at least send an error response |
| `loop_subscribe` double response (subscription_confirmed + loop_subscribe_response) | G1 (two-level lifecycle) | **Strong** — `connection_ack` handles connection-level confirmation; `subscribe` handles operation-level; no double response needed |
| No explicit stream termination | G4 (complete message) | **Strong** — Soothe's agent streams don't have an explicit "stream done" message; `complete` would fix this |
| Stream events have no per-operation ID | G3 (per-operation IDs) | **Moderate** — Soothe's `loop_id` serves a similar role, but multiple concurrent operations on one loop would need per-operation IDs |
| Error handling ambiguity (error then more events?) | G8 (error terminates operation) | **Strong** — clear contract: error ends the operation |
| In-flight messages after detach | G7 (race-safe completion) | **Strong** — explicitly defined behavior for messages arriving after completion |

**Limitation**: graphql-ws is designed for **GraphQL subscriptions only** — the `subscribe` payload is always `{query, variables, operationName}`. It has no concept of RPC methods (loop_get, job_create, etc.). The subscribe/next/error/complete lifecycle maps perfectly to Soothe's streaming use case, but the RPC use case needs a different message model (JSON-RPC's method+params).

---

## 4. STOMP Protocol (v1.2)

### 4.1 Overview

STOMP (Simple Text Oriented Messaging Protocol) is a frame-based protocol modeled on HTTP. It defines a small set of client and server frames for messaging: CONNECT, CONNECTED, SEND, SUBSCRIBE, UNSUBSCRIBE, MESSAGE, ACK, NACK, RECEIPT, ERROR, DISCONNECT. While STOMP is typically used with message brokers, its frame design and negotiation patterns are relevant to Soothe's pub/sub event bus.

### 4.2 Frame Structure

```
COMMAND
header1:value1
header2:value2

body^@
```

Frames consist of a command, zero or more headers (key:value), a blank line, a body, and a NULL terminator. This is text-based, UTF-8 encoded, and human-readable.

### 4.3 Key Frames

| Frame | Direction | Purpose |
|-------|-----------|---------|
| `CONNECT` / `STOMP` | Client → Server | Initiate connection with `accept-version`, `host`, `login`, `passcode`, `heart-beat` headers |
| `CONNECTED` | Server → Client | Acknowledge connection with `version`, `heart-beat` headers |
| `SUBSCRIBE` | Client → Server | Subscribe to a destination; carries `destination`, `id` (subscription ID), `ack` mode |
| `UNSUBSCRIBE` | Client → Server | Cancel subscription by `id` |
| `SEND` | Client → Server | Send a message to a `destination` |
| `MESSAGE` | Server → Client | Deliver a message to a subscriber; carries `subscription` (ID), `message-id`, `destination` |
| `ACK` | Client → Server | Acknowledge a message (in `client` or `client-individual` ack mode) |
| `NACK` | Client → Server | Negative acknowledge (message not processed, server can redeliver) |
| `RECEIPT` | Server → Client | Confirm receipt of a client frame that included a `receipt` header |
| `ERROR` | Server → Client | Error frame with `message` header and optional body |
| `DISCONNECT` | Client → Server | Clean disconnect with optional `receipt` header |

### 4.4 Protocol Negotiation

STOMP 1.2 introduces explicit version negotiation:

1. Client sends `CONNECT` with `accept-version:1.2` (can list multiple: `1.2,1.1,1.0`)
2. Server responds with `CONNECTED` and `version:1.2` (the highest version both support)
3. If no compatible version, server sends `ERROR` frame

This is a clean **version negotiation handshake** — the client declares what it accepts, the server picks the highest compatible version.

### 4.5 Heart-beating

STOMP 1.2 defines a `heart-beat` header in both `CONNECT` and `CONNECTED`:
- Format: `heart-beat: <cx>,<cy>` where `cx` = client's minimum heartbeat interval, `cy` = client's desired heartbeat interval
- Server responds with its own `heart-beat: <sx>,<sy>`
- The effective heartbeat is `max(cx, sy)` for server→client and `max(sx, cy)` for client→server
- A `0` value means "no heartbeat from this direction"

This is a **negotiated heartbeat** — both parties declare their capabilities and the effective rate is computed. More sophisticated than graphql-ws's simple ping/pong.

### 4.6 Receipt Mechanism

STOMP's `receipt` header is a lightweight acknowledgment for fire-and-forget messages:
- Client adds `receipt: <unique-id>` to any frame (SEND, SUBSCRIBE, DISCONNECT, etc.)
- Server MUST respond with a `RECEIPT` frame carrying `receipt-id: <same-id>`
- This gives the client confirmation that the server received and processed the frame

This elegantly solves Soothe's "fire-and-forget but I want to know it arrived" problem without requiring a full request/response cycle.

### 4.7 Acknowledgment Modes

STOMP defines three `ack` modes for subscriptions:
- `auto` (default): Server sends messages; client doesn't ACK; no redelivery
- `client`: Client must ACK or NACK each message; unacked messages are redelivered on reconnect
- `client-individual`: Like `client` but ACK is per-message, not cumulative

This gives subscribers control over message delivery guarantees.

### 4.8 Design Principles Extracted

| # | Principle | Description |
|---|-----------|-------------|
| S1 | **Explicit version negotiation** | Client declares accepted versions; server picks highest compatible. No guessing about protocol version. |
| S2 | **Negotiated heartbeat** | Both parties declare heartbeat capabilities; effective rate is computed from both declarations. More robust than fixed-interval pings. |
| S3 | **Receipt mechanism** | Lightweight per-frame acknowledgment via `receipt` header. Optional, per-message, doesn't require request/response overhead. |
| S4 | **Subscription IDs are first-class** | `SUBSCRIBE` carries an `id`; `MESSAGE` frames reference the subscription `id`. Multiple subscriptions per connection, each with unique ID. |
| S5 | **Destination-based routing** | Messages are sent to `destination` strings (opaque to the protocol). Server defines destination semantics. This separates routing from message content. |
| S6 | **ACK/NACK for delivery guarantees** | Subscribers can acknowledge or reject messages, enabling at-least-once delivery semantics. |
| S7 | **ERROR frame with message + body** | Error frames have a `message` header (summary) and optional body (details). Consistent structure. |
| S8 | **Clean disconnect with receipt** | `DISCONNECT` with `receipt` header ensures the server processes all prior frames before closing. |

### 4.9 Applicability to Soothe

| Soothe Issue | STOMP Principle | Fit |
|--------------|----------------|-----|
| No protocol version | S1 (accept-version negotiation) | **Strong** — `accept-version` in handshake; server picks version |
| No heartbeat / dead connections | S2 (negotiated heartbeat) | **Strong** — bidirectional, rate-negotiated |
| Fire-and-forget messages with no delivery confirmation | S3 (receipt mechanism) | **Strong** — `send_input` is fire-and-forget but clients want to know it was received; `receipt` solves this elegantly |
| `loop_subscribe` produces double response | S4 (subscription ID is first-class) | **Moderate** — Soothe's `loop_id` is similar, but STOMP's explicit `id` per subscription is cleaner |
| Event routing is ad-hoc | S5 (destination-based routing) | **Moderate** — Soothe already uses `loop:{loop_id}` topics internally; STOMP formalizes this |
| No delivery guarantee for events | S6 (ACK/NACK) | **Weak** — Soothe's events are ephemeral stream chunks, not durable messages; ACK/NACK adds complexity without value |
| Error format inconsistency | S7 (ERROR frame structure) | **Moderate** — STOMP's `message` header + body is simpler than JSON-RPC's code/message/data, but less structured |
| Client disconnect doesn't guarantee processing | S8 (receipt on disconnect) | **Moderate** — useful for clean shutdown, but Soothe's `detach` is simpler |

**Limitation**: STOMP is a **messaging protocol**, not an RPC protocol. It has no concept of request/response correlation or method invocation. Its `SEND` frame is fire-and-forget (with optional receipt). For Soothe's RPC needs (loop_get, job_status, etc.), STOMP alone is insufficient. Its strengths are in subscription management, heartbeat, and version negotiation.

---

## 5. Common Patterns Across Standards

### 5.1 Message Envelope Design: Type+Payload vs Flat

| Standard | Envelope Style | Example |
|----------|---------------|---------|
| **JSON-RPC 2.0** | Method+params (nested) | `{"jsonrpc":"2.0", "method":"loop_get", "params":{"loop_id":"a"}, "id":"1"}` |
| **graphql-ws** | Type+payload (nested) | `{"type":"subscribe", "id":"1", "payload":{"query":"..."}}` |
| **STOMP** | Command+headers+body (flat headers, separate body) | `SEND\ndestination:loops/a\n\n{"text":"hello"}^@` |
| **AsyncAPI** | Describes both; no mandate | Schema can be flat or nested |

**Soothe's current approach**: Flat — `{"type": "loop_get", "loop_id": "a", "request_id": "1"}`. This works for simple messages but becomes unwieldy for complex params (e.g., `loop_input` with 13+ fields).

**Best practice**: Use a **type/method + payload envelope** where `type`/`method` identifies the operation and `payload`/`params` carries the structured parameters. This:
- Separates protocol metadata (`type`, `id`, `version`) from operation data (`params`)
- Makes validation easier (validate `params` as a unit against a schema)
- Prevents field name collisions between protocol and operation layers
- Enables `oneOf` message schemas (each message type has its own `params` schema)

### 5.2 Correlation IDs

| Standard | Field Name | Location | Semantics |
|----------|-----------|----------|-----------|
| **JSON-RPC** | `id` | Top-level | Present = request (response expected); absent = notification (no response) |
| **graphql-ws** | `id` | Top-level | Per-operation; links `subscribe` → `next`/`error`/`complete` |
| **STOMP** | `receipt` | Header | Per-frame; server confirms with `RECEIPT` frame |
| **AsyncAPI** | `correlationId` | Declared in spec | Points to field location (header or payload) |

**Soothe's current approach**: `request_id` — optional, inconsistently included in responses, no structural requirement for its presence.

**Best practice**: Correlation ID should be:
1. **Mandatory for request/response messages** (JSON-RPC: `id` required for requests)
2. **Echoed in every response** (JSON-RPC: response MUST contain same `id`)
3. **Per-operation for streams** (graphql-ws: each subscription has its own `id`)
4. **Declared in the spec** (AsyncAPI: `correlationId` location is explicit)

### 5.3 Versioning Fields

| Standard | Approach | Granularity |
|----------|----------|-------------|
| **JSON-RPC** | `"jsonrpc": "2.0"` in every message | Per-message |
| **STOMP** | `accept-version` in CONNECT, `version` in CONNECTED | Per-connection (negotiated) |
| **graphql-ws** | Sub-protocol identifier in WebSocket handshake (`graphql-transport-ws`) | Per-connection |
| **AsyncAPI** | `server.protocolVersion` in spec | Per-server (declarative) |

**Best practice**: Use **per-connection version negotiation** (STOMP/graphql-ws style) for the initial handshake, and optionally a **per-message version field** (JSON-RPC style) for protocol evolution. The connection-level negotiation determines the protocol version; the message-level field enables within-version extensions.

### 5.4 Capability Negotiation

| Standard | Mechanism | Example |
|----------|-----------|---------|
| **graphql-ws** | `connection_init` payload | `{"type":"connection_init", "payload":{"authToken":"...", "clientVersion":"1.0"}}` |
| **STOMP** | CONNECT headers | `accept-version`, `heart-beat`, `host` |
| **AsyncAPI** | Server bindings + operation bindings | Declared in spec, not negotiated at runtime |

**Best practice**: A **connection_init/ack handshake** where:
1. Client declares its capabilities (version, supported features, auth credentials)
2. Server responds with its capabilities (version, available features, server limits)
3. Both parties can reject incompatible connections before any operations

### 5.5 Error Standardization

| Standard | Error Structure | Code Type | Reserved Range |
|----------|----------------|-----------|----------------|
| **JSON-RPC** | `{code, message, data}` | Integer | -32768 to -32000 (reserved), -31999 to -1 (app) |
| **graphql-ws** | `GraphQLError[]` in payload | N/A (uses GraphQL error format) | N/A |
| **STOMP** | ERROR frame with `message` header + body | None (string message) | N/A |
| **AsyncAPI** | Defined per-message schema | Any (schema-defined) | N/A |

**Best practice**: Follow JSON-RPC's structured error model:
1. **Numeric codes** with reserved ranges (protocol errors vs application errors)
2. **Mandatory `message` string** for human-readable summary
3. **Optional `data` field** for machine-parseable details
4. **Error terminates the operation** (graphql-ws principle G8)

### 5.6 Schema Validation

| Standard | Validation Approach |
|----------|-------------------|
| **AsyncAPI** | JSON Schema per message; `oneOf` for multi-message channels |
| **JSON-RPC** | No mandated schema; `params` can be structured or positional |
| **graphql-ws** | TypeScript interfaces; runtime validation by implementation |
| **STOMP** | No schema; headers are untyped strings |

**Best practice**: Use **AsyncAPI message schemas** (JSON Schema) as the source of truth, and generate **Pydantic models** from them for runtime validation. This gives:
- Machine-readable spec (AsyncAPI document)
- Human-readable docs (generated from spec)
- Runtime validation (Pydantic model_validate)
- Type-safe client construction (Pydantic models in SDK)

---

## 6. Mapping Each Principle to Soothe's Current API

### 6.1 Comprehensive Mapping Table

| Soothe Issue (from prior review) | Best Standard | Principle | Recommended Fix |
|----------------------------------|--------------|-----------|-----------------|
| **No protocol version field** | STOMP + JSON-RPC | S1 + J1 | Add `protocol_version` to `daemon_ready` handshake (STOMP-style `accept-version`); add `"jsonrpc":"2.0"` or `"proto":"1"` to every message |
| **No capability negotiation** | graphql-ws | G2 | Replace one-way `daemon_ready` with bidirectional `connection_init`/`connection_ack` exchange; client declares version+features, server responds with capabilities |
| **`cmd`/`command` collision** | JSON-RPC | J2 | Use `method` + `params` envelope: `{"method":"slash_command", "params":{"cmd":"/exit"}}` vs `{"method":"rpc_command", "params":{"command":"autopilot_status"}}` — no collision |
| **`send_*` vs `request_response` duality** | JSON-RPC | J3 | `id` present = request (response expected); `id` absent = notification (fire-and-forget). One client method, caller decides. |
| **37 message types, only 8 in RFC-450** | AsyncAPI | A2 + A7 | Write an AsyncAPI document with all 37 message types as `oneOf` on the WebSocket channel. Replace RFC-450 message tables with the AsyncAPI spec. |
| **No Pydantic models / ad-hoc dict.get** | AsyncAPI + JSON-RPC | A4 + J2 | Define JSON Schema per message type → generate Pydantic models → validate `params` before dispatch |
| **Malformed error (router.py:1414)** | JSON-RPC | J4 | Structured error object `{code, message, data}` — structurally impossible to have inconsistent format |
| **20+ ad-hoc error codes, no taxonomy** | JSON-RPC | J4 + J5 | Numeric codes: -32600 series for protocol errors, -31xxx for application errors. Document all in a registry. |
| **`request_id` inconsistency on errors** | JSON-RPC | J7 | Error response MUST echo the request `id`. Structural requirement. |
| **Unknown message types silently ignored** | JSON-RPC + graphql-ws | J4 + G6 | Return -32601 (method not found) for unknown methods; consider closing connection for repeated violations (graphql-ws G6) |
| **`loop_subscribe` double response** | graphql-ws | G1 | `connection_ack` handles connection-level confirmation; `subscribe` is operation-level. One response per action. |
| **No heartbeat / dead-connection detection** | graphql-ws + STOMP | G5 + S2 | Implement bidirectional `ping`/`pong`; consider STOMP-style negotiated heartbeat intervals |
| **No explicit stream termination** | graphql-ws | G4 | Add `complete` message when agent stream finishes. Client knows no more events will arrive. |
| **Fire-and-forget with no delivery confirmation** | STOMP | S3 | Add optional `receipt` field to fire-and-forget messages; server confirms with receipt response |
| **`verbose`/`format` fields silently ignored** | AsyncAPI | A2 | Schema declares these as optional; if accepted, they MUST be used or rejected (not silently ignored) |
| **Error then more events ambiguity** | graphql-ws | G8 | Define: error terminates the operation. No further events for that operation ID. |
| **In-flight messages after detach** | graphql-ws | G7 | Define: messages for completed/detached operations are ignored, not errors. |
| **RFC-450 uses `thread_id`, code uses `loop_id`** | AsyncAPI | A2 | AsyncAPI spec declares `loop_id` as the field; RFC-450 is superseded by the spec document. |
| **No batch support for CLI queries** | JSON-RPC | J6 | Support JSON array of requests for bulk loop operations. |
| **`content` vs `text` field naming** | JSON-RPC | J2 | All input goes in `params.content`; no flat-field naming ambiguity. |
| **`workspace` vs `client_workspace` aliases** | JSON-RPC | J2 | Single `params.workspace` field; no aliases. |

### 6.2 Principle Coverage Matrix

| Principle | AsyncAPI | JSON-RPC | graphql-ws | STOMP |
|-----------|----------|----------|------------|-------|
| Message envelope design | ✅ (describes) | ✅ (method+params) | ✅ (type+payload) | ✅ (command+headers+body) |
| Correlation IDs | ✅ (correlationId) | ✅ (id, structural) | ✅ (id, per-operation) | ✅ (receipt) |
| Versioning | ✅ (protocolVersion) | ✅ (per-message) | ✅ (sub-protocol) | ✅ (negotiated) |
| Capability negotiation | ❌ | ❌ | ✅ (connection_init) | ✅ (CONNECT headers) |
| Error standardization | ✅ (per-schema) | ✅ (code+message+data) | ✅ (terminates op) | ✅ (ERROR frame) |
| Schema validation | ✅ (JSON Schema) | ❌ | ❌ | ❌ |
| Subscription lifecycle | ❌ | ❌ | ✅ (subscribe/next/complete) | ✅ (SUBSCRIBE/UNSUBSCRIBE) |
| Heartbeat | ✅ (binding) | ❌ | ✅ (ping/pong) | ✅ (negotiated) |
| Batch support | ❌ | ✅ | ❌ | ❌ |
| Delivery confirmation | ❌ | ✅ (id=response) | ✅ (id=next/error/complete) | ✅ (receipt) |
| Documentation generation | ✅ (spec-as-docs) | ❌ | ❌ | ❌ |

---

## 7. Recommended Hybrid Approach for Soothe

### 7.1 The Case for a Hybrid

Soothe's daemon API is a **bidirectional streaming + RPC hybrid**:
- **Streaming**: Agent output events pushed to subscribed clients (like graphql-ws subscriptions)
- **RPC**: Loop management, job control, skill invocation (like JSON-RPC method calls)
- **Fire-and-forget**: User input submission (like STOMP SEND without receipt)

No single standard covers all three modes. The recommended approach borrows the best-fitting piece from each standard:

```
┌─────────────────────────────────────────────────────────┐
│                   AsyncAPI 3.0 Spec                      │
│  (declarative spec: channels, operations, messages,     │
│   schemas, correlationIds, WebSocket bindings)           │
└──────────────────────┬──────────────────────────────────┘
                       │ governs
┌──────────────────────▼──────────────────────────────────┐
│              Runtime Protocol (hybrid)                   │
│                                                         │
│  ┌────────────────────────────────────────────────────┐ │
│  │  Connection Layer (from graphql-ws + STOMP)        │ │
│  │  • connection_init (client caps + version)         │ │
│  │  • connection_ack (server caps + version)          │ │
│  │  • ping/pong (bidirectional heartbeat)             │ │
│  └────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌────────────────────────────────────────────────────┐ │
│  │  RPC Layer (from JSON-RPC 2.0)                     │ │
│  │  • {method, params, id} for requests               │ │
│  │  • {result, id} for success responses              │ │
│  │  • {error: {code, message, data}, id} for errors   │ │
│  │  • {method, params} (no id) for notifications      │ │
│  │  • Batch support (array of requests)               │ │
│  └────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌────────────────────────────────────────────────────┐ │
│  │  Subscription Layer (from graphql-ws)              │ │
│  │  • subscribe (id, params: {loop_id, ...})          │ │
│  │  • next (id, payload: event data)                  │ │
│  │  • error (id, payload: error) — terminates op      │ │
│  │  • complete (id) — stream ended                    │ │
│  │  • unsubscribe (id) — client cancels               │ │
│  └────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌────────────────────────────────────────────────────┐ │
│  │  Receipt Layer (from STOMP, optional)              │ │
│  │  • receipt field on any notification               │ │
│  │  • receipt_response with receipt-id                │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### 7.2 Proposed Wire Format

**Unified message envelope** (combines JSON-RPC structure with graphql-ws type semantics):

```json
{
  "proto": "1",
  "type": "request",
  "method": "loop_get",
  "params": {"loop_id": "abc123", "verbose": true},
  "id": "req_001"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `proto` | Yes | Protocol version string (`"1"`). Enables per-message version detection. (From JSON-RPC's `jsonrpc` field.) |
| `type` | Yes | Message class: `"request"`, `"response"`, `"notification"`, `"subscribe"`, `"next"`, `"error"`, `"complete"`, `"unsubscribe"`, `"ping"`, `"pong"`. (From graphql-ws's `type` field.) |
| `method` | For request/notification | RPC method name (e.g., `"loop_get"`, `"loop_input"`). (From JSON-RPC's `method` field.) |
| `params` | For request/notification/subscribe | Structured parameters object. (From JSON-RPC's `params` field.) |
| `id` | For request/subscribe/response/next/error/complete | Operation correlation ID. Absent for notifications. (From JSON-RPC's `id` + graphql-ws's `id`.) |
| `result` | For response (success) | The result data. (From JSON-RPC's `result` field.) |
| `error` | For error | `{code, message, data}` object. (From JSON-RPC's `error` field.) |
| `payload` | For next | Event data for a subscription stream. (From graphql-ws's `payload` field.) |
| `receipt` | Optional on any message | Receipt ID for delivery confirmation. (From STOMP's `receipt` header.) |

**Key design decisions**:
1. `type` distinguishes the **message class** (request vs subscription vs heartbeat); `method` names the **operation** within that class. This eliminates the `type`/`cmd`/`command` collision.
2. `params` is always a structured object — no flat field sprawl. Schema validation applies to `params` as a unit.
3. `id` is the single correlation mechanism. Present = response expected. Absent = fire-and-forget. No separate `request_id` concept.
4. `proto` version field in every message enables gradual migration.

### 7.3 Concrete Examples Mapped to Soothe

**RPC Request (replaces `loop_get`)**:
```json
// Client → Server
{"proto":"1", "type":"request", "method":"loop_get", "params":{"loop_id":"abc"}, "id":"r1"}

// Server → Client (success)
{"proto":"1", "type":"response", "result":{"loop_id":"abc", "status":"running", ...}, "id":"r1"}

// Server → Client (error)
{"proto":"1", "type":"error", "error":{"code":-31001, "message":"Loop not found", "data":{"loop_id":"abc"}}, "id":"r1"}
```

**Notification (replaces fire-and-forget `loop_input`)**:
```json
// Client → Server (no id = notification, no response expected)
{"proto":"1", "type":"notification", "method":"loop_input", "params":{"loop_id":"abc", "content":"hello"}}

// With receipt (client wants delivery confirmation)
{"proto":"1", "type":"notification", "method":"loop_input", "params":{"loop_id":"abc", "content":"hello"}, "receipt":"rc1"}

// Server → Client (receipt confirmation)
{"proto":"1", "type":"receipt_response", "receipt":"rc1"}
```

**Subscription (replaces `loop_subscribe` + event stream)**:
```json
// Client → Server
{"proto":"1", "type":"subscribe", "method":"loop_events", "params":{"loop_id":"abc", "stream_delivery":"adaptive"}, "id":"s1"}

// Server → Client (stream event)
{"proto":"1", "type":"next", "id":"s1", "payload":{"namespace":"assistant", "mode":"text", "data":"Hello!"}}

// Server → Client (stream event)
{"proto":"1", "type":"next", "id":"s1", "payload":{"namespace":"tool", "mode":"json", "data":{...}}}

// Server → Client (stream complete)
{"proto":"1", "type":"complete", "id":"s1"}

// Client → Server (unsubscribe early)
{"proto":"1", "type":"unsubscribe", "id":"s1"}
```

**Connection Handshake (replaces `daemon_ready`)**:
```json
// Client → Server
{"proto":"1", "type":"connection_init", "params":{"client_version":"0.5.0", "capabilities":["streaming", "batch", "receipts"]}}

// Server → Client
{"proto":"1", "type":"connection_ack", "result":{"server_version":"0.5.0", "protocol_version":"1", "capabilities":["streaming", "batch", "receipts", "heartbeat"], "readiness_state":"ready"}}
```

**Heartbeat**:
```json
// Either direction
{"proto":"1", "type":"ping"}

// Response
{"proto":"1", "type":"pong"}
```

### 7.4 Error Code Mapping

Adopt JSON-RPC's numeric code scheme with reserved ranges:

| Soothe Current Code | New Numeric Code | Range | Description |
|---------------------|-----------------|-------|-------------|
| (new) | -32700 | Parse error | Invalid JSON |
| (new) | -32600 | Invalid request | Message is not a valid request object |
| `UNKNOWN_MESSAGE_TYPE` / - | -32601 | Method not found | Unknown method/type |
| `INVALID_MESSAGE` / `INVALID_REQUEST` | -32602 | Invalid params | Invalid method parameters |
| `INTERNAL_ERROR` | -32603 | Internal error | Internal server error |
| `RATE_LIMITED` | -32000 | Server error | Rate limited |
| `DAEMON_STARTING` | -32001 | Server error | Daemon not ready |
| `DAEMON_BUSY` | -32002 | Server error | Daemon busy |
| `DAEMON_DEGRADED` | -32003 | Server error | Daemon degraded |
| `DAEMON_ERROR` | -32004 | Server error | Daemon error state |
| `NO_LOOP_SUBSCRIPTION` | -32100 | Application | No active loop subscription |
| `LOOP_NOT_SUBSCRIBED` | -32101 | Application | Loop not subscribed |
| `NO_SESSION` | -32102 | Application | No active session |
| `LOOP_NOT_FOUND` | -32200 | Application | Loop not found |
| `JOB_NOT_FOUND` | -32201 | Application | Job not found |
| `GOAL_NOT_FOUND` | -32202 | Application | Goal not found |
| `SKILL_NOT_FOUND` | -32203 | Application | Skill not found |
| `JOB_ALREADY_PAUSED` | -32300 | Application | State conflict |
| `JOB_NOT_PAUSED` | -32301 | Application | State conflict |
| `JOB_COMPLETED` | -32302 | Application | State conflict |
| `SKILL_LOAD_FAILED` | -32400 | Application | Operation failure |
| `RUNNER_UNAVAILABLE` | -32401 | Application | Operation failure |
| `AUTOPILOT_NOT_READY` | -32402 | Application | Operation failure |
| `CARD_MANAGER_UNAVAILABLE` | -32403 | Application | Operation failure |
| `CARDS_FETCH_FAILED` | -32404 | Application | Operation failure |
| `LOOP_CONTEXT` | -32405 | Application | Operation failure |
| `LOOP_STATE` | -32406 | Application | Operation failure |
| `WORKSPACE_RESOLUTION_FAILED` | -32407 | Application | Operation failure |
| `JOB_CREATE_FAILED` | -32500 | Application | Job operation failure |
| `JOB_PAUSE_FAILED` | -32501 | Application | Job operation failure |
| `JOB_RESUME_FAILED` | -32502 | Application | Job operation failure |
| `JOB_CANCEL_FAILED` | -32503 | Application | Job operation failure |
| `LOOP_REATTACH_FAILED` | -32504 | Application | Operation failure |

**Ranges**:
- -32768 to -32000: Protocol-level (reserved by JSON-RPC convention)
- -32100 to -32199: Authorization/session errors
- -32200 to -32299: Resource not found
- -32300 to -32399: State conflicts
- -32400 to -32499: Operation failures
- -32500 to -32599: Job operation failures

### 7.5 AsyncAPI Specification Skeleton

```yaml
asyncapi: 3.0.0
info:
  title: Soothe Daemon WebSocket API
  version: 1.0.0
  description: |
    Bidirectional WebSocket protocol for daemon communication.
    Hybrid RPC + streaming subscription model.
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
    messages:
      $ref: '#/components/messages'
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
components:
  correlationIds:
    requestId:
      location: $message.header#/id
      description: Operation correlation ID
  messages:
    connectionInit:
      name: connectionInit
      title: Connection initialization
      correlationId:
        $ref: '#/components/correlationIds/requestId'
      payload:
        type: object
        properties:
          proto: {type: string, const: "1"}
          type: {type: string, const: "connection_init"}
          params:
            type: object
            properties:
              client_version: {type: string}
              capabilities:
                type: array
                items: {type: string}
    request:
      name: request
      title: RPC request
      correlationId:
        $ref: '#/components/correlationIds/requestId'
      payload:
        type: object
        required: [proto, type, method, params, id]
        properties:
          proto: {type: string, const: "1"}
          type: {type: string, const: "request"}
          method: {type: string, description: "RPC method name"}
          params: {type: object}
          id: {type: string}
          receipt: {type: string}
        oneOf:
          - properties:
              method: {const: "loop_get"}
              params:
                type: object
                required: [loop_id]
                properties:
                  loop_id: {type: string}
                  verbose: {type: boolean}
          - properties:
              method: {const: "loop_input"}
              params:
                type: object
                required: [loop_id, content]
                properties:
                  loop_id: {type: string}
                  content: {type: string}
                  autonomous: {type: boolean}
                  # ... all 13 fields
          # ... one entry per method
    # ... (similar definitions for all message types)
```

### 7.6 Migration Strategy

**Phase 1: Spec-First (AsyncAPI document)**
1. Write an AsyncAPI 3.0 document covering all 37 current message types
2. Generate Pydantic models from the JSON Schemas
3. Use generated models in `validate_message()` — covers all transports
4. This alone fixes: validation gaps, undocumented types, schema enforcement

**Phase 2: Error Standardization**
1. Adopt numeric error codes with reserved ranges (§7.4)
2. Create `_send_error()` helper enforcing `{code, message, data}` structure
3. Replace all inline error dicts with helper calls
4. This fixes: malformed errors, inconsistent error formats, missing `request_id`

**Phase 3: Connection Handshake**
1. Add `connection_init`/`connection_ack` handshake (replaces one-way `daemon_ready`)
2. Client declares version + capabilities; server responds with capabilities
3. Add bidirectional `ping`/`pong` heartbeat
4. This fixes: no versioning, no capability negotiation, no dead-connection detection

**Phase 4: Envelope Migration (breaking)**
1. Introduce `proto: "1"` field in all messages
2. Gradually migrate `type` from operation names (`loop_get`) to message classes (`request`)
3. Move operation-specific fields into `params` sub-object
4. Replace `request_id` with `id` (JSON-RPC semantics: absent = notification)
5. Add `complete` message for explicit stream termination
6. This fixes: envelope inconsistency, `cmd`/`command` collision, `send_*` vs `request_response` duality

**Phase 5: Subscription Lifecycle**
1. Map `loop_subscribe` to `subscribe` with per-operation `id`
2. Map stream events to `next` with matching `id`
3. Add `complete` when stream ends
4. Map `loop_detach` to `unsubscribe`
5. This fixes: double response on subscribe, no explicit stream termination, error-then-more-events ambiguity

**Phase 6: Optional Enhancements**
1. Add `receipt` mechanism for fire-and-forget delivery confirmation
2. Add batch support (JSON array of requests)
3. Generate client SDK stubs from AsyncAPI spec

### 7.7 What NOT to Adopt

| Standard | What to Skip | Why |
|----------|-------------|-----|
| STOMP | Frame-based wire format (command+headers+body) | JSON is already used; STOMP's text frame format adds parsing complexity without benefit |
| STOMP | ACK/NACK delivery guarantees | Soothe's events are ephemeral stream chunks, not durable messages requiring redelivery |
| STOMP | Destination-based routing | Soothe already has `loop_id`-based routing; STOMP destinations add an unnecessary indirection layer |
| graphql-ws | GraphQL query language | Soothe doesn't use GraphQL; the protocol structure is borrowed, not the query language |
| graphql-ws | Socket closure on invalid messages | Too aggressive for Soothe — a single bad message shouldn't kill the entire connection (which may have active streams) |
| JSON-RPC | Positional params (array) | Object params are always used in Soothe; positional params add ambiguity |
| AsyncAPI | Full broker messaging semantics | Soothe is a direct WebSocket connection, not a pub/sub broker; AsyncAPI's broker features are unnecessary |

---

## 8. Summary Comparison

| Dimension | AsyncAPI | JSON-RPC 2.0 | graphql-ws | STOMP | Soothe Current |
|-----------|----------|--------------|------------|-------|----------------|
| **Primary use case** | Spec format | RPC | Subscriptions | Messaging | Streaming + RPC hybrid |
| **Envelope** | Describes both | method+params | type+payload | command+headers+body | Flat (type+fields) |
| **Correlation ID** | correlationId (declared) | id (structural) | id (per-operation) | receipt (per-frame) | request_id (optional, inconsistent) |
| **Versioning** | protocolVersion | jsonrpc field | sub-protocol | accept-version (negotiated) | None |
| **Capability negotiation** | ❌ | ❌ | ✅ (connection_init) | ✅ (CONNECT headers) | ❌ |
| **Error model** | Per-schema | {code, message, data} | Terminates operation | ERROR frame | Ad-hoc (3 formats) |
| **Error code taxonomy** | N/A | Numeric, reserved ranges | N/A | None | 20+ string codes, no registry |
| **Schema validation** | ✅ (JSON Schema) | ❌ | ❌ | ❌ | Ad-hoc dict.get (6/37 types) |
| **Subscription lifecycle** | ❌ | ❌ | ✅ (subscribe/next/complete) | ✅ (SUBSCRIBE/UNSUBSCRIBE) | Partial (loop_subscribe, no complete) |
| **Heartbeat** | Binding (declared) | ❌ | ✅ (ping/pong) | ✅ (negotiated) | ❌ |
| **Batch** | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Delivery confirmation** | ❌ | id → response | id → next/complete | receipt | ❌ |
| **Documentation** | ✅ (spec-as-docs) | ❌ | ❌ | ❌ | RFC-450 (stale, 8/37 types) |
| **Fit for Soothe RPC** | Moderate | **Strong** | Weak | Weak | — |
| **Fit for Soothe streaming** | Moderate | Weak | **Strong** | Moderate | — |
| **Fit for Soothe spec/docs** | **Strong** | ❌ | ❌ | ❌ | — |

### Final Recommendation

**Adopt a JSON-RPC 2.0 + graphql-ws + AsyncAPI hybrid**:

1. **AsyncAPI 3.0** as the specification format — write one AsyncAPI document that formally declares all channels, operations, messages, schemas, and correlation IDs. This becomes the single source of truth, replacing the stale RFC-450 message tables and enabling auto-generated documentation and Pydantic model generation.

2. **JSON-RPC 2.0** envelope and error model for the RPC layer — `{proto, type, method, params, id}` envelope with `{code, message, data}` structured errors using numeric codes with reserved ranges. The `id` field's presence/absence semantics (request vs notification) eliminate the `send_*` vs `request_response` duality and the `cmd`/`command` collision.

3. **graphql-ws** connection lifecycle and subscription model — `connection_init`/`connection_ack` handshake with capability negotiation; `subscribe`/`next`/`error`/`complete` operation lifecycle with per-operation IDs; bidirectional `ping`/`pong` heartbeat. This provides explicit stream termination, race-safe completion, and dead-connection detection.

4. **STOMP** receipt mechanism (optional) — for fire-and-forget messages that need delivery confirmation without full request/response overhead.

This hybrid addresses all 21 issues identified in the prior API review: envelope collision, schema validation gaps, error inconsistency, missing versioning, capability negotiation, stream termination, heartbeat, and documentation gaps.
