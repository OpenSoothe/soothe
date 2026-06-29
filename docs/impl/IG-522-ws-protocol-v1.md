# IG-522: WebSocket Protocol v1 Implementation

**Guide**: IG-522
**Title**: Implement RFC-450 Unified Daemon Communication Protocol (Protocol-1 Wire Contract)
**Created**: 2026-06-28
**Related RFCs**: RFC-450 (Unified Daemon Communication Protocol), RFC-900 (Deprecation), RFC-620 (Channel Architecture), RFC-228 (Autopilot Job IPC), RFC-503 (Loop-First UX), RFC-504 (Loop Management CLI Commands)
**Scope**: Full protocol-1 wire contract implementation — clean-break replacement of the ad-hoc wire format across daemon, SDK, and CLI.
**Status**: Draft

---

## Goal

Implement the protocol-1 wire contract defined in RFC-450 as a complete, clean-break replacement for the current ad-hoc WebSocket message format. This is a simultaneous daemon + SDK update — clients connecting with the old format are rejected at handshake.

The protocol introduces:
- A unified `{proto, type, method, params, id}` envelope (hybrid JSON-RPC + graphql-ws)
- Schema validation via Pydantic models at the transport boundary
- Numeric `ErrorCode` IntEnum registry with reserved ranges
- Bidirectional `connection_init` / `connection_ack` handshake with capability negotiation
- A schema-validated dispatch table replacing the 32-branch `if`-chain in `MessageRouter`
- Subscription lifecycle (`subscribe` → `next` → `complete` / `unsubscribe` / `error`)

## Success Criteria

| Criterion | Verification |
|-----------|--------------|
| All messages use `{proto, type, method, params, id}` envelope | Unit tests assert envelope structure for every message type |
| `ErrorCode` IntEnum has all 37 codes per RFC-450 §7.3 | Unit test enumerates and checks each numeric value |
| `connection_init` / `connection_ack` handshake works | Integration test: client connects, handshakes, receives `readiness_state: "ready"` |
| Old-format messages rejected at handshake | Integration test: old `daemon_ready` message → `-32600 INVALID_REQUEST` |
| `MessageRouter` uses dispatch table, not if-chain | Grep confirms no `if msg_type ==` branches in `dispatch()`; `len(HANDLER_REGISTRY)` covers all methods |
| All 37+ message types validated against Pydantic models | Unit test feeds valid + invalid params for each `(type, method)` pair |
| `WebSocketClient` uses new envelope + blocking/non-blocking semantics | Unit tests for `request()` (blocking, with `id`) and `notify()` (fire-and-forget) |
| `WsCommandClient` migrated or removed | No old `{type: "command", command: ...}` wire format remains |
| `bootstrap_loop_session` uses new handshake | Integration test: bootstrap sends `connection_init`, waits for `connection_ack`, then `subscribe` |
| CLI works end-to-end with new protocol | Manual test: `soothe` headless + TUI against updated daemon |
| All tests pass | `./scripts/verify_finally.sh` passes |

---

## Architecture (from RFC-450 §3, §5, §6)

```
WebSocket/HTTP REST → Transport Layer (decode + validate) → Message Router → Handler Layer
                         │                                      │
                         ├─ 1. Decode raw bytes → dict           ├─ Receives validated, typed params
                         ├─ 2. Validate envelope (proto, type)  ├─ No inline `if not loop_id:` checks
                         ├─ 3. Look up Pydantic model by        ├─ Dispatches to handler by (type, method)
                         │     (type, method)                    └─ Returns result dict or raises ProtocolError
                         ├─ 4. model_validate(params) → validated or -32602
                         └─ 5. Pass validated params to router
```

### Component Flow

- **Transport Layer** (`channels/websocket.py`, `server/core.py`): JSON decode, envelope validation, Pydantic schema validation, router dispatch
- **Wire Schema Registry** (`protocol/schemas.py`): Maps `(type, method)` → Pydantic params model
- **Message Router** (`protocol/router.py`): Dispatches by `(type, method)` via `HANDLER_REGISTRY` table
- **Error Codes** (`protocol/error_codes.py`): `ErrorCode` IntEnum + `ProtocolError` helper
- **SDK Client** (`soothe_sdk/client/websocket.py`, `wire.py`, `session.py`): Envelope encoding, handshake, blocking/non-blocking RPC, subscription management

### New Module Layout

```
packages/soothe-daemon/src/soothe_daemon/protocol/
├── __init__.py           # Public exports (updated)
├── router.py             # Refactored: dispatch table (MODIFY)
├── validation.py         # Rewritten: Pydantic-based validation (MODIFY)
├── schemas.py            # NEW: Pydantic params models + PARAMS_REGISTRY
├── error_codes.py        # NEW: ErrorCode IntEnum
├── errors.py             # NEW: ProtocolError + convenience constructors
└── envelope.py           # NEW: Envelope Pydantic models (proto, type, method, params, id)

packages/soothe-sdk/src/soothe_sdk/client/
├── wire.py               # ADD: envelope models + wire helpers (shared models)
├── websocket.py          # MODIFY: new envelope, handshake, blocking/non-blocking
├── session.py            # MODIFY: bootstrap_loop_session uses connection_init/ack
├── ws_command_client.py  # MODIFY or DELETE: migrate to new envelope or remove
├── protocol.py           # MODIFY: encode/decode updated for envelope
└── __init__.py           # MODIFY: exports updated
```

---

## Implementation Phases

### Phase 1: Wire Envelope Pydantic Models

**Estimated effort**: 1 session

#### Context

RFC-450 §5 defines the unified `{proto, type, method, params, id}` envelope. The envelope models must be defined in the SDK (`soothe_sdk.wire` or `soothe_sdk.client.wire`) so both daemon and CLI share them without circular imports. The current `wire.py` only contains LangChain message normalization — it needs envelope models added.

#### Tasks

1. **Define envelope base models**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/wire.py`
   - Add `BaseEnvelope` Pydantic model with `proto: str = "1"` and `type: str`
   - Add `RequestEnvelope` with `method: str`, `params: dict[str, Any]`, `id: str | None`
   - Add `ResponseEnvelope` with `result: dict[str, Any] | None`, `id: str | None`
   - Add `NotificationEnvelope` with `method: str`, `params: dict[str, Any]`, `receipt: str | None`
   - Add `SubscribeEnvelope` with `method: str`, `params: dict[str, Any]`, `id: str`
   - Add `NextEnvelope` with `id: str`, `payload: dict[str, Any]`
   - Add `ErrorEnvelope` with `error: dict[str, int, str, Any]`, `id: str | None`
   - Add `CompleteEnvelope` with `id: str`
   - Add `UnsubscribeEnvelope` with `id: str`
   - Add `ConnectionInitEnvelope` with `params: ConnectionInitParams`
   - Add `ConnectionAckEnvelope` with `result: ConnectionAckResult`
   - Add `PingEnvelope`, `PongEnvelope`, `DisconnectEnvelope`, `ReceiptResponseEnvelope`
   - Use `Literal` types to constrain `type` field values per RFC-450 §9.1

2. **Define `MessageType` enum**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/wire.py`
   - `MessageType` string enum: `CONNECTION_INIT`, `CONNECTION_ACK`, `REQUEST`, `RESPONSE`, `NOTIFICATION`, `SUBSCRIBE`, `NEXT`, `ERROR`, `COMPLETE`, `UNSUBSCRIBE`, `PING`, `PONG`, `RECEIPT_RESPONSE`, `DISCONNECT`
   - Values match RFC-450 §5.2 type field strings

3. **Define `ConnectionInitParams` and `ConnectionAckResult`**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/wire.py`
   - `ConnectionInitParams`: `client_version: str`, `client_name: str | None`, `accept_proto: list[str]`, `capabilities: list[str]`
   - `ConnectionAckResult`: `server_version: str`, `protocol_version: str`, `capabilities: list[str]`, `readiness_state: str`, `heartbeat_interval_ms: int = 30000`

4. **Add envelope encode/decode helpers**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/wire.py`
   - `encode_envelope(envelope: BaseModel) -> str` — serialize to JSON text for WebSocket text frame
   - `decode_envelope(text: str) -> dict[str, Any] | None` — parse JSON, return raw dict (validation happens separately)
   - Re-export from `protocol.py` for backward compat

5. **Update SDK `__init__.py` exports**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/__init__.py`
   - Export envelope models, `MessageType` enum, encode/decode helpers

#### Tests

- `packages/soothe-sdk/tests/unit/client/test_wire_envelope.py`
  - Test each envelope model validates correctly with valid input
  - Test envelope rejects missing `proto` or `type`
  - Test `RequestEnvelope` without `id` is valid (notification semantics)
  - Test `ErrorEnvelope` requires `code` and `message` in `error` dict
  - Test `encode_envelope` / `decode_envelope` round-trip

---

### Phase 2: ErrorCode IntEnum Registry

**Estimated effort**: 0.5 session

#### Context

RFC-450 §7.3 defines a numeric error code scheme with reserved ranges. The current `validation.py` uses string error codes (`"INVALID_MESSAGE"`, `"RATE_LIMITED"`, etc.). The new `ErrorCode` IntEnum replaces these with JSON-RPC 2.0-style numeric codes.

#### Tasks

1. **Create `error_codes.py`**
   - Location: `packages/soothe-daemon/src/soothe_daemon/protocol/error_codes.py`
   - Define `ErrorCode(IntEnum)` with all 37 codes per RFC-450 §7.3:

   ```python
   class ErrorCode(IntEnum):
       # Protocol-level (-32768 to -32000)
       PARSE_ERROR = -32700
       INVALID_REQUEST = -32600
       METHOD_NOT_FOUND = -32601
       INVALID_PARAMS = -32602
       INTERNAL_ERROR = -32603

       # Server state (-32000 to -32099)
       RATE_LIMITED = -32000
       DAEMON_STARTING = -32001
       DAEMON_BUSY = -32002
       DAEMON_DEGRADED = -32003
       DAEMON_ERROR = -32004

       # Authorization/session (-32100 to -32199)
       NO_LOOP_SUBSCRIPTION = -32100
       LOOP_NOT_SUBSCRIBED = -32101
       NO_SESSION = -32102
       AUTH_FAILED = -32103
       AUTH_EXPIRED = -32104

       # Resource not found (-32200 to -32299)
       LOOP_NOT_FOUND = -32200
       JOB_NOT_FOUND = -32201
       GOAL_NOT_FOUND = -32202
       SKILL_NOT_FOUND = -32203

       # State conflicts (-32300 to -32399)
       JOB_ALREADY_PAUSED = -32300
       JOB_NOT_PAUSED = -32301
       JOB_COMPLETED = -32302
       LOOP_ALREADY_ACTIVE = -32303

       # Operation failures (-32400 to -32499)
       SKILL_LOAD_FAILED = -32400
       RUNNER_UNAVAILABLE = -32401
       AUTOPILOT_NOT_READY = -32402
       CARD_MANAGER_UNAVAILABLE = -32403
       CARDS_FETCH_FAILED = -32404
       LOOP_CONTEXT_ERROR = -32405
       LOOP_STATE_ERROR = -32406
       WORKSPACE_RESOLUTION_FAILED = -32407

       # Job operation failures (-32500 to -32599)
       JOB_CREATE_FAILED = -32500
       JOB_PAUSE_FAILED = -32501
       JOB_RESUME_FAILED = -32502
       JOB_CANCEL_FAILED = -32503
       LOOP_REATTACH_FAILED = -32504
   ```

2. **Create `errors.py` with `ProtocolError` helper**
   - Location: `packages/soothe-daemon/src/soothe_daemon/protocol/errors.py`
   - `ProtocolError(Exception)` with `code: ErrorCode`, `message: str`, `data: dict`, `severity: str`
   - `to_envelope(request_id=None) -> dict` — builds wire-ready error message per RFC-450 §7.1
   - Convenience constructors: `loop_not_found(loop_id)`, `invalid_params(field, reason)`, `method_not_found(method)`, `daemon_not_ready(state)`, `internal_error(detail)`

3. **Migrate from old string codes**
   - Location: `packages/soothe-daemon/src/soothe_daemon/protocol/validation.py`
   - Remove old `ERROR_INVALID_MESSAGE`, `ERROR_INVALID_JSON`, etc. constants
   - Remove old `ProtocolError` class (string-based) — replaced by `errors.py` `ProtocolError` (numeric)
   - Remove old `create_error_response(code: str, ...)` — replaced by `ProtocolError.to_envelope()`
   - Update `protocol/__init__.py` exports

4. **Share error codes with SDK**
   - The `ErrorCode` IntEnum and `ProtocolError` should be importable by the SDK for client-side error handling
   - Option A: Define in `soothe_sdk.client.wire` and import in daemon (SDK has no daemon dependency)
   - Option B: Duplicate in daemon with a comment noting the SDK is the source of truth
   - **Recommended**: Option A — define in SDK, daemon imports from SDK (daemon already depends on SDK)

#### Tests

- `packages/soothe-daemon/tests/unit/protocol/test_error_codes.py`
  - Test all 37 codes have correct numeric values per RFC-450 §7.3
  - Test `ProtocolError.to_envelope()` produces correct `{proto, type, error: {code, message, data}, id}` structure
  - Test convenience constructors produce correct codes
  - Test `to_envelope()` omits `data` when empty, omits `id` when `request_id` is None

---

### Phase 3: Connection Handshake (connection_init / connection_ack)

**Estimated effort**: 1-2 sessions

#### Context

RFC-450 §8.2 defines a bidirectional handshake replacing the current one-directional `daemon_ready` flow. Currently:
- **Daemon side** (`server/core.py:667`): `daemon_ready_message()` returns `{"type": "daemon_ready", "state": ..., "message": ...}`
- **Daemon side** (`server/core.py:675`): `_get_handshake_messages()` sends `[status_msg, daemon_ready_msg]` on connect
- **SDK side** (`client/websocket.py:918`): `request_daemon_ready()` sends `{"type": "daemon_ready"}`
- **SDK side** (`client/websocket.py:938`): `wait_for_daemon_ready()` waits for `type == "daemon_ready"` with `state == "ready"`

The new handshake: client sends `connection_init` with `accept_proto: ["1"]` and capabilities; daemon responds with `connection_ack` including `readiness_state`, `protocol_version`, and negotiated capabilities.

#### Tasks

1. **Daemon: Implement `connection_init` handler**
   - Location: `packages/soothe-daemon/src/soothe_daemon/protocol/router.py`
   - Add `_handle_connection_init(client_id, msg)` method
   - Parse `ConnectionInitParams` from `msg["params"]`
   - Negotiate protocol version: pick highest from `accept_proto` that daemon supports (currently only `"1"`)
   - Negotiate capabilities: intersect client `capabilities` with daemon-supported (`["streaming", "batch", "receipts", "heartbeat"]`)
   - Build `connection_ack` response with `ConnectionAckResult`: `server_version`, `protocol_version: "1"`, negotiated `capabilities`, `readiness_state` from daemon state, `heartbeat_interval_ms: 30000`
   - If no compatible proto version: respond with `readiness_state: "incompatible"` and close connection with code 1001
   - Store negotiated capabilities on the client session for later enforcement

2. **Daemon: Replace `daemon_ready_message()` and `_get_handshake_messages()`**
   - Location: `packages/soothe-daemon/src/soothe_daemon/server/core.py`
   - Remove `daemon_ready_message()` method (replaced by `connection_ack`)
   - Modify `_get_handshake_messages()` to NOT send `daemon_ready` automatically — the handshake is now client-initiated
   - The daemon waits for `connection_init` before sending `connection_ack`
   - Messages received before `connection_init` → reject with `-32600 INVALID_REQUEST` ("handshake must complete first")

3. **Daemon: Track handshake state per connection**
   - Location: `packages/soothe-daemon/src/soothe_daemon/server/core.py` (or `ClientSession`)
   - Add `handshake_complete: bool` flag to client session
   - Router checks `handshake_complete` before dispatching any non-`connection_init` message
   - If `handshake_complete is False` and `msg_type != "connection_init"` → send error `-32600`

4. **Daemon: WebSocket channel handshake enforcement**
   - Location: `packages/soothe-daemon/src/soothe_daemon/channels/websocket.py`
   - In `_handle_client_endpoint()`, after WebSocket upgrade, wait for `connection_init` as first message
   - If first message is not `connection_init` → send error and close
   - After `connection_ack` sent, mark session as handshake-complete and proceed to normal message loop

5. **SDK: Implement `connection_init` / `connection_ack` in `WebSocketClient`**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`
   - Replace `request_daemon_ready()` with `request_connection_init()` — sends `connection_init` with `client_version`, `accept_proto: ["1"]`, `capabilities: ["streaming", "batch", "receipts"]`
   - Replace `wait_for_daemon_ready()` with `wait_for_connection_ack()` — waits for `type == "connection_ack"`, checks `readiness_state == "ready"`, stores negotiated capabilities
   - Handle `readiness_state == "incompatible"` → raise `ConnectionError` with clear message
   - Handle transitional states (`starting`, `warming`) → bounded retry re-sending `connection_init`
   - Handle `degraded` / `error` → raise `RuntimeError` with message

6. **SDK: Store negotiated capabilities**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`
   - Add `self._negotiated_capabilities: set[str]` and `self._protocol_version: str`
   - `wait_for_connection_ack()` populates these from the `connection_ack` result
   - Batch support: only send arrays if `"batch" in self._negotiated_capabilities`
   - Receipt support: only include `receipt` field if `"receipts" in self._negotiated_capabilities`

7. **SDK: Heartbeat (ping/pong)**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`
   - Add optional `ping` sender task if `"heartbeat" in negotiated_capabilities`
   - Respond to incoming `ping` with `pong` within `heartbeat_timeout_ms`
   - If no `pong` within timeout → consider connection dead, close

#### Tests

- `packages/soothe-daemon/tests/unit/protocol/test_connection_handshake.py`
  - Test `connection_init` with valid params → `connection_ack` with `readiness_state: "ready"`
  - Test `connection_init` with unsupported `accept_proto` → `readiness_state: "incompatible"`
  - Test message before `connection_init` → `-32600 INVALID_REQUEST`
  - Test capability intersection (client declares `["streaming"]` → server echoes `["streaming"]` only)
- `packages/soothe-sdk/tests/unit/client/test_websocket_handshake.py`
  - Test `request_connection_init()` sends correct envelope
  - Test `wait_for_connection_ack()` returns on `ready`, raises on `error`/`degraded`, retries on `starting`
  - Test `incompatible` state raises `ConnectionError`
- `packages/soothe-daemon/tests/integration/daemon/test_daemon_websocket_protocol.py`
  - End-to-end: client connects → handshakes → sends `loop_get` → gets response

---

### Phase 4: MessageRouter Refactor — Dispatch Table

**Estimated effort**: 1-2 sessions

#### Context

The current `MessageRouter.dispatch()` (`protocol/router.py:211`) is a 32-branch `if msg_type == "..."` chain spanning ~200 lines. Each branch calls a `_handle_*` method. The new design uses a `HANDLER_REGISTRY` dict mapping `(type, method)` tuples to handler callables, with validation happening before dispatch.

#### Tasks

1. **Build `HANDLER_REGISTRY` dispatch table**
   - Location: `packages/soothe-daemon/src/soothe_daemon/protocol/router.py`
   - Replace the `if msg_type == ...` chain with a class-level or instance-level dict:

   ```python
   # Maps (type, method) → handler method name
   HANDLER_REGISTRY: dict[tuple[str, str | None], str] = {
       ("connection_init", None): "_handle_connection_init",
       ("request", "loop_list"): "_handle_loop_list",
       ("request", "loop_get"): "_handle_loop_get",
       ("request", "loop_tree"): "_handle_loop_tree",
       ("request", "loop_prune"): "_handle_loop_prune",
       ("request", "loop_delete"): "_handle_loop_delete",
       ("request", "loop_new"): "_handle_loop_new",
       ("request", "loop_reattach"): "_handle_loop_reattach",
       ("request", "loop_input"): "_handle_loop_input",
       ("notification", "loop_input"): "_handle_loop_input",
       ("request", "loop_messages"): "_handle_loop_messages",
       ("request", "loop_state_get"): "_handle_loop_state_get",
       ("request", "loop_state_update"): "_handle_loop_state_update",
       ("request", "loop_cards_fetch"): "_handle_loop_cards_fetch",
       ("subscribe", "loop_events"): "_handle_loop_subscribe",
       ("unsubscribe", None): "_handle_loop_detach",
       ("request", "job_create"): "_handle_job_create",
       ("request", "job_status"): "_handle_job_status",
       ("request", "job_pause"): "_handle_job_pause",
       ("request", "job_resume"): "_handle_job_resume",
       ("request", "job_cancel"): "_handle_job_cancel",
       ("request", "job_dag"): "_handle_job_dag",
       ("request", "job_guidance"): "_handle_job_guidance",
       ("request", "daemon_status"): "_handle_daemon_status",
       ("request", "daemon_shutdown"): "_handle_daemon_shutdown",
       ("request", "config_get"): "_handle_config_get",
       ("request", "skills_list"): "_handle_skills_list",
       ("request", "models_list"): "_handle_models_list",
       ("request", "invoke_skill"): "_handle_invoke_skill",
       ("request", "mcp_status"): "_handle_mcp_status",
       ("request", "auth"): "_handle_auth",
       ("request", "auth_refresh"): "_handle_auth_refresh",
       ("request", "rpc_command"): "_handle_rpc_command",
       ("notification", "slash_command"): "_handle_slash_command",
       ("notification", "disconnect"): "_handle_disconnect",
       ("subscribe", "autopilot_events"): "_handle_autopilot_subscribe",
       ("unsubscribe", None): "_handle_autopilot_unsubscribe",  # disambiguate by stored sub id
       ("ping", None): "_handle_ping",
       ("request", "loop_detach"): "_handle_loop_detach",  # backward alias during migration
   }
   ```

2. **Rewrite `dispatch()` method**
   - Location: `packages/soothe-daemon/src/soothe_daemon/protocol/router.py`
   - New `dispatch()` logic:
     1. Set client_id in logging context
     2. Check `handshake_complete` — if not and type != `connection_init`, send `-32600`
     3. Look up handler in `HANDLER_REGISTRY` by `(msg_type, msg_method)`
     4. If not found → send `-32601 METHOD_NOT_FOUND` error
     5. Get handler method by name: `getattr(self, handler_name)`
     6. Call `await handler(client_id, msg)` — handler receives pre-validated msg
     7. Catch `ProtocolError` → serialize via `to_envelope()` and send
   - Remove ALL `if msg_type == ...` branches

3. **Handle `unsubscribe` ambiguity**
   - `unsubscribe` uses only `id` (no `method`), so the registry key is `("unsubscribe", None)`
   - The handler looks up the subscription by `id` and cancels it (whether it's a `loop_events` or `autopilot_events` subscription)

4. **Update handler signatures**
   - All `_handle_*` methods currently receive raw `msg: dict[str, Any]`
   - After validation refactor (Phase 8), they will receive pre-validated params
   - For now, keep `msg` param but extract `params = msg.get("params", {})` consistently
   - Migrate from `msg.get("loop_id")` to `msg.get("params", {}).get("loop_id")` — params are nested in the new envelope

5. **Rename message types per RFC-450 §9.4**
   - `command` (slash) → `notification` + `method: "slash_command"` → `_handle_slash_command()`
   - `command_request` (RPC) → `request` + `method: "rpc_command"` → `_handle_rpc_command()`
   - `detach` → `notification` + `method: "disconnect"` → `_handle_disconnect()`
   - `loop_subscribe` → `subscribe` + `method: "loop_events"` → `_handle_loop_subscribe()` (lifecycle change)
   - `loop_detach` → `unsubscribe` (by `id`) → `_handle_loop_detach()`
   - `daemon_ready` → `connection_init` → `_handle_connection_init()`
   - `autopilot_subscribe` → `subscribe` + `method: "autopilot_events"` → `_handle_autopilot_subscribe()`
   - `autopilot_unsubscribe` → `unsubscribe` (by `id`)

6. **Remove `_SKIP_PER_MESSAGE_DEBUG_TYPES`**
   - Location: `packages/soothe-daemon/src/soothe_daemon/protocol/router.py`
   - The old set `{"daemon_ready", "daemon_status"}` is no longer needed — `connection_init` is infrequent, and debug logging can use `(type, method)` tuple

7. **Update response format in handlers**
   - All handlers currently send `{"type": "loop_get_response", "request_id": ...}` 
   - Change to `{"proto": "1", "type": "response", "result": {...}, "id": msg.get("id")}`
   - Eliminate `{type}_response` suffix pattern per RFC-450 §10.2
   - This is a mechanical change across all ~30 handler methods

#### Tests

- `packages/soothe-daemon/tests/unit/protocol/test_router_dispatch.py`
  - Test each `(type, method)` in `HANDLER_REGISTRY` dispatches to correct handler
  - Test unknown method → `-32601 METHOD_NOT_FOUND`
  - Test message before handshake → `-32600 INVALID_REQUEST`
  - Test `ProtocolError` raised in handler → serialized as error envelope
- `packages/soothe-daemon/tests/unit/protocol/test_router_no_if_chain.py`
  - Static analysis test: assert `dispatch()` method source contains no `if msg_type ==` (enforces dispatch table usage)

---

### Phase 5: WebSocketClient SDK Refactor

**Estimated effort**: 1-2 sessions

#### Context

The current `WebSocketClient` (`client/websocket.py`, 1102 lines) uses the old wire format:
- `request_response()` (line 723) correlates by `request_id` and waits for `{type}_response`
- `request_daemon_ready()` (line 918) sends `{"type": "daemon_ready"}`
- `send()` sends flat dicts with `type` at top level
- No envelope structure, no `proto` field, no `method`/`params` separation

The refactor introduces blocking (`request` with `id`) and non-blocking (`notify` without `id`) semantics per RFC-450 §5.

#### Tasks

1. **Add `request()` method (blocking RPC)**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`
   - `async def request(method, params, *, timeout=5.0) -> dict[str, Any]`
   - Generates `id` (UUID hex), sends `{"proto": "1", "type": "request", "method": method, "params": params, "id": id}`
   - Waits for `type == "response"` with matching `id`
   - On `type == "error"` with matching `id` → raise `ProtocolError` from the error envelope
   - On timeout → `TimeoutError`

2. **Add `notify()` method (non-blocking notification)**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`
   - `async def notify(method, params, *, receipt=None) -> None`
   - Sends `{"proto": "1", "type": "notification", "method": method, "params": params}` (no `id`)
   - If `receipt` is provided and `"receipts"` in negotiated capabilities → include `receipt` field, wait for `receipt_response`
   - Fire-and-forget: does not wait for response (unless receipt requested)

3. **Add `subscribe()` method**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`
   - `async def subscribe(method, params, *, timeout=5.0) -> str`
   - Sends `{"proto": "1", "type": "subscribe", "method": method, "params": params, "id": id}`
   - Returns the subscription `id` for later `unsubscribe()` and event correlation
   - Does NOT wait for a response — subscription confirmation is implicit; errors arrive as `type == "error"` with matching `id`

4. **Add `unsubscribe()` method**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`
   - `async def unsubscribe(subscription_id) -> None`
   - Sends `{"proto": "1", "type": "unsubscribe", "id": subscription_id}`

5. **Update `read_event()` for new envelope**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`
   - Events now arrive as `{"proto": "1", "type": "next", "id": sub_id, "payload": {...}}`
   - `read_event()` should return the `payload` for `next` messages, or the full envelope for `response`/`error`/`complete`
   - Route `response` and `error` messages to pending `request()` waiters by `id`
   - Route `next` messages to the consumer via `read_event()` or a subscription callback

6. **Replace `request_response()` with `request()`**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`
   - Deprecate `request_response(payload, response_type=..., timeout=...)` 
   - Replace all internal calls (e.g., `list_skills()`, `list_models()`, `invoke_skill()`) to use `request("skills_list", {})` etc.
   - Keep `request_response()` as a thin shim during migration if needed, but prefer clean replacement

7. **Replace `request_daemon_ready()` / `wait_for_daemon_ready()`**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`
   - Replace with `request_connection_init()` / `wait_for_connection_ack()` (from Phase 3)
   - Remove `_TRANSITIONAL_DAEMON_READY_STATES` and `_DAEMON_READY_POLL_INTERVAL_S` constants (replaced by connection_ack retry logic)

8. **Update `send()` to use envelope**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`
   - `send()` currently sends raw dicts; update to accept envelope models or wrap raw dicts in envelope structure
   - Add `send_envelope(envelope: BaseModel) -> None` for typed sending

9. **Update `send_command()` and `send_detach()`**
   - `send_command(cmd)` → `notify("slash_command", {"cmd": cmd})`
   - `send_detach()` → `notify("disconnect", {})`

10. **Update `send_loop_input()`**
    - Currently sends `{"type": "loop_input", "loop_id": ..., "content": ...}` (flat)
    - Change to `notify("loop_input", {"loop_id": ..., "content": ...})` (nested params)

#### Tests

- `packages/soothe-sdk/tests/unit/client/test_websocket_request.py`
  - Test `request()` sends correct envelope and waits for matching `response`
  - Test `request()` raises `ProtocolError` on `error` response
  - Test `request()` raises `TimeoutError` on timeout
- `packages/soothe-sdk/tests/unit/client/test_websocket_notify.py`
  - Test `notify()` sends without `id`, does not wait
  - Test `notify()` with `receipt` waits for `receipt_response`
- `packages/soothe-sdk/tests/unit/client/test_websocket_subscribe.py`
  - Test `subscribe()` returns subscription `id`
  - Test `unsubscribe()` sends correct envelope
- `packages/soothe-sdk/tests/unit/client/test_websocket_event_routing.py`
  - Test `next` events routed to subscription consumer
  - Test `response`/`error` events routed to `request()` waiter by `id`

---

### Phase 6: WsCommandClient Migration or Removal

**Estimated effort**: 0.5-1 session

#### Context

`WsCommandClient` (`client/ws_command_client.py`, 380 lines) was created in IG-504 to replace HTTP REST clients for autopilot/cron/memory commands. It uses the old wire format: `{"type": "command", "command": command_type, "request_id": ..., "payload": ...}`. Under RFC-450, these become `rpc_command` requests: `{"proto": "1", "type": "request", "method": "rpc_command", "params": {"command": ..., "payload": ...}, "id": ...}`.

#### Tasks

1. **Migrate `WsCommandClient._send_command()` to new envelope**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/ws_command_client.py`
   - Change message format from `{"type": "command", "command": ..., "request_id": ..., "payload": ...}` to `{"proto": "1", "type": "request", "method": "rpc_command", "params": {"command": ..., "payload": ...}, "id": ...}`
   - Update response matching: wait for `type == "response"` with matching `id` (not `type == "command_response"` with `request_id`)

2. **Add `connection_init` handshake to `WsCommandClient`**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/ws_command_client.py`
   - Currently connects, sends command, disconnects — no handshake
   - Must now send `connection_init` and wait for `connection_ack` before sending `rpc_command`
   - Add `_handshake(ws)` helper that sends `connection_init` and waits for `connection_ack`

3. **Alternatively: Remove `WsCommandClient` and use `WebSocketClient.request()`**
   - If `WsCommandClient` is just a thin wrapper over WebSocket connect + request + disconnect, it can be replaced by:
     ```python
     client = WebSocketClient(url)
     await client.connect()
     await client.request_connection_init()
     await client.wait_for_connection_ack()
     result = await client.request("rpc_command", {"command": "autopilot_status", "payload": {}})
     await client.close()
     ```
   - **Recommended**: Migrate `WsCommandClient` to use `WebSocketClient` internally, reducing duplicate connection logic. Keep the convenience methods (`autopilot_status()`, `cron_add()`, etc.) but delegate to `WebSocketClient.request("rpc_command", ...)`.

4. **Update CLI command clients**
   - Location: `packages/soothe-cli/src/soothe_cli/cli/commands/autopilot_cmd.py`, `cron_cmd.py`
   - If `WsCommandClient` API stays the same, no CLI changes needed here
   - If `WsCommandClient` is removed, update CLI to use `WebSocketClient` directly

5. **Update daemon `rpc_command` handler**
   - Location: `packages/soothe-daemon/src/soothe_daemon/protocol/router.py`
   - Rename `_handle_command_request()` to `_handle_rpc_command()`
   - Extract params from `msg["params"]` instead of top-level `msg`

#### Tests

- `packages/soothe-sdk/tests/unit/client/test_ws_command_client.py`
  - Test `_send_command` sends new envelope format
  - Test handshake before command
  - Test response matching by `id`

---

### Phase 7: Session Bootstrap (bootstrap_loop_session) Update

**Estimated effort**: 1 session

#### Context

`bootstrap_loop_session()` (`client/session.py`, 167 lines) orchestrates: connect → `daemon_ready` handshake → `loop_new` / `loop_subscribe` → return `session_ready`. The handshake and RPC calls all use the old wire format.

Current flow:
1. `client.request_daemon_ready()` → sends `{"type": "daemon_ready"}`
2. `client.wait_for_daemon_ready()` → waits for `type == "daemon_ready"` with `state == "ready"`
3. `client.request_response({"type": "loop_new", ...}, response_type="loop_new_response")` 
4. `client.request_response({"type": "loop_subscribe", ...}, response_type="loop_subscribe_response")`

New flow per RFC-450:
1. `client.request_connection_init()` → sends `connection_init` envelope
2. `client.wait_for_connection_ack()` → waits for `connection_ack` with `readiness_state == "ready"`
3. `client.request("loop_new", {"workspace": ..., "user_id": ...})` → waits for `response`
4. `client.subscribe("loop_events", {"loop_id": ..., "stream_delivery": ...})` → returns subscription `id`

#### Tasks

1. **Replace daemon_ready handshake with connection_init/ack**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/session.py`
   - Replace `await client.request_daemon_ready()` with `await client.request_connection_init()`
   - Replace `await client.wait_for_daemon_ready(...)` with `await client.wait_for_connection_ack(...)`
   - Update timeout constant: `_DAEMON_READY_TIMEOUT_S` → `_CONNECTION_ACK_TIMEOUT_S`

2. **Replace `loop_new` request with new envelope**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/session.py`
   - Change from:
     ```python
     loop_new_payload = {"type": "loop_new", "client_workspace": workspace_str, ...}
     new_resp = await client.request_response(loop_new_payload, response_type="loop_new_response", ...)
     ```
   - To:
     ```python
     params = {"workspace": workspace_str, "user_id": user_id, ...}
     new_resp = await client.request("loop_new", params, timeout=subscribe_timeout_s)
     result = new_resp.get("result", {})
     loop_id = result.get("loop_id")
     ```
   - Note field rename: `client_workspace` → `workspace` per RFC-450 §10.1

3. **Replace `loop_subscribe` with `subscribe` + `loop_events`**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/session.py`
   - Change from:
     ```python
     sub_resp = await client.request_response(
         {"type": "loop_subscribe", "loop_id": loop_id, "stream_delivery": delivery},
         response_type="loop_subscribe_response", ...
     )
     ```
   - To:
     ```python
     sub_id = await client.subscribe(
         "loop_events",
         {"loop_id": loop_id, "stream_delivery": delivery, "wire_tier": "full"},
         timeout=subscribe_timeout_s,
     )
     ```
   - The subscription is confirmed implicitly — no `subscription_confirmed` response (RFC-450 §9.4)
   - If subscription fails (e.g., loop not found), an `error` message with the subscription `id` arrives

4. **Update response field access**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/session.py`
   - Old: `new_resp.get("loop_id")`, `new_resp.get("autopilot_mode")`, `new_resp.get("workspace_mapping")`
   - New: `new_resp.get("result", {}).get("loop_id")`, etc. — result data is nested in `result` field

5. **Update `connect_websocket_with_retries()`**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/session.py`
   - No structural change — still retries `client.connect()` — but `connect()` now includes the `connection_init`/`ack` handshake (or the handshake is done separately after connect)
   - **Decision**: Keep `connect()` as transport-only (WebSocket upgrade), do handshake in `bootstrap_loop_session()` via explicit `request_connection_init()` / `wait_for_connection_ack()` calls

#### Tests

- `packages/soothe-sdk/tests/unit/test_session_bootstrap.py`
  - Update to assert `connection_init` is sent (not `daemon_ready`)
  - Assert `loop_new` uses `request("loop_new", ...)` not `request_response({"type": "loop_new"}, ...)`
  - Assert `subscribe("loop_events", ...)` is used (not `request_response({"type": "loop_subscribe"}, ...)`)
  - Assert `workspace` field (not `client_workspace`)
- `packages/soothe-sdk/tests/unit/test_session_bootstrap_reconnect.py`
  - Update reconnect test to use new handshake

---

### Phase 8: Validation Layer (validation.py) — Pydantic Schema Validation

**Estimated effort**: 1-2 sessions

#### Context

The current `validation.py` (148 lines) does manual structural validation with `if msg_type == "command": if "cmd" not in msg: ...`. RFC-450 §6 requires Pydantic model validation at the transport boundary, with a `PARAMS_REGISTRY` mapping `(type, method)` → Pydantic params model. The validation function is called before router dispatch on all transport paths.

#### Tasks

1. **Create `schemas.py` with all params models**
   - Location: `packages/soothe-daemon/src/soothe_daemon/protocol/schemas.py`
   - Define Pydantic `BaseModel` for each method's params per RFC-450 §6.2:
     - `LoopGetParams`: `loop_id: str`, `verbose: bool = False`, `tree: bool = False`
     - `LoopListParams`: `status: str | None = None`, `limit: int | None = None`
     - `LoopTreeParams`: `loop_id: str`
     - `LoopPruneParams`: `loop_id: str`, `keep_latest: int = 1`
     - `LoopDeleteParams`: `loop_id: str`
     - `LoopNewParams`: `workspace: str | None`, `user_id: str | None`, `client_workspace_id: str | None`, `is_ephemeral: bool = False`
     - `LoopReattachParams`: `loop_id: str`
     - `LoopInputParams`: `loop_id: str`, `content: str | dict`, `autonomous: bool = False`, `max_iterations: int | None`, `preferred_subagent: str | None`, `model: str | None`, `model_params: dict | None`, `attachments: list | None`, `intent_hint: str | None`, `response_schema: dict | None`, `response_schema_name: str | None`, `response_schema_strict: bool | None`, `clarification_mode: str | None`, `clarification_answer: bool = False`, `clarification_answers: list[str] | None`
     - `LoopMessagesParams`: `loop_id: str`, `limit: int = 100`, `offset: int = 0`
     - `LoopStateGetParams`: `loop_id: str`, `keys: list[str] | None = None`
     - `LoopStateUpdateParams`: `loop_id: str`, `values: dict[str, Any]`
     - `LoopCardsFetchParams`: `loop_id: str`, `since: str | None = None`
     - `JobCreateParams`: `goal: str`, `workspace: str | None`, `user_id: str | None`, `autonomous: bool = False`, `max_iterations: int | None`, `guidance: str | None`, `intent_hint: str | None`
     - `JobStatusParams`: `job_id: str`
     - `JobPauseParams`: `job_id: str`
     - `JobResumeParams`: `job_id: str`
     - `JobCancelParams`: `job_id: str`
     - `JobDagParams`: `job_id: str`
     - `JobGuidanceParams`: `job_id: str`, `content: str`
     - `DaemonStatusParams`: (empty — no required fields)
     - `DaemonShutdownParams`: (empty)
     - `ConfigGetParams`: `section: str | None = None`
     - `SkillsListParams`: (empty)
     - `ModelsListParams`: (empty)
     - `InvokeSkillParams`: `skill: str`, `args: str = ""`, `clarification_mode: str | None = None`
     - `McpStatusParams`: (empty)
     - `AuthParams`: `access_key: str`, `secret_key: str`
     - `AuthRefreshParams`: `refresh_token: str`
     - `SubscribeParams`: `loop_id: str`, `stream_delivery: Literal["batch", "adaptive", "streaming"] = "adaptive"`, `wire_tier: Literal["full", "compact"] = "full"`
     - `AutopilotSubscribeParams`: (empty or optional filters)
     - `SlashCommandParams`: `cmd: str`
     - `RpcCommandParams`: `command: str`, `payload: dict[str, Any] = {}`
     - `ConnectionInitParams`: `client_version: str`, `client_name: str | None`, `accept_proto: list[str]`, `capabilities: list[str] = []`
     - `DisconnectParams`: (empty)

2. **Build `PARAMS_REGISTRY`**
   - Location: `packages/soothe-daemon/src/soothe_daemon/protocol/schemas.py`
   - Map `(type, method)` → params model class per RFC-450 §6.2 registry (see RFC for full mapping)
   - Include `("connection_init", None): ConnectionInitParams`
   - Include both `("notification", "loop_input")` and `("request", "loop_input")` → `LoopInputParams`

3. **Rewrite `validate_message()`**
   - Location: `packages/soothe-daemon/src/soothe_daemon/protocol/validation.py`
   - New logic per RFC-450 §6.3:
     1. Check `proto == "1"` → else return error
     2. Check `type` is present and in `VALID_TYPES` → else return error
     3. Look up schema in `PARAMS_REGISTRY` by `(type, method)` → else return `-32601 METHOD_NOT_FOUND`
     4. `schema.model_validate(params)` → on `ValidationError`, return field-level errors
     5. Return `[]` (empty = valid)
   - Return type: `list[str]` (error messages) for backward compat, or change to raise `ProtocolError` directly

4. **Define `VALID_TYPES` set**
   - Location: `packages/soothe-daemon/src/soothe_daemon/protocol/validation.py`
   - `VALID_TYPES = frozenset({"connection_init", "connection_ack", "request", "response", "notification", "subscribe", "next", "error", "complete", "unsubscribe", "ping", "pong", "receipt_response", "disconnect"})`

5. **Inject validation at transport boundary**
   - Location: `packages/soothe-daemon/src/soothe_daemon/channels/websocket.py`
   - In the message receive path, before calling `router.dispatch()`:
     ```python
     errors = validate_message(msg_dict)
     if errors:
         await ws.send_text(encode_websocket_text({
             "proto": "1", "type": "error",
             "error": {"code": -32602, "message": "Invalid params", "data": {"errors": errors}},
             "id": msg_dict.get("id"),
         }))
         return
     await router.dispatch(client_id, msg_dict)
     ```
   - Location: `packages/soothe-daemon/src/soothe_daemon/server/core.py`
   - In the asyncio dispatch path (if any non-WebSocket transport exists), add the same `validate_message()` call before `router.dispatch()`

6. **Add SDK-side validation (§6.5)**
   - Location: `packages/soothe-sdk/src/soothe_sdk/client/schemas.py` (or `wire.py`)
   - Define client-side envelope models that validate before sending:
     ```python
     class LoopInputRequest(BaseModel):
         proto: str = "1"
         type: Literal["notification"] = "notification"
         method: Literal["loop_input"] = "loop_input"
         params: LoopInputParams
         receipt: str | None = None
     ```
   - `WebSocketClient.request()` / `notify()` validate params against these models before sending

7. **Remove old manual validation**
   - Location: `packages/soothe-daemon/src/soothe_daemon/protocol/validation.py`
   - Remove all `if msg_type == "command": ...` branches
   - Remove old `ProtocolError` class (replaced by `errors.py`)
   - Remove old `create_error_response()` (replaced by `ProtocolError.to_envelope()`)
   - Remove old `ERROR_*` string constants

#### Tests

- `packages/soothe-daemon/tests/unit/protocol/test_validation.py`
  - Test valid message for each `(type, method)` pair in `PARAMS_REGISTRY` → `[]` errors
  - Test missing `proto` → error
  - Test invalid `type` → error
  - Test unknown `(type, method)` → `-32601` error
  - Test invalid params (missing required field, wrong type) → field-level errors
  - Test `validate_message_size()` still works (unchanged)
- `packages/soothe-daemon/tests/unit/protocol/test_schemas.py`
  - Test each params model validates correctly
  - Test field constraints (e.g., `loop_id: min_length=1`)
- `packages/soothe-sdk/tests/unit/client/test_client_side_validation.py`
  - Test SDK validates before sending (catches malformed messages client-side)

---

### Phase 9: CLI Updates for New Client API

**Estimated effort**: 1 session

#### Context

The CLI (`packages/soothe-cli`) uses `WebSocketClient` and `bootstrap_loop_session` from the SDK. The headless execution path (`cli/execution/daemon.py`) and TUI model (`tui/app/_model.py`) call SDK methods that are changing. The event processing loop reads `event.get("type")` and checks for old type names.

#### Tasks

1. **Update headless execution event processing**
   - Location: `packages/soothe-cli/src/soothe_cli/cli/execution/daemon.py`
   - Update `_is_loop_scoped_event()`: old types `{"status", "event"}` → new types `{"next", "response"}`
   - Update event type checks throughout the file: `event.get("type") == "status"` → `event.get("type") == "next"` (or `response`)
   - Update `client.send_command("/cancel")` → `client.notify("slash_command", {"cmd": "/cancel"})`
   - Update `client.send_detach()` → `client.notify("disconnect", {})`
   - Update `client.send_loop_input(...)` → `client.notify("loop_input", {...})` or `client.request("loop_input", {...})`

2. **Update TUI model**
   - Location: `packages/soothe-cli/src/soothe_cli/tui/app/_model.py`
   - Update all `client.request_response(...)` calls to `client.request(method, params)`
   - Update event type handling in the TUI event loop
   - Update `client.send_command()` → `client.notify("slash_command", {"cmd": cmd})`

3. **Update CLI runtime transport session**
   - Location: `packages/soothe-cli/src/soothe_cli/runtime/transport/session.py`
   - Update any `bootstrap_loop_session` usage — the function signature stays the same, but internal behavior changes
   - Update event type checks

4. **Update EventProcessor**
   - Location: `packages/soothe-cli/src/soothe_cli/runtime/` (EventProcessor and related)
   - Event types change: `event` → `next` (with `payload`), `status` → `next` or `response`
   - The `payload` field contains the event data (was previously flat in the event dict)

5. **Update CLI commands using WsCommandClient**
   - Location: `packages/soothe-cli/src/soothe_cli/cli/commands/autopilot_cmd.py`, `cron_cmd.py`
   - If `WsCommandClient` API is unchanged (Phase 6 migration keeps convenience methods), no changes needed
   - If `WsCommandClient` is removed, update to use `WebSocketClient.request("rpc_command", ...)` directly

6. **Update headless renderer**
   - Location: `packages/soothe-cli/src/soothe_cli/cli/execution/headless_renderer.py`
   - Update event type checks for rendering decisions

#### Tests

- `packages/soothe-cli/tests/unit/ux/cli/test_headless_cancel_on_sigint.py` — update for new cancel envelope
- `packages/soothe-cli/tests/unit/ux/cli/test_headless_daemon_thread_isolation.py` — update event types
- Manual testing: `soothe` headless mode against updated daemon
- Manual testing: `soothe` TUI mode against updated daemon

---

### Phase 10: Test Plan

**Estimated effort**: 1-2 sessions

#### Context

This phase covers comprehensive testing across wire format, handshake, error handling, and each message type. Tests span unit (daemon + SDK) and integration levels.

#### Test Categories

##### 10.1 Wire Format Tests

- **File**: `packages/soothe-sdk/tests/unit/client/test_wire_envelope.py`
  - Each envelope model validates with correct input
  - Envelope rejects missing `proto` or `type`
  - `RequestEnvelope` without `id` = notification semantics (valid)
  - `ErrorEnvelope` requires `code` and `message` in `error` dict
  - `encode_envelope()` / `decode_envelope()` round-trip preserves data
  - `proto` field is always `"1"`

- **File**: `packages/soothe-daemon/tests/unit/protocol/test_envelope_validation.py`
  - Message without `proto` → `-32600 INVALID_REQUEST`
  - Message with `proto: "2"` → rejected (clean break, no legacy)
  - Message with `proto: 1` (integer, not string) → rejected
  - Message without `type` → `-32600`
  - Message with unknown `type` → `-32600`

##### 10.2 Handshake Tests

- **File**: `packages/soothe-daemon/tests/unit/protocol/test_connection_handshake.py`
  - `connection_init` with valid params → `connection_ack` with `readiness_state: "ready"`
  - `connection_init` with `accept_proto: ["2"]` (unsupported) → `readiness_state: "incompatible"`
  - Message before `connection_init` → `-32600 INVALID_REQUEST`
  - Capability intersection: client `["streaming"]` + server `["streaming", "batch", "receipts", "heartbeat"]` → `["streaming"]`
  - `connection_ack` includes `server_version`, `protocol_version`, `heartbeat_interval_ms`

- **File**: `packages/soothe-sdk/tests/unit/client/test_websocket_handshake.py`
  - `request_connection_init()` sends correct envelope with `client_version`, `accept_proto: ["1"]`
  - `wait_for_connection_ack()` returns on `readiness_state: "ready"`
  - Raises `RuntimeError` on `readiness_state: "error"` or `"degraded"`
  - Raises `ConnectionError` on `readiness_state: "incompatible"`
  - Retries on `readiness_state: "starting"` / `"warming"` (bounded retry)
  - Timeout if no `connection_ack` received

- **File**: `packages/soothe-daemon/tests/integration/daemon/test_daemon_websocket_protocol.py`
  - End-to-end: connect → handshake → `loop_get` → `response` → disconnect
  - Old-format `daemon_ready` message → rejected with `-32600`

##### 10.3 Error Handling Tests

- **File**: `packages/soothe-daemon/tests/unit/protocol/test_error_codes.py`
  - All 37 `ErrorCode` values match RFC-450 §7.3 numeric codes
  - `ProtocolError.to_envelope()` produces `{proto, type: "error", error: {code, message, data}, id}`
  - `to_envelope()` omits `data` when empty
  - `to_envelope()` omits `id` when `request_id` is None
  - Convenience constructors: `loop_not_found("abc")` → code `-32200`, `invalid_params("field", "reason")` → code `-32602`

- **File**: `packages/soothe-daemon/tests/unit/protocol/test_error_handling.py`
  - Handler raises `ProtocolError` → router catches and serializes
  - Handler raises generic `Exception` → router wraps as `-32603 INTERNAL_ERROR`
  - Subscription error terminates stream (no further `next` events for that `id`)
  - Error echoes request `id` when present, omits when absent (notification)

##### 10.4 Message Type Tests (Per Method)

- **File**: `packages/soothe-daemon/tests/unit/protocol/test_message_types.py`
  - For each `(type, method)` in `PARAMS_REGISTRY`:
    - Valid params → dispatched to correct handler
    - Missing required field → `-32602 INVALID_PARAMS` with field name
    - Wrong type → `-32602 INVALID_PARAMS`
  - Cover all 37+ message types:
    - Loop RPC: `loop_list`, `loop_get`, `loop_tree`, `loop_prune`, `loop_delete`, `loop_new`, `loop_reattach`, `loop_input` (request + notification), `loop_messages`, `loop_state_get`, `loop_state_update`, `loop_cards_fetch`
    - Subscription: `loop_events` (subscribe), `autopilot_events` (subscribe), `unsubscribe`
    - Job RPC: `job_create`, `job_status`, `job_pause`, `job_resume`, `job_cancel`, `job_dag`, `job_guidance`
    - Daemon: `daemon_status`, `daemon_shutdown`, `config_get`
    - Skills/Models: `skills_list`, `invoke_skill`, `models_list`, `mcp_status`
    - Auth: `auth`, `auth_refresh`
    - Commands: `slash_command` (notification), `rpc_command` (request)
    - Connection: `connection_init`, `disconnect` (notification)

##### 10.5 Router Dispatch Table Tests

- **File**: `packages/soothe-daemon/tests/unit/protocol/test_router_dispatch.py`
  - Each `(type, method)` in `HANDLER_REGISTRY` dispatches to correct handler method
  - Unknown `(type, method)` → `-32601 METHOD_NOT_FOUND`
  - `HANDLER_REGISTRY` covers all methods in `PARAMS_REGISTRY` (no gaps)
  - `dispatch()` method has no `if msg_type ==` branches (static analysis)

##### 10.6 SDK Client Tests

- **File**: `packages/soothe-sdk/tests/unit/client/test_websocket_request.py`
  - `request()` sends `{"proto": "1", "type": "request", "method", "params", "id"}` and waits for `response`
  - `request()` raises `ProtocolError` on `error` response with matching `id`
  - `request()` raises `TimeoutError` on timeout

- **File**: `packages/soothe-sdk/tests/unit/client/test_websocket_notify.py`
  - `notify()` sends without `id`, returns immediately
  - `notify()` with `receipt` waits for `receipt_response`

- **File**: `packages/soothe-sdk/tests/unit/client/test_websocket_subscribe.py`
  - `subscribe()` returns subscription `id`
  - `unsubscribe()` sends `{"type": "unsubscribe", "id": sub_id}`
  - `next` events with matching `id` delivered to consumer

- **File**: `packages/soothe-sdk/tests/unit/test_session_bootstrap.py`
  - Bootstrap sends `connection_init` (not `daemon_ready`)
  - `loop_new` uses `request("loop_new", {"workspace": ...})` (not `request_response`)
  - `subscribe("loop_events", ...)` (not `request_response({"type": "loop_subscribe"})`)
  - `workspace` field (not `client_workspace`)

##### 10.7 Integration Tests

- **File**: `packages/soothe-daemon/tests/integration/daemon/test_daemon_websocket_protocol.py`
  - Full lifecycle: connect → handshake → `loop_new` → `subscribe` → `loop_input` → receive `next` events → `complete` → `disconnect`
  - Error path: `loop_get` with non-existent `loop_id` → `-32200 LOOP_NOT_FOUND`
  - Batch: array of requests → array of responses (if `batch` capability negotiated)
  - Receipt: `loop_input` with `receipt` → `receipt_response`

- **File**: `packages/soothe-daemon/tests/integration/daemon/test_daemon_event_protocol.py`
  - Stream events arrive as `{"type": "next", "id": sub_id, "payload": {...}}`
  - Stream termination: `{"type": "complete", "id": sub_id}`
  - `unsubscribe` cancels stream

- **File**: `packages/soothe-sdk/tests/integration/test_protocol_e2e.py` (new)
  - SDK client + daemon server: full protocol exchange
  - All RPC methods return correct response format
  - Heartbeat: `ping` → `pong`

##### 10.8 Migration Verification

- **File**: `packages/soothe-daemon/tests/unit/protocol/test_no_old_format.py`
  - Grep-based test: no `daemon_ready`, `command_request`, `loop_subscribe`, `loop_detach`, `autopilot_subscribe` string literals in router source
  - No `{type}_response` suffix patterns in daemon handlers
  - No `request_id` field in outbound messages (replaced by `id`)

---

## Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| RFC-450 | Draft | Single source of truth for protocol-1 wire contract |
| RFC-900 | Exists | Deprecation taxonomy (active/deprecated/removed) |
| Pydantic | Exists | Already used for config models, plan schemas |
| `soothe_sdk.client.protocol` | Exists | `encode`/`decode`/`encode_websocket_text` helpers (modify) |
| `soothe_daemon.protocol.validation` | Exists | Current manual validation (rewrite) |
| `soothe_daemon.protocol.router` | Exists | Current 32-branch dispatch (refactor) |
| `soothe_daemon.channels.websocket` | Exists | FastAPI WebSocket channel (modify) |
| `soothe_daemon.server.core` | Exists | Daemon core with `daemon_ready_message()` (modify) |
| `soothe_sdk.client.websocket` | Exists | 1102-line client (modify) |
| `soothe_sdk.client.session` | Exists | Bootstrap flow (modify) |
| `soothe_sdk.client.ws_command_client` | Exists | Old wire format command client (migrate) |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Clean break breaks all existing clients | Daemon + SDK updated simultaneously; old clients rejected at handshake with clear error |
| 32-branch refactor introduces dispatch bugs | Dispatch table test covers every `(type, method)` pair; static analysis test forbids `if msg_type ==` |
| Handler param extraction breaks (flat → nested params) | Mechanical migration with tests for each handler; validate before dispatch catches structural errors |
| `connection_init`/`ack` handshake race conditions | Bounded retry on transitional states; timeout on all waits; integration tests for cold start |
| `WsCommandClient` migration breaks CLI commands | Keep convenience method API; only change internal wire format; CLI tests cover command paths |
| Event type renames break TUI/headless rendering | Phase 9 updates all event type checks; manual TUI + headless testing |
| Pydantic validation rejects previously-accepted lenient input | Schema models use `min_length=1` for required fields, `None` defaults for optional; tests cover edge cases |
| Batch/receipt capabilities not negotiated correctly | Capability intersection tested; features gated on negotiated capability set |

---

## Files Changed

| File | Action | Phase |
|------|--------|-------|
| `packages/soothe-sdk/src/soothe_sdk/client/wire.py` | Modify (add envelope models, `MessageType` enum, encode/decode helpers) | 1 |
| `packages/soothe-sdk/src/soothe_sdk/client/__init__.py` | Modify (export envelope models) | 1 |
| `packages/soothe-daemon/src/soothe_daemon/protocol/error_codes.py` | Create (`ErrorCode` IntEnum) | 2 |
| `packages/soothe-daemon/src/soothe_daemon/protocol/errors.py` | Create (`ProtocolError`, convenience constructors) | 2 |
| `packages/soothe-daemon/src/soothe_daemon/protocol/__init__.py` | Modify (update exports) | 2 |
| `packages/soothe-daemon/src/soothe_daemon/server/core.py` | Modify (remove `daemon_ready_message()`, update `_get_handshake_messages()`, add handshake state tracking) | 3 |
| `packages/soothe-daemon/src/soothe_daemon/channels/websocket.py` | Modify (handshake enforcement, validation injection) | 3, 8 |
| `packages/soothe-sdk/src/soothe_sdk/client/websocket.py` | Modify (new envelope, `request`/`notify`/`subscribe`/`unsubscribe`, handshake, heartbeat) | 3, 5 |
| `packages/soothe-daemon/src/soothe_daemon/protocol/router.py` | Modify (dispatch table, rename handlers, update response format) | 4 |
| `packages/soothe-sdk/src/soothe_sdk/client/ws_command_client.py` | Modify or Delete (migrate to new envelope) | 6 |
| `packages/soothe-sdk/src/soothe_sdk/client/session.py` | Modify (bootstrap uses `connection_init`/`ack`, `request`, `subscribe`) | 7 |
| `packages/soothe-daemon/src/soothe_daemon/protocol/schemas.py` | Create (Pydantic params models, `PARAMS_REGISTRY`) | 8 |
| `packages/soothe-daemon/src/soothe_daemon/protocol/validation.py` | Rewrite (Pydantic-based `validate_message`) | 8 |
| `packages/soothe-sdk/src/soothe_sdk/client/schemas.py` | Modify (add client-side validation models) | 8 |
| `packages/soothe-sdk/src/soothe_sdk/client/protocol.py` | Modify (update encode/decode for envelope) | 1, 5 |
| `packages/soothe-cli/src/soothe_cli/cli/execution/daemon.py` | Modify (event types, client API calls) | 9 |
| `packages/soothe-cli/src/soothe_cli/tui/app/_model.py` | Modify (event types, client API calls) | 9 |
| `packages/soothe-cli/src/soothe_cli/runtime/transport/session.py` | Modify (event types) | 9 |
| `packages/soothe-cli/src/soothe_cli/cli/commands/autopilot_cmd.py` | Modify (if `WsCommandClient` removed) | 9 |
| `packages/soothe-cli/src/soothe_cli/cli/commands/cron_cmd.py` | Modify (if `WsCommandClient` removed) | 9 |
| `packages/soothe-daemon/tests/unit/protocol/test_error_codes.py` | Create | 2 |
| `packages/soothe-daemon/tests/unit/protocol/test_connection_handshake.py` | Create | 3 |
| `packages/soothe-daemon/tests/unit/protocol/test_router_dispatch.py` | Create | 4 |
| `packages/soothe-daemon/tests/unit/protocol/test_router_no_if_chain.py` | Create | 4 |
| `packages/soothe-daemon/tests/unit/protocol/test_schemas.py` | Create | 8 |
| `packages/soothe-daemon/tests/unit/protocol/test_validation.py` | Create (or update existing) | 8 |
| `packages/soothe-daemon/tests/unit/protocol/test_envelope_validation.py` | Create | 10 |
| `packages/soothe-daemon/tests/unit/protocol/test_error_handling.py` | Create | 10 |
| `packages/soothe-daemon/tests/unit/protocol/test_message_types.py` | Create | 10 |
| `packages/soothe-daemon/tests/unit/protocol/test_no_old_format.py` | Create | 10 |
| `packages/soothe-sdk/tests/unit/client/test_wire_envelope.py` | Create | 1 |
| `packages/soothe-sdk/tests/unit/client/test_websocket_handshake.py` | Create | 3 |
| `packages/soothe-sdk/tests/unit/client/test_websocket_request.py` | Create | 5 |
| `packages/soothe-sdk/tests/unit/client/test_websocket_notify.py` | Create | 5 |
| `packages/soothe-sdk/tests/unit/client/test_websocket_subscribe.py` | Create | 5 |
| `packages/soothe-sdk/tests/unit/client/test_websocket_event_routing.py` | Create | 5 |
| `packages/soothe-sdk/tests/unit/client/test_client_side_validation.py` | Create | 8 |
| `packages/soothe-sdk/tests/unit/test_session_bootstrap.py` | Modify (update for new handshake/RPC) | 7 |
| `packages/soothe-sdk/tests/unit/test_session_bootstrap_reconnect.py` | Modify | 7 |
| `packages/soothe-daemon/tests/integration/daemon/test_daemon_websocket_protocol.py` | Modify (update for protocol-1) | 10 |
| `packages/soothe-daemon/tests/integration/daemon/test_daemon_event_protocol.py` | Modify | 10 |
| `packages/soothe-sdk/tests/integration/test_protocol_e2e.py` | Create | 10 |

---

## Verification Checklist

Before marking complete:

- [ ] Phase 1: Envelope models defined in `soothe_sdk.client.wire`, exported from `__init__.py`
- [ ] Phase 2: `ErrorCode` IntEnum with all 37 codes in `protocol/error_codes.py`; `ProtocolError` in `protocol/errors.py`
- [ ] Phase 3: `connection_init`/`connection_ack` handshake in daemon router + SDK client; old `daemon_ready` removed
- [ ] Phase 4: `MessageRouter.dispatch()` uses `HANDLER_REGISTRY` table; no `if msg_type ==` branches
- [ ] Phase 5: `WebSocketClient` has `request()`, `notify()`, `subscribe()`, `unsubscribe()`; old `request_response()` removed or shimmed
- [ ] Phase 6: `WsCommandClient` uses new envelope or removed; CLI commands work
- [ ] Phase 7: `bootstrap_loop_session` uses `connection_init`/`ack` + `request` + `subscribe`
- [ ] Phase 8: `validate_message()` uses `PARAMS_REGISTRY` + Pydantic; validation injected at transport boundary
- [ ] Phase 9: CLI headless + TUI event type checks updated; `send_command` → `notify("slash_command", ...)`
- [ ] Phase 10: All test categories pass
- [ ] `./scripts/verify_finally.sh` passes (zero lint errors, all tests pass)
- [ ] Manual test: `soothe` headless against updated daemon
- [ ] Manual test: `soothe` TUI against updated daemon
- [ ] No old wire format strings (`daemon_ready`, `command_request`, `loop_subscribe`, `loop_detach`, `autopilot_subscribe`, `{type}_response`, `request_id`) in runtime code
