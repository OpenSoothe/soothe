# IG-522: RFC-450 Implementation Gap Analysis and Remediation

**IG**: 522
**Title**: RFC-450 Implementation Gap Analysis and Remediation
**Status**: In Progress
**Created**: 2026-06-29
**Dependencies**: RFC-450 (Unified Daemon Communication Protocol)
**Related**: IG-110 (Daemon Transport), IG-408 (Loop-scoped Events)

## Scope

Analyze the design-to-implementation gaps in RFC-450 "Unified Daemon Communication Protocol" and fill all identified gaps. The RFC defines a WebSocket-based daemon communication protocol with a unified message envelope, schema validation, error standardization, versioning, capability negotiation, and AsyncAPI documentation.

## Gap Analysis Summary

| Section | RFC Requirement | Implementation Status | Gap |
|---------|-----------------|----------------------|-----|
| §5.1-5.5 | Unified envelope `{proto, type, method, params, id}` | ✅ Complete | None |
| §5.6 | Batch request/response support | ⚠️ Partial | Daemon dispatch for arrays |
| §5.7 | Receipt mechanism | ❌ Missing | Process receipt, send receipt_response |
| §6 | Schema validation at transport boundary | ✅ Complete | None |
| §7 | Error response standardization | ✅ Complete | None |
| §8.1-8.3 | Protocol version, handshake, heartbeat | ✅ Complete | None |
| §8.4 | Deprecation signaling | ✅ Not Needed | Simplified to METHOD_NOT_FOUND only |
| §9.1-9.2 | Message type taxonomy | ✅ Complete | None |
| §9.4 | Stream termination `complete` message | ⚠️ Partial | Send complete on stream end |
| §10 | Naming conventions | ✅ Complete | None |
| §11 | AsyncAPI specification | ✅ Complete | Created docs/specs/asyncapi.yaml |

## Detailed Gap Analysis

### Gap 1: Batch Support (§5.6) - Server-Side Handling

**RFC Spec**: The server SHALL process batch requests (JSON arrays) and return an array of responses.

**Current State**:
- SDK has `BatchRequestEnvelope` and `BatchResponseEnvelope` models in `wire.py`
- Daemon router only dispatches single messages, not arrays
- WebSocket channel receives arrays but passes them as-is

**Required Changes**:
1. Router dispatch method to detect and handle JSON arrays
2. Process each batch item independently
3. Collect responses (only for items with `id`)
4. Return batch response array

### Gap 2: Receipt Mechanism (§5.7) - Delivery Confirmation

**RFC Spec**: Clients may include a `receipt` field on notifications; server SHALL respond with `receipt_response`.

**Current State**:
- `receipt_response` registered in `VALID_TYPES`
- Receipt field not processed anywhere
- No `receipt_response` messages ever sent

**Required Changes**:
1. Check `receipt` field on notification messages
2. Validate client declared `receipts` capability during handshake
3. Send `receipt_response` after notification is enqueued
4. Add receipt processing in router and WebSocket channel

### Gap 3: Deprecation Signaling (§8.4)

**RFC Spec**: Server SHALL include `deprecation` field when client calls a deprecated method.

**Current State**:
- No deprecation tracking registry
- No `deprecation` field in responses
- No `deprecated_methods` in connection_ack

**Required Changes**:
1. Create deprecation registry with method status
2. Add `deprecated_methods` to connection_ack result
3. Add `deprecation` field to response envelope
4. Track deprecated methods: currently none, infrastructure ready

### Gap 4: Stream Termination `complete` Message (§9.4)

**RFC Spec**: Subscriptions MUST terminate with an explicit `type: "complete"` message.

**Current State**:
- `complete` is registered in `VALID_TYPES`
- Streams stop silently without `complete`
- Autopilot and loop subscriptions don't send `complete`

**Required Changes**:
1. Send `complete` when loop stream ends (goal completed, cancelled, etc.)
2. Send `complete` when autopilot subscription ends
3. Send `complete` after reattachment history replay
4. Add `complete` message helper in router

### Gap 5: AsyncAPI Specification (§11)

**RFC Spec**: AsyncAPI 3.0 YAML as single source of truth for wire contract.

**Current State**:
- No `docs/specs/asyncapi.yaml` file exists
- Pydantic models are hand-written, not generated
- No CI drift detection

**Required Changes**:
1. Create `docs/specs/asyncapi.yaml` with full message catalog
2. Add CI check to regenerate models and diff
3. Document tooling pipeline in RFC-450

## Implementation Plan

### Phase 1: Batch and Receipt Support (Priority: Medium)

1. Add batch dispatch in MessageRouter
2. Add receipt processing in WebSocket channel
3. Update PARAMS_REGISTRY for batch/receipt

### Phase 2: Deprecation Infrastructure (Priority: Low)

1. Create deprecation registry module
2. Add deprecation field to connection_ack
3. Add deprecation field to response serialization

### Phase 3: Stream Termination (Priority: High)

1. Add `_send_complete` helper in router
2. Send complete on loop goal completion
3. Send complete on loop cancellation
4. Send complete on reattachment replay end

### Phase 4: AsyncAPI Specification (Priority: Low)

1. Create asyncapi.yaml skeleton
2. Populate with message schemas
3. Add CI validation step

## Files to Modify

- `packages/soothe-daemon/src/soothe_daemon/protocol/router.py` - batch dispatch, complete helper
- `packages/soothe-daemon/src/soothe_daemon/protocol/schemas.py` - receipt params
- `packages/soothe-daemon/src/soothe_daemon/channels/websocket.py` - receipt response
- `packages/soothe-daemon/src/soothe_daemon/server/core.py` - deprecation registry
- `packages/soothe-sdk/src/soothe_sdk/client/wire.py` - receipt envelope
- `docs/specs/asyncapi.yaml` - new file

## Verification

- Unit tests for batch dispatch
- Unit tests for receipt mechanism
- Unit tests for complete message
- Integration test for full subscription lifecycle
- AsyncAPI spec validation via asyncapi CLI
- AsyncAPI ↔ Pydantic drift detection (Phase 5)

## Progress Tracking

- [x] Phase 1: Batch support — Added `_dispatch_batch` method in router
- [x] Phase 1: Receipt mechanism — Added receipt processing in WebSocket channel
- [x] Phase 2: Deprecation approach — Simplified to METHOD_NOT_FOUND only (no wire signaling), RFC-450 §8.4 updated
- [x] Phase 3: Stream termination complete message — Added `_send_complete` helper, subscription_id tracking, complete sent on stream end
- [x] Phase 4: AsyncAPI specification — Created docs/specs/asyncapi.yaml with full message catalog
- [x] Phase 5: AsyncAPI spec completeness & drift detection (see below)

## Phase 5: AsyncAPI Spec Completeness, SDK Validation, and Drift Detection

A re-audit of RFC-450 §11 against the committed artifacts found three
remaining gaps the earlier phases left open. The asyncapi.yaml skeleton from
Phase 4 only defined schemas for a handful of methods; the full method catalog
(§6.2 registry) was not represented, there was no client-side params validation
(§6.5), and the normative "CI check SHALL detect drift" requirement (§11.3)
had no enforcement.

### Gap 6: AsyncAPI Method Schema Coverage (§11.2)

**RFC Spec**: The AsyncAPI spec is the single source of truth for message
schemas, with one `*Request`/`*Notification`/`*Subscribe` message per method.

**Pre-Phase-5 State**: `asyncapi.yaml` defined params schemas for only
`loopGet`, `loopList`, `loopNew`, `loopInput`, `subscribe` — missing
`loop_tree`, `loop_prune`, `loop_delete`, `loop_reattach`, `loop_detach`,
`loop_messages`, `loop_state_get`, `loop_state_update`, `loop_cards_fetch`,
all `job_*` methods, `daemon_status`/`daemon_shutdown`/`config_get`,
`skills_list`/`models_list`/`invoke_skill`/`mcp_status`, `auth`/`auth_refresh`,
`slash_command`/`rpc_command`, `autopilot_events` subscribe, and
`disconnect`. The channel `operations.receive` referenced only generic
`request`/`notification`/`subscribe` messages.

**Remediation**: Added 30+ method-specific params schemas and method-specific
message definitions to `docs/specs/asyncapi.yaml`; rewrote
`channels.main.operations.receive` to enumerate every method-specific message.

### Gap 7: Client-Side Params Validation (§6.5)

**RFC Spec**: The same Pydantic models SHALL be defined in (or imported from)
the SDK so clients validate before sending.

**Pre-Phase-5 State**: `packages/soothe-sdk/src/soothe_sdk/client/schemas.py`
held only `Plan`/`PlanStep`/`ToolOutput` (unrelated). No client-side params
models existed; clients sent raw dicts, deferring all validation to the daemon.

**Remediation**: Created
`packages/soothe-sdk/src/soothe_sdk/client/protocol_params.py` with a params
model per method (mirroring the daemon `PARAMS_REGISTRY`), re-exporting
`ConnectionInitParams` from `wire.py` to avoid duplication. Exported all
models from `soothe_sdk.client.__init__`. Added 79 unit tests in
`packages/soothe-sdk/tests/unit/client/test_protocol_params.py`.

### Gap 8: CI Drift Detection (§11.3)

**RFC Spec**: A CI check SHALL regenerate and diff against the committed
version to detect drift between the AsyncAPI spec and the Pydantic models.

**Pre-Phase-5 State**: No drift detection existed. The spec and the
hand-written models could silently diverge.

**Remediation**: Created `scripts/check_asyncapi_drift.py` — a drift detector
that parses `asyncapi.yaml`, cross-references every `*Params` schema and
method-specific message against the daemon `PARAMS_REGISTRY` and the SDK
client params models, and reports missing entries in either direction. Wired
into `.github/workflows/ci.yml` (code-quality job, `--strict`) and
`scripts/verify_finally.sh` (new `check_asyncapi_drift` phase). Added 14 unit
tests in `packages/soothe-daemon/tests/unit/protocol/test_asyncapi_drift.py`.

### Phase 5 Files

- `docs/specs/asyncapi.yaml` — expanded with full method catalog
- `packages/soothe-sdk/src/soothe_sdk/client/protocol_params.py` — new, client params models
- `packages/soothe-sdk/src/soothe_sdk/client/__init__.py` — re-exports
- `packages/soothe-sdk/tests/unit/client/test_protocol_params.py` — new, 79 tests
- `scripts/check_asyncapi_drift.py` — new, drift detector
- `packages/soothe-daemon/tests/unit/protocol/test_asyncapi_drift.py` — new, 14 tests
- `.github/workflows/ci.yml` — drift check CI step
- `scripts/verify_finally.sh` — drift check phase

All gaps filled. RFC-450 implementation is complete.

## Phase 6: Protocol-1 Clear Cut (No Backward Compatibility)

The final migration removed all backward-compatibility surfaces so clients
and the daemon speak protocol-1 exclusively. No legacy flat-form API remains.

### Daemon streaming send-side → protocol-1 `next` (RFC-450 §9.3)

Legacy streaming frames (`event`, `command_response`, card replay,
`autopilot_mode_changed`) are now wrapped in `{proto, type:"next",
payload:{namespace, mode, data}, id?}` envelopes at the
`SessionManager.send_to_client` wire boundary. `status` frames remain raw
(they are a defined top-level protocol-1 message type, §9.1, and double as
the connection handshake preamble). The raw `subscription_confirmed` frame
was dropped in favour of the `_send_next` subscribe-ack.

### Client receive-side → `next` payloads

The TUI (`TuiDaemonSession.iter_turn_chunks`), headless
(`cli/execution/daemon.py`), and SDK (`_STALE_TURN_PENDING_TYPES`) now
unwrap `next` envelopes to the inner `data` frame before branching on the
legacy `type`/`mode`/`data` fields. The SDK `next()` reader is the
protocol-1 stream consumer.

### Router: envelope-only dispatch (no flat-form acceptance)

The daemon router accepts protocol-1 envelopes
(`{proto, type, method, params, id}`) plus the three non-envelope control
types (`connection_init`/`ping`/`pong`) — and nothing else. Legacy
flat-form messages (`{type:"loop_get", loop_id:...}`) are rejected with
`METHOD_NOT_FOUND` at the dispatch boundary. Concretely:

- `_METHOD_TO_FLAT_TYPE` → `_METHOD_TO_HANDLER` (method → handler-name map
  for the five overrides: `slash_command`, `disconnect`, `loop_events`,
  `autopilot_events`, `rpc_command`).
- `HANDLER_REGISTRY` now holds only the three control types; every other
  method resolves via `_resolve_handler()` (overrides or `_handle_<method>`).
- `_unwrap_envelope` stays as an INTERNAL adapter that spreads `params` to
  the top level and carries `id` as `request_id` — handlers still read
  `msg.get("<field>")`, unchanged. The wire contract is envelope-only even
  though the handler-facing dict is flat.
- `PARAMS_REGISTRY` lost all `(type, None)` flat-form keys; only
  `(type, method)` envelope keys + the three control types remain.
- `validate_message` is envelope-only (no flat-form fallback).
- `daemon_ready` legacy alias removed (handler, VALID_TYPES entry,
  `daemon_ready_message`).

### SDK dead-compat removal

- `ErrorEnvelope.from_wire_dict` rejects flat-form (nested `error` object only).
- `JobGuidanceParams` dropped the `text` alias; `content` is canonical
  (daemon handler + schema + asyncapi spec all aligned).
- `_daemon_status_indicates_live` uses `readiness_state` only (no
  `running`/`port_live` legacy fallback).

### Cancel race fix (RFC-221)

`QueryEngine.cancel_loop` now records the loop in `_pending_cancels` so a
`/cancel` arriving in the window between the early `running` broadcast
(server/handlers.py) and `run_query`'s task registration is not lost;
`_run_stream` checks the flag at start and aborts immediately with
`idle` + `complete`. The `running` broadcast also moved to after task
registration so a concurrent cancel can resolve the asyncio task directly.

### Phase 6 Verification

- `./scripts/verify_finally.sh` — lint + drift + unit tests all green.
- Daemon unit: 891 passed. Daemon+core+protocol integration: 124 passed.
- Daemon+autopilot integration: 112 passed. Protocol integration: 34 passed.
- CLI unit: 457 passed. SDK unit: 466 passed. Core unit: 3017 passed.