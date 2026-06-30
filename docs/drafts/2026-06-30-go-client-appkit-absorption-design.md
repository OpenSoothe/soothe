# Go Client Appkit Absorption — Design Draft

**Date:** 2026-06-30
**Topic:** Absorb triarch's `internal/agent` adaptation layer into `client/go` so multiple Go apps reuse it instead of re-implementing the "basic tool and msg handling" boilerplate.
**Status:** Draft (pending review)

---

## 1. Problem

`client/go` is a basic WebSocket protocol-1 (RFC-450) wrapper. In a real app, more is required: a panic-safe read loop, mid-session drop detection, loop reattach + liveness probing, daemon-ready retry, concurrent request multiplexing, a per-session connection pool, single-flight query gating, cancel-before-context ordering, event→deliverable classification, and SSE fan-out.

`triarch/backend/internal/agent/` hand-rolls all of this. Critically, **it does not use `soothe.Client` at all** — it reimplements `TriarchClient` on raw `gorilla/websocket` and imports only the library's protocol/message types (`SplitSootheWirePayload`, `DecodeMessage`, `ExpandWireMessages`, `LoopNewMessage`, `EventMessage`, event constants, `WaitDaemonReady`). A second Go app has now started and is repeating the same boilerplate. The absorption question is therefore: *what should the library provide so apps stop rebuilding it?*

### Goal

Eliminate the repeated adaptation boilerplate across Go daemon clients by promoting the generic half of triarch's adaptation layer into the library, while leaving product-specific decisions in each app.

### Non-goals

- HTTP REST client (autopilot endpoints, queue-depth metrics, run stats CRUD) — still out of scope; no consumer needs it yet.
- Auth/token refresh — no consumer has it; remains the caller's job.
- Opinionated persistence schema — triarch's Postgres `ChatRegistryStore` stays in triarch.
- Product-specific deliverable namespaces hardcoded in the library.
- Triarch's legacy `executor.go` task-scanner path — triarch-specific, not absorbed.

---

## 2. Inventory: what triarch has, and the generic/domain split

| Concern (triarch file) | Generic / reusable | Triarch-domain-specific |
|---|---|---|
| Panic-safe read loop + `Disconnected()` signal (`triarch_client.go`) | ✅ core mechanics | `[TriarchClient]` log prefix |
| Loop handshake: new/reattach/subscribe, daemon-ready retry, liveness probe (`session.go`) | ✅ protocol logic | `LoopWorkspaceScope` sandbox-path semantics |
| Event→deliverable/streaming/terminal classification (`event_processor.go`, `chat_event.go`, `thinking_step.go`) | ✅ classification mechanics | deliverable namespace allowlist (`quiz`/`goal_completion`/`direct_model`), thinking-step event allowlist |
| SSE pub/sub fan-out (`broadcaster.go`) | ✅ mechanics | `gen.TaskId` key; `delta`/`complete`/`query_error` vocab |
| Connection pool + single-flight query gate + cancel-before-ctx + timeout turn loop (`pool_manager.go`) | ✅ mechanics | `ChatRegistryStore` Postgres schema; chat modes; user-facing error copy; `gen.*` types |
| Config (`triarch_config.go`), error copy (`chat_user_error.go`, `query_outcome.go`), input hints (`soothe_hints.go`), legacy executor (`executor.go`) | ❌ | ✅ all triarch |

**Key redundancy:** triarch reimplements `soothe.Client`-equivalent functionality instead of using the library. The library lacks (or lacked, when triarch forked) the features the app needed: panic-safe read loop, `Disconnected()` channel, managed `loop_reattach` + liveness probe, `daemon_ready` stopped-retry, and concurrent-safe request multiplexing.

---

## 3. Approaches considered

| | Approach | Trade-off |
|---|---|---|
| ✅ chosen | **Layered: upgrade core `Client` + extract `appkit` package** | Solves the actual cause of triarch's reimplementation (core gaps) AND extracts the now-validated app-architecture layer (pool/query/classifier/SSE) for the imminent second app. Largest scope, but the second app makes the shared shape observable, not hypothetical. |
| rejected | **Upgrade core `Client` only, defer appkit** | Correct YAGNI stance when the second app is hypothetical. Rejected because a second app has *started* and is repeating pool/query/msg-handling boilerplate *now* — deferral incurs real, ongoing cost. |
| rejected | **`appkit` only, core stays thin** | Leaves the root cause (core `Client` gaps) unaddressed; apps would still rebuild a safe client beneath the appkit. Triarch's `TriarchClient` would persist. |
| rejected | **Absorb everything including product decisions** | Bakes triarch's Postgres schema, chat modes, and deliverable namespaces into the library. Couples the thin protocol client to one app's product; violates isolation. |

**Why layered:** the second app is imminent, so appkit extraction is justified — but only the *generic* half. The classifier is included because "msg handling" is the live pain, with the deliverable namespace set made configurable so it remains a product decision expressed in config, not library policy.

---

## 4. Design

### 4.1 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  APP (triarch / new app / future apps)                      │
│  product config: deliverable namespaces, chat modes,        │
│  persistence impl (SessionStore), user-facing error copy,   │
│  SSE event vocabulary, domain types (gen.*)                 │
└───────────────▲───────────────────────────────────▲─────────┘
                │ imports                            │ imports
┌───────────────┴─────────────────┐ ┌───────────────┴──────────────┐
│  client/go/appkit               │ │  client/go (core, upgraded)  │
│  - ConnectionPool               │ │  - Client (concurrent-safe)  │
│  - QueryGate (single-flight)    │ │  - panic-safe read loop      │
│  - TurnRunner (timeout,         │ │  - Disconnected() signal     │
│      cancel-before-ctx)         │ │  - Reconnect + ReattachAndProbe│
│  - EventClassifier              │ │      (+ liveness probe)      │
│      (configurable deliverable  │ │  - readiness retry folded-in │
│       namespace set)            │ │  - pending-request multiplexer│
│  - SSEBroadcaster (string-keyed)│ │  - protocol-1 codec (unchanged)│
│  - SessionStore interface       │ │  - Send*/Request* (unchanged) │
└───────────────▲─────────────────┘ └──────────────────────────────┘
                │ builds on
└───────────────┴──── core Client + protocol types
```

### 4.2 Layer 0 — Core `Client` upgrades (transport/lifecycle)

Additive only; existing API surface preserved (the existing test suite pins it).

1. **Panic-safe read loop.** `ReceiveMessages` recovers from bufio panics raised when `Close()` runs concurrently, matching triarch's `triarch_client.go` read loop. Today a concurrent close can panic the reader.
2. **`Disconnected() <-chan struct{}`.** A channel closed exactly once when the connection drops (read error, write error, peer close, or a missed `pong` per RFC-450 §8.3 dead-connection detection). The signal distinguishes *clean* drops (`disconnect` notification — loops keep running) from *unclean* drops (crash/network — in-flight queries cancelled per RFC-450 §4). The library currently has *no* mid-session drop detection — its only retry is cold-start `ConnectWithRetries`.
3. **Managed `Reconnect(ctx)` + `ReattachAndProbe(ctx, loopID) error`.** Re-dial → `connection_init`/`connection_ack` handshake (bounded-retry on transient `readiness_state` `starting`/`warming`) → on `ready`, re-issue `loop_reattach` and re-`subscribe` with `method:"loop_events"` → optionally probe with `loop_get` (side-effect-free read) to detect stale loops that accept the handshake but silently drop input (triarch's `probeLoopLiveness`). New methods; `Connect`/`Close` unchanged. `ReattachAndProbe` returns a typed `*StaleLoopError` so callers can fall back to a fresh `loop_new` bootstrap. Connection-level readiness is the handshake's `readiness_state` (+ `daemon_status`); `loop_get` is a loop-scoped probe only.
4. **Readiness retry folded in.** Fold triarch's `waitForDaemonReadyWithRetry` into the library's handshake — bounded retry on transient `readiness_state` (`starting`/`warming`) and Warn-severity error codes (`DAEMON_STARTING` -32001, `DAEMON_BUSY` -32002, `DAEMON_DEGRADED` -32003), per RFC-450 §4 and §7.3. (`daemon_ready` is gone in protocol-1; it is subsumed by the `connection_init`/`connection_ack` handshake.)
5. **Concurrent-safe multiplexing.** Internal pending-request and pending-subscription tables; the reader routes each inbound frame by `(type, id)` — not by "has id." `response`/`error` (request's `id`) → RPC waiter; `next`/`complete` (subscription's `id`) → subscription-stream waiter; `receipt_response` (keyed by `receipt`) → receipt waiter; `ping`/`pong`/`connection_ack` → lifecycle handlers. This makes `Client` safe for concurrent use by the pool. `Client` is currently documented "NOT safe for concurrent use" and `RequestResponse` *skips and discards* non-matching events — a showstopper for pooled use.

   **Risk note:** the multiplexer changes the read loop's event-routing contract and is the riskiest piece of core work. RFC-450 §9.3 guarantees `response` arrives before `next` stream events for a given turn, so the RPC waiter is satisfied before stream events begin — consistent with the single-flight gate. Existing `ReceiveMessages` semantics are preserved for genuinely unsolicited/lifecycle frames; solicited responses now route to waiters instead of being discarded.

### 4.3 Layer 1 — `client/go/appkit` package (the absorption target)

New package, single import path, consumed by triarch and the new app.

- **`ConnectionPool`** — acquire/release/health-check/reuse per logical session. Extracted from triarch's `pool_manager.go` mechanics. Persistence is abstracted behind a `SessionStore` interface (see below) so triarch plugs in Postgres and the new app plugs in whatever it has (in-memory, Redis, etc.).
- **`QueryGate`** — single-flight per-session query gate (`ErrQueryBusy`) plus the cancel-before-context ordering: send `command_request{command:"cancel"}` to the daemon *before* cancelling the local context, on a detached 10s-timeout context so caller cancel cannot block the wire send. Extracted from triarch's `AcquireQuery`/`CancelQuery`/`sendLoopCancelCommand`.
- **`TurnRunner`** — the timeout-bounded turn loop: build `loop_input` → `Client.SendMessage` → select on eventCh/timeoutCtx → classify each event → accumulate → resolve deliverable → persist-or-broadcast. This is the "msg handling" the new app is repeating. Extracted from triarch's `ExecuteQuery`.
- **`EventClassifier`** — `ProcessChatEvent` logic, but the **deliverable signal set is configurable**. Per RFC-614 / RFC-403 (verified): on-wire streamed chunks are `type:"next"` frames with `payload.mode="messages"` + a `phase` field for loop-tagged assistant answers (NOT `ai_chunk`/`message_chunk`); stream termination is `type:"complete"` (or `error`). There is no `event_batch` wire frame ("batch" is a `stream_delivery` *mode*, not a coalescing envelope) and no `final_report` wire frame (`final_report` is a namespace/component name). Classification keys on `(namespace, mode, phase)`, not the `output.*` namespace alone — IG-317 removed `soothe.output.*` assistant bodies, so core-loop answers ride `mode="messages"` + `phase`. Apps pass their `DeliverablePhases` set at construction (triarch passes `{quiz, goal_completion, direct_model}`); the streaming/terminal/`IsSubstantiveAssistantReply` (min-8-rune) mechanics stay library-owned. `ExtractThinkingStep`'s event allowlist is made configurable for the same reason.
- **`SSEBroadcaster`** — rekeyed from `gen.TaskId` to `string`, otherwise unchanged. Triarch converts `chatID ↔ gen.TaskId` at its own boundary.
- **`SessionStore` interface** — the persistence seam: `GetSession(sessionID)`, `CreateSession(workspaceID, sessionID, loopID, sessionType)`, `UpdateLastUsed`, `IncrementResetCount`, `GetLoopIDForSession`, `AppendMessage`. Triarch's `ChatRegistryStore` is its Postgres impl; the new app provides its own.

### 4.4 Layer 2 — stays in each app (not absorbed)

- Triarch's `gen.*` domain types, Postgres `ChatRegistryStore` impl, chat modes (`ask`/`agent`), studio activities (deep-research/summarize), user-facing error copy strings, `executor.go` legacy task path, `LoopWorkspaceScope` sandbox-path convention.
- The new app's own domain types, persistence, and product config.

### 4.5 Data flow (a query, after absorption)

```
App calls TurnRunner.Execute(ctx, sessionID, message, attachments, opts)
  → ConnectionPool.Acquire(ctx, sessionID, workspaceID, userID)
      reuses an active slot, or bootstraps (loop_new + subscribe[loop_events]) /
      reattaches (loop_reattach + subscribe[loop_events] + ReattachAndProbe) via core Client
  → QueryGate.Acquire(sessionID)        // single-flight; ErrQueryBusy if busy
  → build loop_input map
  → Client.SendMessage(ctx, loop_input) // fire-and-forget notification (or request w/ receipt)
  → select on eventCh / timeoutCtx.Done()
      for each frame from Client.ReceiveMessages (panic-safe, multiplexed by (type,id)):
        EventClassifier.Classify(msg, app.deliverablePhases) → ChatEventResult
        (next[mode=messages] → accumulate/stream; complete → terminal)
      on deliverable:
        SessionStore.Persist(sessionID, role, content, metadata)
        SSEBroadcaster.Broadcast(sessionID, complete)
  → QueryGate.Release(sessionID)
on cancel:   QueryGate.Cancel(sessionID)  // daemon-cancel before local ctx cancel
on drop:     Client.Disconnected() fires → pool marks slot stale → next Acquire reattaches
on stale:    ReattachAndProbe returns *StaleLoopError → Acquire falls back to fresh bootstrap
```

### 4.6 Error handling

- **Core:** keep `*ConnectionError` / `*DaemonError` / `*TimeoutError`; add `*ReconnectError` and `*StaleLoopError` (from the liveness probe).
- **Appkit:** promote `ErrQueryBusy` / `ErrPoolExhausted` / `ErrQueryTimeout` (triarch's sentinels). The `AgentQueryError{Code, UserFacing, Detail}` *type shape* is promoted to appkit (the user-facing-detail split is generally useful), but the *copy strings* stay in each app.
- No bare `except:`/`catch-all`; structured errors throughout.

### 4.7 Testing

- **Core:** extend the existing mock-WS unit tests for: panic-safe read loop under concurrent close; `Disconnected()` signal on drop; `Reconnect`+`ReattachAndProbe` re-handshake/resubscribe/probe; `daemon_ready` stopped-retry; and the multiplexer regression — two concurrent `RequestResponse` calls with out-of-order responses both resolve correctly, and unsolicited events still flow on `ReceiveMessages`.
- **Appkit:** unit tests for `ConnectionPool`/`QueryGate`/`TurnRunner`/`EventClassifier` against a fake `Client` interface + in-memory `SessionStore`. A configurable-namespace classifier test proving triarch's set and the new app's set both classify correctly. Cancel-before-context ordering verified (daemon receives cancel before local ctx cancels). Integration tests stay gated on a live daemon (`make test-integration`).
- **Migration regression:** triarch's existing agent-package tests must pass unchanged against the appkit-backed implementation.

---

## 5. Sequencing & scope

This is substantial work. Recommended order:

1. **Core `Client` upgrades** — panic-safe read loop, `Disconnected()`, `Reconnect`/`ReattachAndProbe`, daemon-ready retry, multiplexer. Ship as additive, keep existing tests green. The multiplexer is the highest-risk piece; land it with the concurrent-RPC regression test.
2. **`appkit` package** — extract `ConnectionPool`/`QueryGate`/`TurnRunner`/`EventClassifier`/`SSEBroadcaster`/`SessionStore` from triarch, de-domain-ify (rekey SSE to string, make deliverable-namespace configurable, abstract persistence behind `SessionStore`).
3. **Triarch migration** — delete `TriarchClient`, `bootstrap*ThreadSession`, `wait*`; reimplement `pool_manager`/`event_processor` on appkit; keep `executor.go`, `gen.*`, Postgres store, chat modes, error copy. Triarch's agent-package tests must stay green.
4. **New app on appkit from day one** — the forcing function that proves the abstraction. Where the new app's needs diverge from triarch's, that divergence informs whether a piece belongs in appkit or app.

Sequencing is core-first because appkit depends on a safe, concurrent, reconnect-aware `Client`. Triarch migration is last because it is the integration proof.

---

## 6. Open questions / risks

- **Multiplexer contract change.** Routing solicited responses to waiters while keeping unsolicited events on `ReceiveMessages` must be specified precisely to avoid starving the event stream. Resolution: define the routing rule in the RFC (responses with a request id go to the waiter; everything else flows on the channel) and pin it with the concurrent-RPC regression test.
- **`BootstrapLoopSession` vs managed reattach.** The library's existing `BootstrapLoopSession` and triarch's `bootstrap*ThreadSession` differ. The RFC must reconcile: `BootstrapLoopSession` becomes the library's owned entry point, `ReattachAndProbe` the resume path, both used by appkit's `ConnectionPool.Acquire`.
- **Thinking-step allowlist configurability.** Promoting `ExtractThinkingStep`'s event allowlist to config is proposed; confirm the new app actually needs different thinking-step events before adding the knob (YAGNI within the extraction).
- **`AgentQueryError` promotion.** Confirm the new app wants the user-facing/detail split before promoting the type; otherwise leave it triarch-local.

---

## 7. Post-draft routing (to be chosen after review)

Per Platonic Coding brainstorm, the draft is not assumed to spawn a new RFC automatically. `docs/specs/` and `docs/impl/` should be checked for related RFCs/IGs (e.g. the daemon protocol RFC, RFC-450, any client-library RFC) before choosing a path: update an existing RFC, create a new RFC, update an existing IG, or create a new IG.
