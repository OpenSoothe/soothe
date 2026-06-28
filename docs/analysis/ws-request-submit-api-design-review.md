# WebSocket Request-Submit API Design Review

**Date**: 2026-06-28
**Scope**: Focused design review and polish of the WebSocket request-submit APIs (daemon communication protocol, RFC-450 family).
**Coverage**: Argument naming, schema validation, error response consistency, API ergonomics, documentation gaps, versioning, and concrete polishing recommendations.

---

## 1. Argument Naming Consistency

### 1.1 `loop_id` vs `thread_id` — RFC-450 Doc/Code Mismatch

The codebase has converged on `loop_id` as the wire-level identifier for all client-facing messages, but **RFC-450 still documents `thread_id`** for several message types. This is a documentation hazard for any new client implementer.

**Evidence**:
- `QueryEngine._loop_scoped_client_message()` (`query/engine.py:259-264`) explicitly strips `thread_id` and injects `loop_id`:
  ```python
  out["loop_id"] = str(loop_id).strip()
  out.pop("thread_id", None)  # never expose CoreAgent thread_id
  ```
- `subscription_confirmed` message (`protocol/router.py:1237-1240`) uses `loop_id`, but RFC-450 §Server→Client says `thread_id (req)`.
- `status` message (`protocol/router.py:233,308`; `server/handlers.py:189,283`) uses `loop_id` or omits it, but RFC-450 says `thread_id (req)`.
- `event` message (`query/engine.py:335-340`) uses `loop_id`, but RFC-450 says `thread_id (req)`.

**Internal naming is correct** — the docstring at `commands.py:7-10` explicitly states: *"Wire / clients: `loop_id` (StrangeLoop subscription scope)."* The code consistently uses `thread_id` only for internal LangGraph checkpoint keys (`checkpoint_thread_id`), never on the wire.

**Severity**: Medium (doc/code mismatch, not a runtime bug).

### 1.2 `workspace` vs `client_workspace` — Inconsistent Aliases

`loop_new` accepts both `client_workspace` and `workspace` as aliases:
```python
# router.py:1348
raw_workspace = msg.get("client_workspace") or msg.get("workspace")
```
But `job_create` uses only `workspace`:
```python
# router.py:2035
raw_workspace = msg.get("workspace")
```
The SDK client `send_loop_new()` (`websocket.py:565-599`) documents `workspace` as a "deprecated alias for `client_workspace`", but `job_create` has no such deprecation note — it uses `workspace` as the primary name.

**Severity**: Low (both work, but naming is inconsistent across RPC families).

### 1.3 `user_id` vs `user` — Silent Alias

`loop_new` accepts both:
```python
# router.py:1366
raw_user = msg.get("user_id") or msg.get("user")  # Support both field names
```
No deprecation comment, no documentation. The SDK only sends `user_id` (`websocket.py:592`), so `user` is an undocumented alias.

**Severity**: Low.

### 1.4 `content` vs `text` — Dual Field Names for Input

The `loop_input` message uses `content` as the primary field, but the internal queue payload uses `text`:
```python
# router.py:1486 — reads "content"
prompt_text = _coerce_loop_input_text(msg.get("content"))

# router.py:1637-1638 — queues "text"
queue_payload = {"type": "input", "text": text_for_queue, ...}
```
The `_coerce_loop_input_text()` helper (`router.py:170`) also accepts `text`, `prompt`, `message`, `input` as fallback keys within a dict-shaped `content`. This is defensive but undocumented.

Meanwhile, `job_guidance` uses `text` directly:
```python
# router.py:2486
text = msg.get("text")
```

So the wire protocol has two different field names for "user text input" depending on the message type: `content` for `loop_input`, `text` for `job_guidance`.

**Severity**: Medium (confusing for client implementers).

### 1.5 `cmd` vs `command` — Two Different `type: "command"` Messages

This is the most dangerous naming collision. Two completely different message formats share `type: "command"`:

**Path A — Slash commands** (TUI/CLI via `WebSocketClient.send_command()`):
```python
# SDK websocket.py:378
{"type": "command", "cmd": "/exit"}
```
Validated in `validation.py:66-70` (checks `cmd` field).

**Path B — RPC commands** (headless CLI via `WsCommandClient._send_command()`):
```python
# SDK ws_command_client.py:88-93
{"type": "command", "command": "autopilot_status", "request_id": "cmd_1", "payload": {}}
```
Not validated in `validation.py` at all. Handled by a separate dispatch path in `channels/websocket.py:471-473` (`_handle_command_message`).

The `validation.py` validator checks for `cmd` on `command` messages. If a `WsCommandClient` message (with `command` not `cmd`) passes through `validate_message`, it would be flagged as invalid — but it may not pass through that path (the FastAPI WebSocket channel has a separate handler).

**Severity**: High (silent collision, two dispatch paths, potential for messages routed to the wrong handler).

---

## 2. Required vs Optional Field Semantics & Schema Validation

### 2.1 Validation Coverage Gap — Only 6 of 37 Message Types Validated

`validation.py:validate_message()` only validates these message types:
- `command` (checks `cmd`)
- `daemon_ready`
- `detach`
- `skills_list`
- `models_list`
- `invoke_skill`

**31 out of 37 message types have no structural validation** in `validate_message()`. They fall through to the `else` branch (`validation.py:98-101`) which logs a warning and allows the message through.

The handlers do perform **inline ad-hoc validation** (e.g., `router.py:865` checks `loop_id` presence, `router.py:2021` checks `goal` is a non-empty string), but this is:
1. Repetitive — the same `if not loop_id:` pattern is duplicated across ~15 handlers.
2. Inconsistent — some check `isinstance(job_id, str)`, others just `if not loop_id`.
3. Not centralized — no single schema definition to reference.

### 2.2 `validate_message` Only Called on FastAPI WebSocket Path

`validate_message` is called in `channels/websocket.py:447` (FastAPI WebSocket path). It is **NOT called** in:
- `server/handlers.py:137` — legacy TCP `_handle_client` path
- `server/core.py:1466` — main asyncio dispatch path (`_dispatch_with_semaphore`)

This means clients connecting via the asyncio TCP transport bypass all structural validation.

**Severity**: Medium (the TCP path is legacy but still active).

### 2.3 No Pydantic Models for Wire Messages

The SDK defines Pydantic models in `schemas.py` (`PlanStep`, `Plan`, `ToolOutput`), but these are for sub-structures, not for top-level wire messages. There are **no Pydantic models** for any of the 37 client→server message types. All validation is manual `isinstance`/`msg.get()` checks.

This means:
- No automatic type coercion or validation error messages.
- No schema documentation from model definitions.
- No `model_dump()` for consistent serialization.

**Severity**: Medium (works, but fragile and hard to maintain as the API grows).

### 2.4 Required Field Enforcement is Inconsistent

Examples of inconsistency:

| Handler | Field | Check | Line |
|---------|-------|-------|------|
| `_handle_loop_get` | `loop_id` | `if not loop_id:` (truthy, not type-checked) | `router.py:865` |
| `_handle_job_status` | `job_id` | `if not isinstance(job_id, str) or not job_id.strip():` | `router.py:2093` |
| `_handle_loop_input` | `loop_id` | `if not loop_id:` | `router.py:1488` |
| `_handle_loop_state_update` | `loop_id` + `values` | `if not loop_id or not isinstance(raw_values, dict):` | `router.py:1813` |
| `_handle_job_create` | `goal` | `if not isinstance(goal_text, str) or not goal_text.strip():` | `router.py:2021` |

The `loop_*` handlers use loose truthy checks; the `job_*` handlers use stricter `isinstance` checks. A non-string `loop_id` (e.g., integer `0`) would pass the truthy check in some handlers but fail in others.

**Severity**: Medium.

---

## 3. Error Response Consistency

### 3.1 Two Different Error Response Formats

**Standard format** (used by ~95% of handlers):
```python
{"type": "error", "code": "INVALID_REQUEST", "message": "loop_id required", "request_id": request_id}
```

**Malformed format** (one instance, `router.py:1414`):
```python
{"type": "error", "error": str(e), "request_id": request_id}  # missing "code", uses "error" instead
```
This is in `_handle_loop_new` when workspace mount translation fails. It omits `code` and uses `error` as the field name instead of `message`.

**Severity**: Medium (clients parsing errors by `code` will miss this error entirely).

### 3.2 `command_response` Has a Third Error Format

The `command_request` path (`commands.py:111-142`) returns errors differently:
```python
# commands.py:128-140
response = {"type": "command_response", "command": command}
if error is not None:
    response["error"] = error  # string, not a code
```

And the FastAPI WebSocket command path (`channels/websocket.py:517-530`) has yet another format:
```python
response = {"type": "command_response", "request_id": request_id, "result": result, "error": str(exc)}
```

So `command_response` errors use `"error": <string>` while standard protocol errors use `"code": <CODE>, "message": <string>`. Clients must handle two different error parsing strategies.

**Severity**: Medium.

### 3.3 `request_id` Inconsistency on Error Responses

Most error responses include `request_id`, but some don't:

| Location | Has `request_id`? | Line |
|----------|-------------------|------|
| `command` handler NO_LOOP_SUBSCRIPTION | No | `router.py:243-250` |
| `command_request` handler NO_LOOP_SUBSCRIPTION | Yes | `router.py:391-399` |
| `detach` status response | N/A (not an error) | `router.py:308` |
| `_handle_loop_new` workspace error | Yes | `router.py:1414` |
| `query/engine.py:446-453` NO_LOOP_ID | No | `engine.py:450` |

The `NO_LOOP_ID` error from the query engine (`engine.py:450`) omits `request_id`, and the `NO_LOOP_SUBSCRIPTION` error for slash commands (`router.py:243-250`) also omits it. Since these go through `_send_client_message`, the client has no way to correlate them with a specific request.

**Severity**: Low-Medium.

### 3.4 Error Code Taxonomy is Ad Hoc

Error codes are defined in two places with overlapping but incomplete coverage:

**`validation.py:127-131`** (5 codes):
```
INVALID_MESSAGE, INVALID_JSON, RATE_LIMITED, INTERNAL_ERROR, UNKNOWN_MESSAGE_TYPE
```

**RFC-450 §Error Codes** (9 codes):
```
INVALID_MESSAGE, RATE_LIMITED, INTERNAL_ERROR, DAEMON_STARTING, DAEMON_BUSY,
DAEMON_DEGRADED, DAEMON_ERROR, SKILL_NOT_FOUND, SKILL_LOAD_FAILED
```

**Actual codes used in `router.py`** (20+ codes, many not in either list):
```
INVALID_REQUEST, NO_LOOP_SUBSCRIPTION, LOOP_NOT_FOUND, LOOP_NOT_SUBSCRIBED,
LOOP_CONTEXT, LOOP_STATE, RUNNER_UNAVAILABLE, CARD_MANAGER_UNAVAILABLE,
CARDS_FETCH_FAILED, NO_LOOP_ID, NO_SESSION, AUTOPILOT_NOT_READY,
JOB_CREATE_FAILED, JOB_NOT_FOUND, JOB_ALREADY_PAUSED, JOB_COMPLETED,
JOB_PAUSE_FAILED, JOB_NOT_PAUSED, JOB_RESUME_FAILED, JOB_CANCEL_FAILED,
GOAL_NOT_FOUND, LOOP_REATTACH_FAILED
```

`INVALID_REQUEST` is the most common code (~20 uses) but is not in either documented list. `UNKNOWN_MESSAGE_TYPE` from validation.py is never used in any handler.

**Severity**: Medium (no single source of truth for error codes).

---

## 4. API Ergonomics

### 4.1 Flat Message Structure is Good but Inconsistent

Most messages are flat (`{"type": "loop_get", "loop_id": "..."}`), which is good. But some use nested objects:
- `loop_list` request: `{"filter": {"status": "running", "exclude_empty": true}}` (nested)
- `invoke_skill_response`: `{"echo": {"skill_name": ..., "description": ..., "body": ..., "args": ...}}` (nested)
- `loop_new_response`: `{"workspace_mapping": {"host_root": ..., "container_root": ...}}` (nested, conditional)

This mix is acceptable but should be documented as a convention: flat for scalar fields, nested only for complex sub-objects.

### 4.2 Redundant Message Types

**`command` vs `command_request`**: Both deliver slash commands to a loop. The `command` type (`router.py:225-256`) enqueues a raw `{"type": "command", "cmd": cmd}` to the loop dispatcher. The `command_request` type (`router.py:388-404`) enqueues a structured `{"command": ..., "params": ...}` with `request_id` correlation. They serve the same purpose with different field names and error handling. The `command_request` path is strictly more capable (structured params, request_id, structured response). The `command` path should be deprecated.

**`detach` vs `loop_detach`**: The `detach` message (`router.py:304-312`) sets `session.detach_requested = True` and sends `{"type": "status", "state": "detached"}`. The `loop_detach` message (`router.py:1256-1318`) unsubscribes from a specific loop and updates DB metadata. They serve different purposes (client-level vs loop-level), but the naming is confusing — `detach` sounds like it should be the loop-level operation.

**`daemon_ready` vs `daemon_status`**: `daemon_ready` (`router.py:258-259`) returns a readiness message. `daemon_status` (`router.py:347-349,671-708`) returns detailed status. `daemon_ready` is a subset of `daemon_status` and could be consolidated.

### 4.3 `loop_input` vs `input` Internal Type Confusion

The wire message type is `loop_input`, but the internal queue payload type is `input`:
```python
# router.py:1637
queue_payload = {"type": "input", "text": text_for_queue, ...}
```
The `_process_loop_input_message()` handler (`handlers.py:213`) checks for both `"input"` and `"loop_input"`:
```python
if msg_type not in ("input", "loop_input"):
```
This dual-type handling is a workaround for the type mutation that happens during queueing. It works but is confusing — the internal type should not be a wire type.

### 4.4 Response Type Naming is Verbose

Response types follow `{request_type}_response` pattern (e.g., `loop_list_response`, `loop_get_response`, `loop_cards_fetch_response`). This is consistent and clear, but some names are very long. Consider whether `loop_cards_fetch_response` could be `loop_cards_response`.

**Severity**: Low (cosmetic).

---

## 5. Documentation Gaps

### 5.1 RFC-450 Documents Only 8 of 37 Client→Server Message Types

RFC-450 §Client→Server Messages documents:
- `input`, `command`, `resume_thread`, `subscribe_thread`, `detach`, `skills_list`, `models_list`, `invoke_skill`

But the router dispatches **37 message types** (see full list in §1.5 analysis above). The 29 undocumented types include the entire `loop_*` RPC family, the `job_*` family, `autopilot_*`, `daemon_status/shutdown`, `config_get`, `mcp_status`, `auth/auth_refresh`, and `command_request`.

These are documented across separate RFCs (RFC-503, RFC-504, RFC-228, RFC-454, RFC-307), but RFC-450 — the "Unified Daemon Communication Protocol" — does not reference them or provide a complete message type catalog.

### 5.2 RFC-450 Uses Obsolete `thread_id` Field Names

As documented in §1.1, RFC-450 still references `thread_id` in `status`, `subscription_confirmed`, and `event` messages, but the code uses `loop_id`. RFC-450 needs a field rename pass.

### 5.3 RFC-450 Documents `resume_thread` and `subscribe_thread` — Neither Exists in Code

RFC-450 §Client→Server lists `resume_thread` and `subscribe_thread` as message types. The router has no handlers for these — they were renamed to `loop_reattach` and `loop_subscribe` respectively. RFC-450 is stale.

### 5.4 No Error Code Reference Table

There is no single document listing all valid error codes. RFC-450 lists 9, validation.py defines 5 (different ones), and the code uses 20+. An error code registry is needed.

---

## 6. Versioning

### 6.1 No Protocol Version Field

There is **no `version` or `protocol_version` field** in any message. The daemon reports `daemon_version` and `core_version` in `daemon_status_response` (`router.py:704-705`), but there is no wire-level protocol version negotiation.

### 6.2 No Capability Negotiation

Clients cannot declare which features they support. The `daemon_ready` handshake (`router.py:258-259`) is one-directional (daemon tells client it's ready) with no client capability declaration.

### 6.3 Evolution Strategy

The current approach relies on:
- Optional fields (forward-compatible by default — new fields are ignored by old clients).
- `request_id` correlation (allows adding new RPC types without breaking old ones).
- Unknown message types are silently logged and ignored (`router.py:406`, `validation.py:98-101`).

This works but has no formal versioning. A breaking change (like the v2.0 mandatory subscription in RFC-450) requires a hard-cut with no negotiation.

---

## 7. Concrete Polishing Recommendations

### 7.1 Unify `loop_id` in RFC-450 (HIGH PRIORITY)

**What**: Update RFC-450 to replace all `thread_id` references with `loop_id` in the Server→Client message table.

**Files**:
- `docs/specs/RFC-450-daemon-communication-protocol.md` — lines 171-173, 234-247

**Proposed change**:
```diff
- | `status` | `state` (req), `thread_id` (req), `client_id` (req), ... |
- | `subscription_confirmed` | `thread_id` (req), `client_id` (req) | ... |
- | `event` | `thread_id` (req), `namespace` (req), ... |
+ | `status` | `state` (req), `loop_id` (opt), `client_id` (req), ... |
+ | `subscription_confirmed` | `loop_id` (req), `client_id` (req) | ... |
+ | `event` | `loop_id` (req), `namespace` (req), ... |
```

Also rename `resume_thread` → `loop_reattach` and `subscribe_thread` → `loop_subscribe` in the Client→Server table.

### 7.2 Fix Malformed Error Response in `_handle_loop_new` (HIGH PRIORITY)

**What**: The workspace mount error at `router.py:1414` uses `"error"` instead of `"code"`/`"message"`.

**File**: `packages/soothe-daemon/src/soothe_daemon/protocol/router.py:1412-1416`

**Proposed change**:
```diff
- await d._send_client_message(
-     client_id,
-     {"type": "error", "error": str(e), "request_id": request_id},
- )
+ await d._send_client_message(
+     client_id,
+     {
+         "type": "error",
+         "code": "WORKSPACE_RESOLUTION_FAILED",
+         "message": str(e),
+         "request_id": request_id,
+     },
+ )
```

### 7.3 Resolve `cmd` vs `command` Collision (HIGH PRIORITY)

**What**: Two different message formats share `type: "command"`. Rename the RPC command path.

**Files**:
- `packages/soothe-sdk/src/soothe_sdk/client/ws_command_client.py:88-93` — change `"type": "command"` to `"type": "rpc_command"`
- `packages/soothe-daemon/src/soothe_daemon/channels/websocket.py:471-473` — update dispatch check to `msg_dict.get("type") == "rpc_command"`
- `packages/soothe-daemon/src/soothe_daemon/protocol/validation.py` — add `rpc_command` validation

**Proposed wire format for RPC commands**:
```json
{"type": "rpc_command", "command": "autopilot_status", "request_id": "cmd_1", "payload": {}}
```

This eliminates the collision with slash-command `{"type": "command", "cmd": "/exit"}`.

### 7.4 Centralize Validation with Pydantic Models (MEDIUM PRIORITY)

**What**: Define Pydantic models for all 37 client→server message types in `packages/soothe-sdk/src/soothe_sdk/client/schemas.py` and use them in `validate_message()`.

**File**: `packages/soothe-daemon/src/soothe_daemon/protocol/validation.py`

**Proposed structure** (new file `packages/soothe-daemon/src/soothe_daemon/protocol/schemas.py`):
```python
from pydantic import BaseModel, Field

class LoopInputRequest(BaseModel):
    type: str = Field(default="loop_input")
    loop_id: str = Field(..., description="Loop identifier")
    content: str | dict = Field(..., description="User input text or structured content")
    autonomous: bool = False
    max_iterations: int | None = None
    # ... etc

class LoopGetRequest(BaseModel):
    type: str = Field(default="loop_get")
    loop_id: str = Field(..., min_length=1)
    verbose: bool = False
    request_id: str | None = None

# ... one model per message type
```

Then update `validate_message()`:
```python
def validate_message(msg: dict[str, Any]) -> list[str]:
    msg_type = msg.get("type")
    schema = _MESSAGE_SCHEMAS.get(msg_type)
    if schema is None:
        return []  # unknown type, allow (forward compat)
    try:
        schema.model_validate(msg)
        return []
    except ValidationError as e:
        return [str(err) for err in e.errors()]
```

**Benefit**: Eliminates ~15 duplicated `if not loop_id:` checks, provides automatic type validation, and generates schema documentation.

### 7.5 Standardize Error Response Helper (MEDIUM PRIORITY)

**What**: Create a single `_send_error()` helper that enforces the standard format.

**File**: `packages/soothe-daemon/src/soothe_daemon/protocol/router.py` (add method to `MessageRouter`)

**Proposed**:
```python
async def _send_error(
    self, client_id: Any, *, code: str, message: str,
    request_id: str | None = None, details: dict | None = None,
) -> None:
    """Send a standardized protocol error response."""
    error: dict[str, Any] = {
        "type": "error",
        "code": code,
        "message": message,
    }
    if request_id is not None:
        error["request_id"] = request_id
    if details:
        error["details"] = details
    await self._daemon._send_client_message(client_id, error)
```

Then replace all inline error dicts with calls to `self._send_error(...)`. This ensures `code` and `message` are always present and `request_id` is included when available.

### 7.6 Consolidate Error Code Registry (MEDIUM PRIORITY)

**What**: Create a single `ErrorCodes` enum/constant class and update RFC-450.

**File**: `packages/soothe-daemon/src/soothe_daemon/protocol/validation.py`

**Proposed**:
```python
class ErrorCodes:
    # Protocol-level (from RFC-450)
    INVALID_MESSAGE = "INVALID_MESSAGE"
    INVALID_REQUEST = "INVALID_REQUEST"  # most common — promote to documented
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DAEMON_BUSY = "DAEMON_BUSY"
    DAEMON_STARTING = "DAEMON_STARTING"
    DAEMON_DEGRADED = "DAEMON_DEGRADED"

    # Authorization
    NO_LOOP_SUBSCRIPTION = "NO_LOOP_SUBSCRIPTION"
    LOOP_NOT_SUBSCRIBED = "LOOP_NOT_SUBSCRIBED"
    NO_SESSION = "NO_SESSION"
    NO_LOOP_ID = "NO_LOOP_ID"

    # Resource not found
    LOOP_NOT_FOUND = "LOOP_NOT_FOUND"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    GOAL_NOT_FOUND = "GOAL_NOT_FOUND"
    SKILL_NOT_FOUND = "SKILL_NOT_FOUND"

    # State conflicts
    JOB_ALREADY_PAUSED = "JOB_ALREADY_PAUSED"
    JOB_NOT_PAUSED = "JOB_NOT_PAUSED"
    JOB_COMPLETED = "JOB_COMPLETED"

    # Operation failures
    SKILL_LOAD_FAILED = "SKILL_LOAD_FAILED"
    RUNNER_UNAVAILABLE = "RUNNER_UNAVAILABLE"
    AUTOPILOT_NOT_READY = "AUTOPILOT_NOT_READY"
    CARD_MANAGER_UNAVAILABLE = "CARD_MANAGER_UNAVAILABLE"
    CARDS_FETCH_FAILED = "CARDS_FETCH_FAILED"
    LOOP_CONTEXT = "LOOP_CONTEXT"
    LOOP_STATE = "LOOP_STATE"
    LOOP_REATTACH_FAILED = "LOOP_REATTACH_FAILED"
    WORKSPACE_RESOLUTION_FAILED = "WORKSPACE_RESOLUTION_FAILED"

    # Job operation failures
    JOB_CREATE_FAILED = "JOB_CREATE_FAILED"
    JOB_PAUSE_FAILED = "JOB_PAUSE_FAILED"
    JOB_RESUME_FAILED = "JOB_RESUME_FAILED"
    JOB_CANCEL_FAILED = "JOB_CANCEL_FAILED"
```

Update RFC-450 §Error Codes to include the full list with categories.

### 7.7 Unify Input Field Naming (MEDIUM PRIORITY)

**What**: Standardize on `content` as the field name for user text input across all message types.

**Files**:
- `router.py:2486` — `job_guidance` currently uses `text`; change to `content`
- `router.py:1637-1638` — internal queue payload uses `text`; this is internal, but should be documented as internal-only
- `handlers.py:230-237` — the `_process_loop_input_message` handler reads `msg.get("text")` for the `"input"` type; this is the internal queue payload, so it's acceptable, but add a comment clarifying this is internal-only

**Proposed**:
```diff
# router.py:2486 (job_guidance handler)
- text = msg.get("text")
+ text = msg.get("content")
```

Update `WsCommandClient` or any other client that sends `job_guidance` to use `content`.

### 7.8 Add Protocol Version Field (LOW PRIORITY)

**What**: Add an optional `protocol_version` field to the `daemon_ready` handshake.

**Files**:
- `packages/soothe-daemon/src/soothe_daemon/server/core.py` — `daemon_ready_message()` method
- `packages/soothe-sdk/src/soothe_sdk/client/websocket.py` — `request_daemon_ready()` / `wait_for_daemon_ready()`

**Proposed**:
```python
# daemon_ready_message()
{
    "type": "daemon_ready",
    "state": d._readiness_state,
    "protocol_version": "1",  # major version
    "daemon_version": daemon_version,
}
```

Clients check `protocol_version` and can refuse to connect if the major version is incompatible. Minor version changes are non-breaking (new optional fields, new message types).

### 7.9 Extend `validate_message` Coverage to All Transports (MEDIUM PRIORITY)

**What**: Call `validate_message()` in the asyncio TCP dispatch path, not just the FastAPI WebSocket path.

**Files**:
- `packages/soothe-daemon/src/soothe_daemon/server/core.py:1457-1471` — `_dispatch_with_semaphore()`
- `packages/soothe-daemon/src/soothe_daemon/server/handlers.py:147-149` — `_handle_client_message()`

**Proposed** (in `_dispatch_with_semaphore`):
```python
async def _dispatch_with_semaphore(self, client_id: str, msg: dict[str, Any]) -> None:
    async with self._dispatch_semaphore:
        # Validate before dispatch (previously only on FastAPI WS path)
        errors = validate_message(msg)
        if errors:
            from soothe_daemon.protocol import create_error_response
            await self._send_client_message(client_id, create_error_response("INVALID_MESSAGE", errors[0]))
            return
        try:
            await self._message_router.dispatch(client_id, msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error dispatching message for client %s", client_id)
```

### 7.10 Deprecate `command` Slash-Command Path in Favor of `command_request` (LOW PRIORITY)

**What**: The `command_request` RPC path (`router.py:388-404`, `commands.py`) is strictly more capable than the legacy `command` path (`router.py:225-256`). It supports `request_id` correlation, structured params, and structured responses.

**Action**: Document `command` as deprecated in RFC-450 and RFC-454. Migrate the TUI to use `command_request` for slash commands. Eventually remove the `command` handler.

**Files to update**:
- `packages/soothe-sdk/src/soothe_sdk/client/websocket.py:372-378` — `send_command()` should send `command_request` format
- `packages/soothe-daemon/src/soothe_daemon/protocol/router.py:225-256` — add deprecation log
- `docs/specs/RFC-450-daemon-communication-protocol.md` — mark `command` as deprecated

### 7.11 Complete RFC-450 Message Type Catalog (MEDIUM PRIORITY)

**What**: RFC-450 should contain a complete table of all 37 client→server message types, even if details are in sub-RFCs. Add a "Message Type Registry" section.

**Proposed addition to RFC-450**:
```markdown
### Complete Message Type Catalog

| Type | RFC | Required Fields | Description |
|------|-----|-----------------|-------------|
| `loop_new` | RFC-503 | — | Create new loop |
| `loop_subscribe` | RFC-503 | `loop_id` | Subscribe to loop events |
| `loop_input` | RFC-503 | `loop_id`, `content` | Submit user input |
| `loop_get` | RFC-504 | `loop_id` | Get loop metadata |
| `loop_list` | RFC-504 | — | List loops |
| `loop_tree` | RFC-504 | `loop_id` | Get checkpoint tree |
| `loop_prune` | RFC-504 | `loop_id` | Prune failed branches |
| `loop_delete` | RFC-504 | `loop_id` | Delete loop |
| `loop_reattach` | RFC-411 | `loop_id` | Reattach to loop |
| `loop_detach` | RFC-503 | `loop_id` | Detach from loop |
| `loop_messages` | RFC-503 | `loop_id` | Get persisted messages |
| `loop_state_get` | RFC-503 | `loop_id` | Get checkpoint state |
| `loop_state_update` | RFC-503 | `loop_id`, `values` | Update checkpoint state |
| `loop_cards_fetch` | RFC-413 | `loop_id` | Get display card snapshot |
| `command` | RFC-450 | `cmd` | Slash command (deprecated) |
| `command_request` | RFC-454 | `command` | Structured RPC command |
| `detach` | RFC-450 | — | Client detach notification |
| `daemon_ready` | RFC-450 | — | Readiness handshake |
| `daemon_status` | RFC-450 | — | Daemon status query |
| `daemon_shutdown` | RFC-450 | — | Request daemon shutdown |
| `config_get` | RFC-450 | — | Get daemon config |
| `skills_list` | RFC-450 | — | List skills |
| `invoke_skill` | RFC-450 | `skill` | Invoke a skill |
| `models_list` | RFC-450 | — | List models |
| `mcp_status` | RFC-412 | — | MCP server status |
| `auth` | RFC-307 | `access_key`, `secret_key` | AKSK auth |
| `auth_refresh` | RFC-307 | `refresh_token` | Token refresh |
| `job_create` | RFC-228 | `goal` | Create autopilot job |
| `job_status` | RFC-228 | `job_id` | Query job status |
| `job_pause` | RFC-228 | `job_id` | Pause job |
| `job_resume` | RFC-228 | `job_id` | Resume job |
| `job_cancel` | RFC-228 | `job_id` | Cancel job |
| `job_dag` | RFC-228 | `job_id` | Get job DAG |
| `job_guidance` | RFC-228 | `job_id`, `content` | Send guidance |
| `autopilot_subscribe` | RFC-228 | — | Subscribe to autopilot events |
| `autopilot_unsubscribe` | RFC-228 | — | Unsubscribe from autopilot |
```

---

## 8. Summary of Priorities

| Priority | Recommendation | Impact |
|----------|---------------|--------|
| **HIGH** | 7.2 — Fix malformed error in `_handle_loop_new` | Bug fix — clients miss errors |
| **HIGH** | 7.3 — Resolve `cmd` vs `command` collision | Prevents silent misrouting |
| **HIGH** | 7.1 — Update RFC-450 `thread_id` → `loop_id` | Doc/code alignment |
| **MEDIUM** | 7.4 — Pydantic schema validation for all message types | Centralized validation |
| **MEDIUM** | 7.5 — Standardized error response helper | Consistent error format |
| **MEDIUM** | 7.6 — Consolidate error code registry | Single source of truth |
| **MEDIUM** | 7.7 — Unify input field naming (`content`) | Ergonomics |
| **MEDIUM** | 7.9 — Extend validation to all transports | Security/robustness |
| **MEDIUM** | 7.11 — Complete RFC-450 message catalog | Documentation |
| **LOW** | 7.8 — Protocol version field | Future evolution |
| **LOW** | 7.10 — Deprecate `command` path | Cleanup |

---

## Appendix: Complete Message Type Inventory

**Client → Server (37 types)**, dispatched in `protocol/router.py:dispatch()`:

`auth`, `auth_refresh`, `autopilot_subscribe`, `autopilot_unsubscribe`, `command`, `command_request`, `config_get`, `daemon_ready`, `daemon_shutdown`, `daemon_status`, `detach`, `invoke_skill`, `job_cancel`, `job_create`, `job_dag`, `job_guidance`, `job_pause`, `job_resume`, `job_status`, `loop_cards_fetch`, `loop_delete`, `loop_detach`, `loop_get`, `loop_input`, `loop_list`, `loop_messages`, `loop_new`, `loop_prune`, `loop_reattach`, `loop_state_get`, `loop_state_update`, `loop_subscribe`, `loop_tree`, `mcp_status`, `models_list`, `skills_list`

**Validated in `validation.py` (6 types)**: `command`, `daemon_ready`, `detach`, `invoke_skill`, `models_list`, `skills_list`

**Documented in RFC-450 (8 types)**: `input`, `command`, `resume_thread`, `subscribe_thread`, `detach`, `skills_list`, `models_list`, `invoke_skill`

**Documented but not in code (2 types)**: `resume_thread` (renamed to `loop_reattach`), `subscribe_thread` (renamed to `loop_subscribe`)

**In code but not in RFC-450 (29 types)**: All `loop_*` (except none in RFC-450), all `job_*`, `autopilot_*`, `daemon_status`, `daemon_shutdown`, `config_get`, `mcp_status`, `auth`, `auth_refresh`, `command_request`
