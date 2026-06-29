# IG-525: Go & TypeScript Client Migration to RFC-450 Protocol-1

**Guide**: IG-525
**Title**: Migrate Go and TypeScript Soothe clients to the RFC-450 protocol-1 wire contract
**Created**: 2026-06-29
**Related RFCs**: RFC-450 (Unified Daemon Communication Protocol)
**Scope**: `client/go/**` and `client/typescript/**` — full migration from the legacy flat wire format to the protocol-1 `{proto, type, method, params, id}` envelope.
**Status**: Done

## Outcome

Both clients migrated to protocol-1 and verified end-to-end against a live
daemon.

- **TypeScript** (`client/typescript`): `npm test` (118 unit, 27 integration),
  `npm run typecheck`, `npm run build` all green. Integration suite (27 tests)
  passes against the daemon including full conversation streaming, job IPC,
  loop lifecycle, skills/models/config, direct-LLM, and loop messages/state/cards.
- **Go** (`client/go`): `go vet ./...` clean; `go test ./...` green (unit +
  integration + stress) against a healthy daemon, including direct-LLM
  (text/image/structured), full conversation, job IPC, and stress
  (concurrent/sustained load/event streaming/resource cleanup).

Key client-side fixes during migration:
- Both clients perform `connection_init`/`connection_ack` in connect; no more
  `daemon_ready`.
- TS: separated live-socket reads (RPC waits) from the `messageBuffer`
  (stream readers) in `requestResponse`/`subscribe` to prevent head-of-line
  blocking when a `loop_events` subscription floods the shared queue (fixed
  `getLoopMessages`/`getLoopState`/`fetchLoopCards` timeouts).
- TS: fixed double-delivery in the `ws.on('message')` handler (a frame was
  both buffered AND resolver-delivered).
- Go: `DecodeMessage` projects event-shaped `next` payloads to `EventMessage`
  so `raw.(EventMessage)` consumers (LoopAIMessage, NamespaceParts) keep
  working under protocol-1's `next` wrapping.
- Go: `DaemonError` carries a numeric `code` (was string).

## Pre-existing daemon note (not protocol, not fixed here)

Under sustained stress (hundreds of loop creations/worker respawns on a
long-running daemon), `packages/soothe/src/soothe/foundation/loop/state/sloop_manager.py`
`_flush_worker_loop` raises `RuntimeError: Queue is bound to a different event
loop` / `Event loop is closed` — an asyncio Queue created on one loop is reused
after the worker thread respawns on a new loop. This is a core-package
threading bug, not a WS-protocol or client bug; it is not introduced by this
migration and is out of scope for IG-525. A fresh daemon handles the full
stress suite cleanly.

---

## Goal

The daemon (per IG-522) is now envelope-only: it rejects legacy flat-form
messages at the handshake and dispatch stages with `METHOD_NOT_FOUND` /
`INVALID_REQUEST`. The Go and TypeScript clients still speak the legacy
ad-hoc format (`{type, request_id, <flat fields>}`, `*_response` types,
`daemon_ready`, `loop_subscribe`, `subscription_confirmed`, `detach`).

Migrate both clients so every send/receive uses the protocol-1 envelope and
the bidirectional `connection_init`/`connection_ack` handshake, then prove
all client tests pass against the real daemon (and against migrated test
servers). If the daemon misbehaves, fix the daemon and repeat.

## Protocol-1 Contract (authoritative — from RFC-450 + daemon source)

### Envelope (every message)
`{proto:"1", type, method?, params?, id?, result?, error?, payload?, receipt?}`

### Message classes (`type`)
`connection_init`, `connection_ack`, `request`, `response`, `notification`,
`subscribe`, `next`, `error`, `complete`, `unsubscribe`, `ping`, `pong`,
`receipt_response`, `disconnect`.

### Handshake (client MUST do first, after WS upgrade)
1. Send `connection_init`: `{proto:"1", type:"connection_init", params:{client_version, client_name, accept_proto:["1"], capabilities:["streaming","batch","heartbeat","receipts"]}}`.
2. Daemon sends an initial `status` frame (`{proto:"1", type:"status", state, input_history:[]}`) then `connection_ack` (`{proto:"1", type:"connection_ack", result:{server_version, protocol_version, capabilities, readiness_state, heartbeat_interval_ms}}`).
3. Proceed only when `readiness_state == "ready"`. On `starting`/`warming`, bounded-retry `connection_init`.

### Operations
- **request** (`id` present) → daemon replies `response` (`{type:"response", result, id}`) or `error` (`{type:"error", error:{code,message,data?}, id}`). Correlate by `id`.
- **notification** (no `id`) → fire-and-forget. `loop_input` is a notification by default.
- **subscribe** (`id` present, `method:"loop_events"` or `"autopilot_events"`) → stream events arrive as `next` (`{type:"next", payload, id}`); stream ends with `complete` (`{type:"complete", id}`) or `error`. Subscription confirmation is a `next` with `payload.event=="subscribed"`.
- **unsubscribe** (`{type:"unsubscribe", id}`) cancels a subscription by `id`.
- **disconnect** notification = client leaving (daemon keeps loops running).

### Stream events (`next.payload`)
Legacy free-form frames (`event`, `card.*`, `command_response`, status-with-loop)
are wrapped by the daemon's session manager into `next` envelopes:
`payload = {namespace:[], mode:<orig type>, data:<orig frame>}`. The original
`loop_id` is preserved inside `data`. `status` frames pass through raw (they
are a defined protocol-1 type), NOT wrapped in `next`.

### Errors
Numeric codes (JSON-RPC ranges). Nested `error:{code, message, data?}`.
Echo request `id` when the request had one.

## Migration Plan

### Phase 1 — TypeScript client (`client/typescript/src`)
1. `protocol.ts`: rewrite envelope encode/decode + typed message interfaces to protocol-1. Keep `encodeMessage`/`splitWirePayload`/`newRequestID`. Add `nextEnvelope`/`unwrapNext` helpers. Map legacy `*_response` decode → envelope `response` (extract `result`).
2. `client.ts`: `connect()` performs handshake (send `connection_init`, wait `connection_ack` ready). `sendMessage` unchanged (sends raw envelope). `requestResponse(method, params, timeout)` sends a `request` envelope, correlates by `id`, returns `result`. Handle `ping`/`pong`. Add `notify`, `subscribe`, `unsubscribe`, `next`. Migrate all `sendX`/`listX`/`getX` helpers to envelope form.
3. `session.ts`: `bootstrapLoopSession` → handshake (no more `daemon_ready`), `loop_new` request, `subscribe` to `loop_events`. Wait helpers updated for `connection_ack`/`next`/`status`.
4. `helpers.ts`: envelope-based RPCs.
5. `errors.ts`: `DaemonError` carries numeric `code`.
6. `events.ts`, `verbosity.ts`, `config.ts`: minimal (event constants unchanged; verbosity unchanged; config keep timeouts, add `connectionAckTimeout`).
7. `index.ts`: export updated types.

### Phase 2 — Go client (`client/go`)
Mirror the TS migration across `protocol.go`, `client.go`, `send_methods.go`, `request.go`, `session.go`, `helpers.go`, `errors.go`, `heartbeat.go`. Keep public method signatures stable where possible (callers in-repo and external depend on them).

### Phase 3 — Tests
Migrate `client/typescript/test/**` and `client/go/*_test.go` (+ `examples/`) to protocol-1: update `ws-server.ts` handlers and the inline `httptest` servers to speak envelopes; update assertions to `response`/`next`/`status`/`error` shapes.

### Phase 4 — Verify
- `cd client/typescript && npm test && npm run typecheck && npm run build`
- `cd client/go && go test ./...`
- Spin up the real daemon, run integration tests against it; fix daemon if it breaks.

## Success Criteria

| Criterion | Verification |
|-----------|--------------|
| TS + Go clients send only protocol-1 envelopes | Unit tests assert `{proto,type,method,params,id}` on every send |
| Handshake works against real daemon | Integration test connects, gets `connection_ack` ready |
| All TS unit tests pass | `npm test` green |
| All Go tests pass | `go test ./...` green |
| TS builds + typechecks | `npm run build` + `npm run typecheck` |
| Clients interop with the migrated daemon | Live integration run |
