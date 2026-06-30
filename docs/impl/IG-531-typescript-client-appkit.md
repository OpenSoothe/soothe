# IG-531: TypeScript Client Core Upgrade and Appkit Implementation

**Guide**: IG-531
**Title**: Upgrade `client/typescript` core `Client` and extract `appkit` package
**Created**: 2026-06-30
**Related RFCs**: RFC-629 (Client Library — Core Upgrade and Appkit Architecture), RFC-450 (Daemon Communication Protocol), RFC-614 (Unified Streaming Messaging), RFC-403 (Unified Event Naming)
**Scope**: `client/typescript/src/**` (core upgrades) + new `client/typescript/src/appkit/` package.
**Status**: In Progress — Phase 1 (core `Client` upgrades) complete 2026-06-30; Phase 2 (`appkit` package) complete 2026-06-30; Phases 3–4 blocked on a TypeScript application consuming the daemon (see Phase 3 notes).

## Overview

This guide implements the TypeScript half of RFC-629 (the Go half is IG-527). It folds the transport/lifecycle layer down into the core `Client` (Layer 0) and ports the Go `appkit` package's reusable application mechanics into a new `client/typescript/src/appkit` package (Layer 1). Product-specific code stays in the application (Layer 2).

The work is sequenced core-first because `appkit` depends on a safe, concurrent, reconnect-aware `Client`. The multiplexer is the highest-risk piece; it changes the message-handler's event-routing contract and must preserve the existing `receiveMessages`/`readEvent` semantics for unsolicited frames.

## Prerequisites

- [x] RFC-629 in Draft status — currently Draft (generalized for Go + TypeScript 2026-06-30)
- [x] `client/typescript` at module `@mirasoth/soothe-client`, Node ≥19, dep `ws`
- [x] IG-525 work complete (protocol-1 migration) — confirmed Done; this guide builds on it
- [x] Go IG-527 complete (Phase 1 + 2) — the reference implementation this port follows

## Implementation Plan

### Phase 1: Core `Client` transport/lifecycle upgrades (Layer 0)

**Goal**: Make `Client` safe, concurrent, and reconnect-aware. All changes additive — existing `Client`/`Send*`/`Request*` signatures preserved.

**Tasks**:
- [x] 1.1 `DisconnectCause` enum + `ReconnectError`/`StaleLoopError` in `errors.ts`.
- [x] 1.2 Reconnect config knobs (`reconnectMaxAttempts`, `reconnectInitialDelay`, `reconnectMaxDelay`, `reattachProbeTimeout`) in `config.ts`.
- [x] 1.3 `'disconnected'` event via `EventEmitter` — emitted exactly once on connection drop, carrying a `DisconnectCause` (clean = `disconnect` notification, unclean = read/write error or missed pong). Wired into the `ws.on("close")`, `ws.on("error")`, `sendMessage` write-error, and heartbeat-timeout paths.
- [x] 1.4 `reconnect()` — bounded-retry backoff re-dial + handshake on the same `Client`; resets `disconnFired`/`mux`.
- [x] 1.5 `reattachAndProbe(loopID)` — `loop_reattach` + `subscribe(loop_events)` + `loop_get` probe; returns `StaleLoopError` on `-32200` or probe timeout/error.
- [x] 1.6 **Multiplexer** (`multiplexer.ts`) — `Multiplexer` class with pending-RPC/subscription/receipt tables, `route(frame)` routing by `(type, id)`. `requestResponse` registers its RPC waiter *before* sending (ordering fix for fast echoes) and races the mux promise against a timeout and the `'disconnected'` event. `subscribe` keeps the resolver-queue path (subscription confirmation is a one-shot read, not a long-lived mux waiter, mirroring Go `LoopSubscribe`).

### Phase 2: `appkit` package extraction (Layer 1)

**Goal**: Port the Go `appkit` semantics to TypeScript idiomatically, de-domain-ified.

**Tasks**:
- [x] 2.1 `SessionStore` interface (`session_store.ts`) — `SessionEntry` + `SessionMessage`; async methods (TS) vs Go's sync methods.
- [x] 2.2 `SSEBroadcaster` (`broadcaster.ts`) — string-keyed; per-subscriber bounded queue (cap 100) with drop-on-full; `subscribe` returns an `AsyncIterable<SSEEvent>`.
- [x] 2.3 `EventClassifier` (`classifier.ts` + `thinking_step.ts`) — `classify` ports `processChatEvent` with configurable `deliverablePhases`; keys on `(namespace, mode, phase)`; handles `next` envelopes by projecting `payload.{namespace, mode, data}`. `extractThinkingStep` allowlist configurable, defaults to the Go set.
- [x] 2.4 `QueryGate` (`query_gate.ts`) — single-flight (`ErrQueryBusy`) + cancel-before-context (daemon cancel on a detached 10s `AbortController` before local abort).
- [x] 2.5 `ConnectionPool` (`pool.ts`) — acquire/release/reuse/stop; bootstrap (`loop_new`+subscribe via `BootstrapFunc`) or reattach (`connect`+`reattachAndProbe`); falls back to fresh bootstrap on `StaleLoopError`. `ManagedClient` interface + `ClientFactory`/`BootstrapFunc` for testability.
- [x] 2.6 `TurnRunner` (`turn_runner.ts`) — timeout turn loop: acquire → gate → send `loop_input` → race the event stream against the timeout/caller abort → classify → resolve deliverable → persist + broadcast; `onComplete`/`onError` hooks; `inputMessageForLoop` ported. The stream-wait races `iterator.next()` against an `abortRace` promise so a stalled stream still times out.
- [x] 2.7 Unit tests (`appkit.test.ts`) — SSEBroadcaster (subscribe/broadcast/drop-on-full/close), EventClassifier (triarch deliverable set, non-config-phase, streaming continue, substantive-reply guard, error envelope), QueryGate (single-flight, cancel ordering), ConnectionPool (bootstrap, reuse, pool-exhausted), TurnRunner (deliverable turn end-to-end, timeout), `inputMessageForLoop`. All pass.
- [x] 2.8 Layer 0 tests in `client.test.ts` — Clean disconnect notification, Unclean abrupt close (`ws.terminate()`), reconnect re-dials, `reattachAndProbe` → `StaleLoopError` on `-32200`, concurrent RPCs route by id. All pass.

**Phase 2 outcome**: `client/typescript/src/appkit/` builds clean (`tsc --noEmit`), `tsup` build succeeds, all tests pass. The package is product-agnostic: `deliverablePhases` is config, `SessionStore` is an interface, `SSEBroadcaster` is string-keyed.

### Phase 3: TypeScript application migration (Layer 2)

**Goal**: When a TS app consuming the daemon exists, migrate its hand-rolled layer onto `appkit`, mirroring the triarch migration (IG-527 Phase 3).

**Tasks**:
- [ ] 3.1 Delete the app's hand-rolled `TriarchClient`-equivalent / bootstrap / wait helpers.
- [ ] 3.2 Reimplement the app's pool/event-processor on `appkit.ConnectionPool`/`QueryGate`/`TurnRunner`.
- [ ] 3.3 Supply the app's `deliverablePhases` and SSE vocabulary.
- [ ] 3.4 Run the app's test suite; fix regressions.

**BLOCKER (2026-06-30)**: No TypeScript application consuming the daemon client was found under `/Users/chenxm/Workspace` (only the Go `triarch` consumes `soothe-client-go`). The TS app is either not yet started in code or lives outside this workspace. Phase 3 cannot proceed until the app exists or its location is specified.

### Phase 4: New TS app on `appkit` (forcing function)

**Goal**: Build a TS app on `appkit` from day one; divergences inform whether pieces belong in `appkit` or the app.

**Tasks**:
- [ ] 4.1 New app implements `SessionStore` for its own persistence.
- [ ] 4.2 New app supplies its own `deliverablePhases` and SSE vocabulary.
- [ ] 4.3 Note any `appkit` gaps hit during build; feed back into Phase 2 or mark app-local.

**STATUS (2026-06-30)**: No second TS app consuming the daemon client was found. Phase 4 cannot proceed until the app exists or its location is specified.

## File Structure

```
client/typescript/
├── package.json                   # module @mirasoth/soothe-client
├── src/
│   ├── client.ts                  # +'disconnected' event, +reconnect(), +reattachAndProbe()
│   ├── multiplexer.ts             # NEW (Phase 1.6): pending-request/subscription routing
│   ├── errors.ts                  # +DisconnectCause, +ReconnectError, +StaleLoopError
│   ├── config.ts                  # +reconnect/backoff knobs
│   ├── protocol.ts                # unchanged (envelope codec)
│   ├── session.ts                 # unchanged
│   ├── events.ts                  # unchanged
│   ├── verbosity.ts               # unchanged
│   ├── helpers.ts                 # unchanged
│   ├── index.ts                   # +appkit re-export, +Multiplexer/errors exports
│   └── appkit/                    # NEW package (Phase 2)
│       ├── index.ts               # package appkit — re-exports
│       ├── session_store.ts       # SessionStore interface + SessionEntry/SessionMessage
│       ├── broadcaster.ts         # SSEBroadcaster (string-keyed, drop-on-full)
│       ├── classifier.ts          # EventClassifier + ClassifierConfig + ChatEventResult
│       ├── thinking_step.ts       # extractThinkingStep + default allowlist
│       ├── query_gate.ts          # QueryGate + ErrQueryBusy
│       ├── pool.ts                # ConnectionPool + PoolConfig + PooledConn
│       ├── client.ts              # ManagedClient interface + ClientFactory/BootstrapFunc
│       └── turn_runner.ts         # TurnRunner + TurnConfig + inputMessageForLoop
└── test/
    ├── client.test.ts             # +5 Layer 0 tests
    └── appkit.test.ts             # NEW (Phase 2.7): 16 appkit unit tests
```

## Implementation Details

### 1. Core `Client` — new methods (`client.ts`)

```typescript
enum DisconnectCause { Unclean = 0, Clean = 1 }

class Client extends EventEmitter {
  /** Fires exactly once on connection drop with the cause. */
  // 'disconnected' event
  isDisconnected(): boolean;
  disconnectCause(): DisconnectCause | null;

  /** Re-dials + handshakes after a drop (bounded-retry backoff). */
  reconnect(): Promise<void>;

  /** loop_reattach + subscribe(loop_events) + loop_get probe; StaleLoopError on -32200. */
  reattachAndProbe(loopID: string): Promise<void>;
}
```

### 2. Multiplexer (`multiplexer.ts`)

```typescript
class Multiplexer {
  registerRPC(id: string): { call: Promise<Record<string, unknown>>; unregister: () => void };
  registerSubscription(id: string): { push: (f) => void; done: Promise<void>; unregister: () => void };
  registerReceipt(receipt: string): { wait: Promise<Record<string, unknown>>; unregister: () => void };
  route(frame: Record<string, unknown>): boolean; // consumed=true → don't forward
  hasRPCWaiter(id: string): boolean;
}
```

**Routing rule (RFC-629 constraint #1, RFC-450 §5.2/§5.5):** `response`/`error` with `id` in pending RPCs → RPC waiter; `next`/`complete` with `id` in pending subs → subscription waiter; `receipt_response` keyed by `receipt`; everything else flows on. `requestResponse` registers *before* sending so a fast echo is not missed.

### 3. appkit components

See `src/appkit/*.ts` — each file's docstring documents its contract. The semantics mirror the Go `appkit` package (IG-527); the mechanics are TypeScript-idiomatic (`EventEmitter`, `AsyncGenerator`, `AbortSignal`, `Promise.race`).

## Testing Strategy

### Unit Tests

- **Phase 1 (core):** Clean disconnect (peer `disconnect` notification), Unclean disconnect (`ws.terminate()`), `reconnect()` re-dials against a still-listening server, `reattachAndProbe` → `StaleLoopError` on `-32200`, concurrent RPCs route by id (out-of-order responses).
- **Phase 2 (appkit):** `EventClassifier` with two `deliverablePhases` sets; `QueryGate` single-flight + cancel ordering; `ConnectionPool` acquire/reuse/exhausted against a `FakeClient` + `MemStore`; `TurnRunner` end-to-end deliverable turn + timeout against a scripted `FakeClient`.

### Integration Tests

- Gated on a live daemon (`npm run test:integration`), mirroring the Go suite. Concurrent RPCs against a real daemon; mid-session drop + reconnect + reattach against a real loop. *(Deferred until a live daemon is available in CI.)*

## Migration Notes

- **No public API break** in core `Client`; existing `requestResponse`/`subscribe` callers work unchanged (RPC now goes through the multiplexer transparently; `subscribe` keeps its resolver-queue confirmation read).
- **`appkit` is opt-in:** applications import `@mirasoth/soothe-client/appkit` (re-exported from the package root) and construct a `TurnRunner` from the components.
- **`deliverablePhases` is config, not constants:** the application passes its phase set at construction; `appkit` hardcodes none.
- **SSE is string-keyed:** the application converts from any domain key type to `string` at its own boundary.
- **Cross-language parity:** the Go and TypeScript `appkit` packages classify events, gate queries, and run turns with the same semantics; a ported application behaves identically against the same daemon (RFC-629 constraint #8).

## Verification

- [x] `npm run typecheck` clean
- [x] `npm run build` succeeds
- [x] `npm run test` green (139 passed | 27 skipped)
- [ ] `npm run test:integration` green against a live daemon (deferred — requires live daemon in CI)
- [ ] TS app builds on `appkit` end-to-end against a live daemon (Phase 4)
- [x] No `daemon_ready`/`event_batch`/`final_report_stream` strings introduced in code (per RFC-629 constraint #3)
- [x] **FIXED (2026-06-30)**: Removed all RFC-629 forbidden strings from codebase:
  - `client.ts:359`: error message "loop_subscribe" → "loop events subscription failed"
  - `config.ts:22`: comment "After loop_subscribe" → "After subscribe(method:\"loop_events\")"
  - `client.ts:829`: comment "loop_detach is modelled" → "unsubscribe by subscription id"
- [ ] RFC-629 status advanced Draft → Accepted → Implemented as phases land

## Open Questions (from RFC-629, to resolve during impl)

- Late-response-after-timeout behavior — currently log-and-drop (the mux deletes the waiter on `unregister`); confirm no goroutine/listener leak (the `_raceRPC` `once("disconnected")` listener is removed in `finally`).
- Whether to promote an `AgentQueryError{code, userFacing, detail}` type shape into `appkit` (decide when the TS app's error needs are known).
- Whether `extractThinkingStep`'s allowlist needs to be configurable for the TS app (YAGNI until confirmed; the knob already exists).

## Remaining Gaps

| Gap | Status | Blocker |
|-----|--------|---------|
| Integration tests (`npm run test:integration`) | Deferred | Requires live daemon in CI environment |
| Phase 3: TS app migration | Blocked | No TypeScript app consuming daemon client found under workspace; location unknown |
| Phase 4: New TS app on `appkit` | Blocked | Same as Phase 3 — no second TS app exists |
| RFC-629 status advancement | Pending | Phases 3–4 must land before "Implemented" status |

**Repository layout (confirmed)**: `client/typescript` is a subdirectory of the soothe monorepo (not a git submodule like `client/go`). Build output goes to `client/typescript/dist/`. Package published as `@mirasoth/soothe-client@0.1.0` on npm (no version bump yet for RFC-629 changes).

## Related Documents

- [RFC-629](../specs/RFC-629-client-appkit-architecture.md) — Client Library Core Upgrade and Appkit Architecture (Go + TypeScript)
- [RFC-450](../specs/RFC-450-daemon-communication-protocol.md) — Daemon Communication Protocol
- [RFC-614](../specs/RFC-614-unified-streaming-messaging.md) — Unified Streaming Messaging
- [RFC-403](../specs/RFC-403-unified-event-naming.md) — Unified Event Naming
- [IG-527](./IG-527-go-client-appkit.md) — Go Client Core Upgrade and Appkit Implementation (reference implementation)

---

*Generated by Platonic Coding (impl-create-guide).*
