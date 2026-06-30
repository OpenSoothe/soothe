# IG-527: Go Client Core Upgrade and Appkit Implementation

**Guide**: IG-527
**Title**: Upgrade `client/go` core `Client` and extract `appkit` package from triarch
**Created**: 2026-06-30
**Related RFCs**: RFC-629 (Client Library — Core Upgrade and Appkit Architecture), RFC-450 (Daemon Communication Protocol), RFC-614 (Unified Streaming Messaging), RFC-403 (Unified Event Naming)
**Scope**: `client/go/**` (core upgrades) + new `client/go/appkit/` package; triarch `internal/agent/` migrates to consume both.
**Status**: In Progress — Phase 1 (core `Client` upgrades) complete 2026-06-30; Phase 2 (`appkit` package) complete 2026-06-30; Phases 3–4 blocked on a client-library publish (see Phase 3 notes).

## Overview

This guide implements the Go half of RFC-629 (the TypeScript half is IG-531). It folds triarch's hand-rolled transport/lifecycle layer down into the core `Client` (Layer 0) and extracts triarch's reusable application mechanics into a new `client/go/appkit` package (Layer 1). Product-specific code stays in triarch (Layer 2).

The work is sequenced core-first because `appkit` depends on a safe, concurrent, reconnect-aware `Client`. The multiplexer is the highest-risk piece; it changes the read loop's event-routing contract and must preserve the existing `ReceiveMessages` semantics for unsolicited frames.

## Prerequisites

- [ ] RFC-629 in Draft (or Accepted) status — currently Draft
- [ ] `client/go` at module `github.com/mirasoth/soothe-client-go`, Go ≥1.25, deps `gorilla/websocket`, `google/uuid`
- [ ] IG-525 work complete (protocol-1 migration) — confirmed Done; this guide builds on it
- [ ] triarch `internal/agent/` importable for reference during extraction
- [ ] Live daemon available for integration tests (`make test-integration`)

## Implementation Plan

### Phase 1: Core `Client` transport/lifecycle upgrades (Layer 0)

**Goal**: Make `Client` safe, concurrent, and reconnect-aware. All changes additive — existing `Client`/`Send*`/`Request*` signatures preserved.

**Tasks**:
- [x] 1.1 Panic-safe read loop — `recover()` in `ReceiveMessages` around `ReadMessage`. *(Already present in existing `client.go`; confirmed, not redone.)*
- [x] 1.2 `Disconnected() <-chan DisconnectCause` — buffered-1 channel delivering the cause then closed; clean = `disconnect` notification (RFC-450 §9.2), unclean = read/write error (§8.3) or explicit `Close()`. Wired into read loop, `SendMessage` write errors, `isControlFrame`, and `Close`.
- [x] 1.3 Readiness retry in `handshake()` — `starting`/`warming` retry *(already present)* **plus** Warn-severity error-code retry (`DAEMON_STARTING` -32001, `DAEMON_BUSY` -32002, `DAEMON_DEGRADED` -32003) via `isRetryableWarnCode`.
- [x] 1.4 `Reconnect(ctx) error` — tears down stale socket quietly (no redundant signal) and re-dials via `Connect`, which resets `disconnCh`/`disconnOnce`/`mux`.
- [x] 1.5 `ReattachAndProbe(ctx, loopID) error` — `loop_reattach` + `LoopSubscribe` (`loop_events`) + `loop_get` probe; returns `*StaleLoopError` on `LOOP_NOT_FOUND` (-32200) or probe timeout/ error.
- [x] 1.6 **Multiplexer** — `multiplexer.go` with `pendingCall`/`pendingSubscription` tables, route by `(type, id)`. `RequestResponse` registers a pending call; when a `ReceiveMessages` reader is active (`readerActive` atomic), it waits purely on the mux channels (gorilla forbids concurrent readers); otherwise it falls back to synchronous `ReadEvent` (which itself routes other waiters' frames). Added `ReconnectError`, `StaleLoopError`, `DisconnectCause` to `errors.go`; reconnect knobs to `config.go`.
- [ ] 1.7 Client-initiated `ping` keepalive (optional) — deferred; not needed for triarch migration.

### Phase 2: `appkit` package extraction (Layer 1)

**Goal**: Extract triarch's reusable mechanics into `client/go/appkit/`, de-domain-ified.

**Tasks**:
- [x] 2.1 `SessionStore` interface (`session_store.go`) — abstracts triarch's `ChatRegistryStore`; `SessionEntry` + `SessionMessage`.
- [x] 2.2 `SSEBroadcaster` (`broadcaster.go`) — rekeyed from `gen.TaskId` to `string`; drop-on-full; Subscribe/Unsubscribe/Broadcast/Close/CloseAll.
- [x] 2.3 `EventClassifier` (`classifier.go` + `thinking_step.go`) — `ProcessChatEvent` ported with configurable `DeliverablePhases`; keys on `(namespace, mode, phase)`; `IsSubstantiveAssistantReply`, `ResolveDeliverableFinalContent`, `ExtractThinkingStep` (allowlist configurable, defaults to triarch's set). Adapted to the current `soothe` package (uses `soothe.Envelope` for protocol-1 acks, since the legacy `LoopSubscribeResponse`/etc. types were removed in the protocol-1 migration).
- [x] 2.4 `QueryGate` (`query_gate.go`) — single-flight (`ErrQueryBusy`) + cancel-before-context (daemon cancel on a detached 10s ctx before local cancel).
- [x] 2.5 `ConnectionPool` (`pool.go`) — acquire/release/reuse/Stop; bootstrap (`loop_new`+subscribe via `BootstrapFunc`) or reattach (`Connect`+`ReattachAndProbe`); falls back to fresh bootstrap on `*StaleLoopError`. `ManagedClient` interface + `ClientFactory`/`BootstrapFunc` for testability.
- [x] 2.6 `TurnRunner` (`turn_runner.go`) — timeout turn loop: acquire → gate → send `loop_input` → classify → resolve deliverable → persist + broadcast; timeout/cancel/event-stream-closed/failed-event paths; `onComplete`/`onError` hooks; `InputMessageForLoop` ported.
- [x] 2.7 Unit tests (`appkit_test.go`) — SSEBroadcaster (subscribe/broadcast/drop-on-full/close), EventClassifier (triarch deliverable set, non-config-phase not deliverable, streaming continue, substantive-reply guard), QueryGate (single-flight, cancel ordering), ConnectionPool (bootstrap, reuse), TurnRunner (deliverable turn end-to-end, timeout). All pass under `-race`.

**Phase 2 outcome**: `client/go/appkit/` builds clean (`go vet`/`go build`), all tests pass under `-race`, `gofmt` clean, `./scripts/verify_finally.sh` "All checks passed". The package is product-agnostic: `DeliverablePhases` is config, `SessionStore` is an interface, `SSEBroadcaster` is string-keyed.

### Phase 3: Triarch migration (Layer 2)

**Goal**: Delete triarch's hand-rolled layer; consume `appkit` + core `Client`. Triarch agent-package tests must stay green.

**Tasks**:
- [ ] 3.1 Delete `triarch_client.go` (`TriarchClient`), `session.go` (`bootstrap*ThreadSession`, `wait*`).
- [ ] 3.2 Reimplement `pool_manager.go` on `appkit.ConnectionPool`/`QueryGate`/`TurnRunner`.
- [ ] 3.3 Reimplement `event_processor.go`/`chat_event.go`/`thinking_step.go` via `appkit.EventClassifier` with triarch's `DeliverablePhases` = `{quiz, goal_completion, direct_model}`.
- [ ] 3.4 Keep `executor.go`, `gen.*`, Postgres `ChatRegistryStore` (now an `appkit.SessionStore` impl), chat modes, error copy, `LoopWorkspaceScope`.
- [ ] 3.5 Move `SootheLoopInputOpts`/`InputMessageForLoop` to triarch's app-layer config consumed by `TurnRunner`.
- [ ] 3.6 Run triarch agent-package test suite; fix regressions.

**BLOCKER (2026-06-30)**: Phase 3 requires publishing the new client library and bumping triarch onto it — both are outward-facing actions that need explicit user authorization.

Repository layout (confirmed): `client/go` is a git **submodule** of the soothe monorepo pointing at `git@github.com:mirasoth/soothe-client-go.git` (the canonical published client repo), on branch `main` at `afcb915` = `origin/main`. The standalone clone at `/Users/chenxm/Workspace/soothe-client-go` (remote `OpenSoothe/soothe-client-go`) is a separate working copy of the same lineage, currently behind the submodule. All Phase 1 + Phase 2 work is staged-but-uncommitted inside the `client/go` submodule.

Triarch (`/Users/chenxm/Workspace/triarch`) pins the published `soothe-client-go v0.1.18` (from before the protocol-1 migration); no `replace` directive. The migration therefore requires, in order:

1. **Commit + push** the Phase 1 + Phase 2 changes inside the `client/go` submodule, and **tag/publish** a new version (e.g. v0.2.0). *(User-authorized publish.)*
2. **Bump** triarch's `backend/go.mod` to the new version (or add a `replace` directive pointing at the local submodule for a trial migration without publishing).
3. Then tasks 3.1–3.6 above (the actual delete-and-reimplement of triarch's `TriarchClient`/`bootstrap*ThreadSession`/`wait*` onto `appkit`).

Step 1 modifies a published library and needs the user's go-ahead. Step 3 only compiles against the new version. Recommended next action: confirm with the user whether to (a) commit + push + publish the submodule now, (b) trial-migrate triarch via a local `replace` directive first, or (c) leave Phase 3-4 for a separate, authorized pass.

### Phase 4: New app on `appkit` (forcing function)

**Goal**: Build the second Go app on `appkit` from day one; divergences inform whether pieces belong in `appkit` or the app.

**Tasks**:
- [ ] 4.1 New app implements `SessionStore` for its own persistence.
- [ ] 4.2 New app supplies its own `DeliverablePhases` and SSE vocabulary.
- [ ] 4.3 Note any `appkit` gaps hit during build; feed back into Phase 2 or mark app-local.

**STATUS (2026-06-30)**: No second Go app consuming the daemon client was found under `/Users/chenxm/Workspace` (surveyed all sibling Go modules; only triarch consumes `soothe-client-go`). The "new app" is either not yet started in code or lives outside this workspace. Phase 4 cannot proceed until the app exists or its location is specified.

## File Structure

```
client/go/
├── go.mod                        # module github.com/mirasoth/soothe-client-go
├── client.go                     # +Disconnected(), +Reconnect(), +ReattachAndProbe(); panic-safe read loop
├── protocol.go                   # unchanged (envelope codec)
├── request.go                    # RequestResponse now uses the multiplexer (no discard)
├── send_methods.go               # unchanged
├── session.go                    # BootstrapLoopSession reconciled with ReattachAndProbe
├── heartbeat.go                  # unchanged
├── config.go                     # +reconnect/backoff knobs (consumed by Reconnect)
├── errors.go                     # +ReconnectError, +StaleLoopError
├── events.go                     # unchanged
├── verbosity.go                  # unchanged
├── job.go                        # unchanged
├── helpers.go                    # unchanged
├── multiplexer.go                # NEW (Phase 1.6): pending-request/subscription routing
└── appkit/                       # NEW package (Phase 2)
    ├── doc.go                    # package appkit
    ├── session_store.go          # SessionStore interface + SessionEntry
    ├── broadcaster.go            # SSEBroadcaster (string-keyed)
    ├── classifier.go             # EventClassifier + ClassifierConfig + ChatEventResult
    ├── query_gate.go             # QueryGate + ErrQueryBusy
    ├── pool.go                   # ConnectionPool + PoolConfig
    ├── turn_runner.go            # TurnRunner + TurnConfig
    └── fake_client.go            # test-only fake Client interface impl
```

## Implementation Details

### 1. Core `Client` — new methods (`client.go`)

```go
// DisconnectCause distinguishes clean vs unclean connection loss.
type DisconnectCause int

const (
    DisconnectUnclean DisconnectCause = iota // read/write error, missed pong (RFC-450 §8.3)
    DisconnectClean                          // received `disconnect` notification (§9.2); loops keep running
)

// Disconnected returns a channel closed exactly once when the connection drops.
// Callers must not assume loop state is preserved on DisconnectUnclean.
func (c *Client) Disconnected() <-chan DisconnectCause

// Reconnect re-dials and re-handshakes on a dropped connection. Does not
// re-establish subscriptions; follow with ReattachAndProbe for a loop session.
func (c *Client) Reconnect(ctx context.Context) error

// ReattachAndProbe resumes an existing loop: loop_reattach + subscribe(loop_events)
// + loop_get liveness probe. Returns *StaleLoopError when the loop accepts the
// reattach but fails the probe; callers should fall back to a fresh loop_new.
func (c *Client) ReattachAndProbe(ctx context.Context, loopID string) error
```

### 2. New error types (`errors.go`)

```go
type ReconnectError struct{ URL string; Attempts int; Err error }
func (e *ReconnectError) Error() string  // "reconnect failed after N attempts: <err>"
func (e *ReconnectError) Unwrap() error

type StaleLoopError struct{ LoopID string }
func (e *StaleLoopError) Error() string  // "stale loop <id>: reattach accepted but liveness probe failed"
```

### 3. Multiplexer — routing by `(type, id)` (`multiplexer.go`)

This is the riskiest change. The reader goroutine classifies each inbound frame and routes it; it must not discard solicited responses, and must still surface unsolicited/lifecycle frames on the `ReceiveMessages` channel.

```go
type frameRoute int

const (
    routeRPC frameRoute = iota        // type in {response, error} with request id
    routeSubscription                 // type in {next, complete} with subscription id
    routeReceipt                      // type == receipt_response, keyed by receipt
    routeControl                      // type in {ping, pong, connection_ack}
    routeEvent                        // everything else (unsolicited notifications, lifecycle)
)

// pendingCall is a single in-flight RPC wait.
type pendingCall struct {
    id      string
    replyCh chan<- map[string]interface{}  // result on response, nil+err on error
    errCh   chan<- error
}

// pendingSubscription is a single in-flight subscription stream.
type pendingSubscription struct {
    id      string
    streamCh chan<- interface{}  // next/complete frames
    done     chan struct{}
}

type mux struct {
    mu       sync.Mutex
    rpcs     map[string]*pendingCall
    subs     map[string]*pendingSubscription
    receipts map[string]chan<- map[string]interface{}
}

// route classifies and dispatches one decoded frame. Returns true if the frame
// was consumed by a waiter (and must NOT be forwarded to ReceiveMessages);
// false if it is an unsolicited/lifecycle frame that flows on.
func (m *mux) route(frame interface{}) (consumed bool)
```

**Routing rule (RFC-629 constraint #1, RFC-450 §5.2/§5.5):**
- `response`/`error` with `id` ∈ pending RPCs → deliver to `pendingCall.replyCh`/`errCh`; consumed.
- `next`/`complete` with `id` ∈ pending subs → deliver to `pendingSubscription.streamCh`; consumed.
- `receipt_response` with `receipt` ∈ pending receipts → deliver; consumed.
- `ping` → send `pong` (existing `sendPong`); consumed.
- `pong`, `connection_ack` → lifecycle handler; consumed.
- Everything else → not consumed; flows on `ReceiveMessages` as today.

**Ordering invariant (RFC-450 §9.3):** for a given turn, `response` arrives before any `next` stream frames, so the RPC waiter is satisfied before stream events begin — consistent with the single-flight gate.

**`RequestResponse` change:** instead of looping on `ReadEvent` and discarding non-matching events, it registers a `pendingCall` and waits on its `replyCh`/`errCh`. This makes `Client` safe for concurrent RPCs.

### 4. `appkit.SessionStore` (`session_store.go`)

```go
package appkit

type SessionEntry struct {
    WorkspaceID, SessionID, LoopID, SessionType string
    ResetCount int
    LastUsedAt time.Time
}

// SessionStore is the persistence seam. Apps implement this against their own
// store (triarch: Postgres; others: in-memory, Redis, etc.).
type SessionStore interface {
    GetSession(sessionID string) (*SessionEntry, error)
    CreateSession(workspaceID, sessionID, loopID, sessionType string) error
    UpdateLastUsed(sessionID string) error
    IncrementResetCount(sessionID string) error
    GetLoopIDForSession(sessionID string) (loopID string, ok bool, err error)
    AppendMessage(sessionID, role, content string, metadata map[string]interface{}) error
}
```

### 5. `appkit.SSEBroadcaster` (`broadcaster.go`)

```go
type SSEEvent struct{ Type string; Data interface{} }

type SSEBroadcaster struct { /* mu; subscribers map[string]map[string]chan SSEEvent */ }

func NewSSEBroadcaster() *SSEBroadcaster
func (b *SSEBroadcaster) Subscribe(sessionID string) (<-chan SSEEvent, error)   // buffered cap 100
func (b *SSEBroadcaster) Unsubscribe(sessionID string, ch <-chan SSEEvent)
func (b *SSEBroadcaster) Broadcast(sessionID string, event SSEEvent)            // non-blocking, drop on full
func (b *SSEBroadcaster) Close(sessionID string)
func (b *SSEBroadcaster) CloseAll()
```

### 6. `appkit.EventClassifier` (`classifier.go`)

```go
type ChatEventTerminal int

const (
    EventContinue ChatEventTerminal = iota
    EventDeliverableComplete
    EventFailedComplete
)

type ChatEventResult struct {
    Content, ThinkingStep string
    Terminal              ChatEventTerminal
    CompletionEvent       string
    Err                   error
}

type ClassifierConfig struct {
    DeliverablePhases   map[string]bool   // app-defined, e.g. {"quiz":true,"goal_completion":true,"direct_model":true}
    ThinkingStepEvents  map[string]bool   // optional app override; nil = library default
    MinDeliverableRunes int               // default 8 (IsSubstantiveAssistantReply)
}

type EventClassifier struct{ cfg ClassifierConfig }

func NewEventClassifier(cfg ClassifierConfig) *EventClassifier

// Classify maps one decoded frame to a ChatEventResult. Keys on
// (namespace, mode, phase) per RFC-614/RFC-403:
//   - type:"next" + payload.mode=="messages" → accumulate/stream (EventContinue)
//   - type:"complete" → terminal (EventDeliverableComplete, or EventFailedComplete if preceded by error)
//   - payload.phase in DeliverablePhases → deliverable
//   - soothe.error.* namespaces → EventFailedComplete
func (cl *EventClassifier) Classify(msg interface{}, accumulated string) ChatEventResult
```

### 7. `appkit.QueryGate` (`query_gate.go`)

```go
var ErrQueryBusy = errors.New("appkit: query already in progress for session")

type QueryGate struct { /* mu; active map[string]*queryState */ }

func NewQueryGate() *QueryGate

// Acquire enforces single-flight per session. Returns ErrQueryBusy if a query
// is already running or pending.
func (g *QueryGate) Acquire(sessionID string, cancel context.CancelFunc) error

// Cancel sends the daemon cancel BEFORE cancelling the local context, on a
// detached 10s-timeout context so caller cancel cannot block the wire send.
// (triarch IG-398 ordering: command_request{command:"cancel"} first.)
func (g *QueryGate) Cancel(ctx context.Context, sessionID string, sendCancel func(ctx context.Context) error) error

func (g *QueryGate) Release(sessionID string)
func (g *QueryGate) IsActive(sessionID string) bool
```

### 8. `appkit.ConnectionPool` (`pool.go`)

```go
type PoolConfig struct {
    PoolSize, MaxIdleTime, HealthCheckInterval, ConnectionTimeout time.Duration
    QueryTimeout time.Duration
}

type ClientFactory func(url string, cfg *soothe.Config) *soothe.Client  // injectable for tests

type ConnectionPool struct {
    cfg       PoolConfig
    factory   ClientFactory
    store     SessionStore
    // pool chan, activeSlots, registry, cancelFuncs (from triarch pool_manager.go)
}

func NewConnectionPool(cfg PoolConfig, factory ClientFactory, store SessionStore) *ConnectionPool

// Acquire reuses an active slot or bootstraps (loop_new + subscribe) / reattaches
// (loop_reattach + subscribe + ReattachAndProbe). Falls back from reattach-fail
// to fresh bootstrap. On *StaleLoopError from ReattachAndProbe, starts fresh.
func (p *ConnectionPool) Acquire(ctx context.Context, sessionID, workspaceID, userID string) (*soothe.Client, error)

func (p *ConnectionPool) Release(sessionID string)
func (p *ConnectionPool) ResetSession(sessionID string) error
func (p *ConnectionPool) Stop()
func (p *ConnectionPool) Stats() map[string]int
```

### 9. `appkit.TurnRunner` (`turn_runner.go`)

```go
type TurnConfig struct {
    Timeout time.Duration  // default 30m (triarch PoolConfig.QueryTimeout)
}

type TurnRunner struct {
    pool       *ConnectionPool
    gate       *QueryGate
    classifier *EventClassifier
    store      SessionStore
    broadcaster *SSEBroadcaster
    cfg        TurnConfig
}

func NewTurnRunner(pool *ConnectionPool, gate *QueryGate, cl *EventClassifier, store SessionStore, b *SSEBroadcaster, cfg TurnConfig) *TurnRunner

// Execute runs one query turn: acquire → gate.Acquire → build loop_input →
// SendMessage → select on event stream / timeoutCtx → classify → accumulate →
// on deliverable: store.Persist + broadcaster.Broadcast → gate.Release.
func (r *TurnRunner) Execute(ctx context.Context, sessionID, message, userID string, attachments []map[string]interface{}, opts map[string]interface{}) error
```

## Testing Strategy

### Unit Tests

- **Phase 1 (core):**
  - Panic-safe read loop: concurrent `Close()` during `ReadMessage` does not panic; `Disconnected()` fires.
  - `Disconnected()` clean vs unclean: simulate `disconnect` notification (clean) vs write error (unclean).
  - `Reconnect`+`ReattachAndProbe`: mock server drops, reconnects, reattaches, probes; `*StaleLoopError` on `LOOP_NOT_FOUND`.
  - Readiness retry: mock `connection_ack` with `readiness_state:"warming"` then `"ready"`; assert bounded retry.
  - **Multiplexer regression (critical):** two concurrent `RequestResponse` calls; responses arrive out of order; both resolve to the correct caller. Unsolicited `next`/notification frames still flow on `ReceiveMessages`. Late response after timeout is logged-and-dropped (no goroutine leak).
- **Phase 2 (appkit):**
  - `EventClassifier` with two different `DeliverablePhases` sets (triarch's + the new app's) both classify correctly; `mode:"messages"` + recognized `phase` → deliverable; `complete` → terminal; `error.*` → failed.
  - `QueryGate` single-flight: second `Acquire` returns `ErrQueryBusy`; `Cancel` calls `sendCancel` before local cancel (assert ordering with a recording fake).
  - `ConnectionPool` acquire/reuse/reattach/stale-fallback against a fake `Client` + in-memory `SessionStore`.
  - `TurnRunner` end-to-end against a fake `Client` streaming a scripted event sequence.

```go
// appkit/fake_client_test.go — minimal Client interface for unit tests
type fakeClient struct {
    // records SendMessage calls; replays a scripted stream on ReceiveMessages
}
```

### Integration Tests

- Gated on a live daemon (`make test-integration`), mirroring IG-525's suite.
- Concurrent RPCs against a real daemon (the multiplexer's real-world proof).
- Mid-session drop + reconnect + reattach against a real loop.
- Triarch migration regression: triarch's agent-package integration tests pass against the `appkit`-backed implementation.

## Migration Notes

- **No public API break** in core `Client`; existing `RequestResponse` callers work unchanged (they now go through the multiplexer transparently).
- **Triarch migration is a delete-and-reimplement**, not a parallel path: `TriarchClient`, `bootstrap*ThreadSession`, `wait*` are removed; triarch imports `appkit` + `soothe.Client`.
- **`BootstrapLoopSession` reconciliation:** the library's existing helper becomes the owned entry point used by `ConnectionPool.Acquire` for new sessions; `ReattachAndProbe` is the resume path. Remove triarch's divergent `bootstrapResumeThreadSession`.
- **`DeliverablePhases` is config, not constants:** triarch passes `{quiz, goal_completion, direct_model}` at construction; the new app passes its own. Do not hardcode these in `appkit`.
- **SSE rekeying:** triarch converts `chatID ↔ gen.TaskId` at its own boundary; `appkit.SSEBroadcaster` is string-keyed.
- **Backwards-incompatible for triarch only:** triarch's `internal/agent` package internal API changes; its external HTTP/SSE contract is unchanged.

## Verification

- [ ] `go vet ./...` clean in `client/go` and `client/go/appkit`
- [ ] `go test ./...` green (unit) in `client/go` and `client/go/appkit`
- [ ] `make test-integration` green in `client/go` (concurrent RPCs, drop+reattach)
- [ ] Triarch agent-package test suite green after migration
- [ ] New app builds on `appkit` end-to-end against a live daemon
- [ ] No `daemon_ready`/`loop_subscribe`/`loop_detach`/`event_batch`/`ai_chunk`/`final_report_stream` strings introduced in code (per RFC-629 constraint #3)
- [ ] RFC-629 status advanced Draft → Accepted → Implemented as phases land

## Open Questions (from RFC-629, to resolve during impl)

- Late-response-after-timeout behavior — specify as log-and-drop with a counter; confirm no goroutine leak.
- Whether to promote triarch's `AgentQueryError{Code, UserFacing, Detail}` type shape into `appkit` (decide when the new app's error needs are known).
- Whether `ExtractThinkingStep`'s event allowlist needs to be configurable for the new app (YAGNI until confirmed).

## Related Documents

- [RFC-629](../specs/RFC-629-client-appkit-architecture.md) — Client Library Core Upgrade and Appkit Architecture (Go + TypeScript)
- [RFC-450](../specs/RFC-450-daemon-communication-protocol.md) — Daemon Communication Protocol
- [RFC-614](../specs/RFC-614-unified-streaming-messaging.md) — Unified Streaming Messaging
- [RFC-403](../specs/RFC-403-unified-event-naming.md) — Unified Event Naming
- [IG-525](./IG-525-go-ts-clients-rfc450.md) — Go/TS Client protocol-1 migration (predecessor)

---

*Generated by Platonic Coding (impl-create-guide).*
