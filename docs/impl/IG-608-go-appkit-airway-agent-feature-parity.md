# IG-608: Go Appkit Parity — Migrate mizar-airway Agent Enhancements

**Guide**: IG-608  
**Title**: Port battle-tested turn-lifecycle features from mizar-airway `internal/agent` into `soothe-client-go` / `appkit`  
**Created**: 2026-07-15  
**Related RFCs**: RFC-629 (Client Appkit Architecture), RFC-614 (Unified Streaming Messaging), RFC-403 (Unified Event Naming)  
**Predecessor**: [IG-527](../archive/impl/IG-527-go-client-appkit.md) (appkit extraction), [SIL-02](../../client/go/docs/impl/) / mizar-airway SIL-02 notes (v0.2.4 phase set), [IG-532](../archive/impl/IG-532-daemon-intent-hint-direct-model-turns.md)  
**Source analysis**: mizar-airway `internal/agent` vs `client/go` (2026-07-15)  
**Scope**: `client/go/appkit/**`, small helpers in `client/go/` (Layer 0/1); mizar-airway Layer-2 thinning is a follow-up phase  
**Status**: Implemented (2026-07-15)

---

## Overview

mizar-airway’s `internal/agent` adapter talks to the daemon via low-level `soothe.Client` and **reimplements** much of `appkit` (`TurnRunner` + `EventClassifier` + session-scoped connection), while also carrying enhancements that appkit still lacks. This guide migrates the **general-purpose** gaps upstream so airway (and other Go apps) can thin onto `appkit` without losing reliability.

### Principle

| Layer | Belongs in soothe-client-go | Stays in product (airway) |
|-------|----------------------------|---------------------------|
| 0/1 | Idle watchdog, status-idle completion option, metadata skip, image compaction helper, soft stream-close policy, teardown drain helpers, phase-set hygiene | RFC-002 SSE names (`chat.*`), error codes (`SOOTHE_DOWN`, …), empty ack delta, `data_base64`→`data` reshape, gateway WaitGroup ownership |

Do **not** copy `Adapter` wholesale. Extend `TurnConfig` / `ClassifierConfig` / helpers and keep defaults backward-compatible for triarch.

---

## Problem Summary

| Gap ID | Local behavior (airway) | Current appkit / client | Risk if not migrated |
|--------|-------------------------|-------------------------|----------------------|
| G1 | `WithIdleTimeout` + reset-on-event; attachment floor 90s | Absolute `QueryTimeout` only | Hung SSE when daemon goes silent mid-turn |
| G2 | `StatusResponse{state:idle}` + non-empty content → turn complete | Classifier always `Continue` on status | Direct-model turns may never complete under appkit |
| G3 | `isMetadataMap` skips `{loop_id,latest_seq}` | No skip | False-positive content / noise |
| G4 | `compactAttachment` (max dim 768, Lanczos, JPEG Q=85) | Attachments opaque | Large vision payloads slow every consumer |
| G5 | Soft event-channel close → partial success | Stream close → error | Apps diverge on Close/reconnect UX |
| G6 | Non-blocking Close + WaitGroup drain | Gate cancel only; no drain API | DELETE-while-Chat races / orphaned WS use |
| G7 | Local `isDeliverablePhase` includes `plan_direct` | `DefaultDeliverablePhases` correctly **omits** it; `isLoopAssistantPhase` **includes** it | Airway may end turns early on next-action narration (regression risk) |

**Clarification (G7):** `plan_direct` is streamable assistant **narration**, not a final deliverable. Upstream `DefaultDeliverablePhases` must **not** gain `plan_direct`. Airway should drop it from its terminal allowlist when thinning (see Phase 4).

---

## Prerequisites

- [ ] `client/go` builds; `go test ./...` green (unit)
- [ ] IG-527 Phase 2 appkit surface present (`TurnRunner`, `EventClassifier`, `QueryGate`, `ConnectionPool`)
- [ ] Reference implementation readable: mizar-airway `internal/agent/{soothe_agent.go,attachment.go,eventloop_test.go,attachment_test.go}`
- [ ] No change to daemon wire protocol required

---

## Implementation Plan

### Phase 0: Hygiene — phase sets (no API break)

**Goal**: Document and enforce the two-set model; fix comments / defaults if drift exists.

**Tasks**:
- [ ] 0.1 Document in `intent_hints.go` / `appkit/doc.go`: **Loop assistant phases** (text extractable) ⊇ **Deliverable phases** (turn-ending). `plan_direct` ∈ loop-assistant only.
- [ ] 0.2 Confirm `DefaultDeliverablePhases()` does **not** include `plan_direct` (already true — add a unit assertion so it cannot regress).
- [ ] 0.3 Confirm `isLoopAssistantPhase` retains `plan_direct` (text extraction / `LoopAIMessage`).
- [ ] 0.4 Add `TestDefaultDeliverablePhases_ExcludesPlanDirect` and `TestIsLoopAssistantPhase_IncludesPlanDirect`.

**Exit**: Phase-set contract locked by tests.

---

### Phase 1: Idle-timeout watchdog (G1)

**Goal**: Optional silence watchdog on `TurnRunner`, independent of absolute query timeout.

**API sketch** (`appkit/turn_runner.go`):

```go
type TurnConfig struct {
    QueryTimeout time.Duration // existing; default 30m

    // IdleTimeout is the maximum silence between consecutive classified
    // events. Zero disables (default). Each received event resets the timer.
    IdleTimeout time.Duration

    // MinIdleTimeoutWithAttachments, when > 0, raises IdleTimeout for a
    // turn that has attachments if IdleTimeout is positive but below this
    // floor (airway uses 90s for image_to_text gaps). Zero = no floor.
    MinIdleTimeoutWithAttachments time.Duration
}

// New sentinel (or wrap) when idle fires:
var ErrIdleTimeout = errors.New("appkit: idle timeout")
```

**Behavior**:
1. On `Execute`, compute `idleForTurn` = `IdleTimeout`, optionally raised by attachment floor.
2. If `idleForTurn > 0`, arm `time.NewTimer`; on each event arm, `Reset`.
3. On fire: prefer daemon cancel (same as query timeout), then `onError` / `broadcastError` with `ErrIdleTimeout` **by default**.
4. Optional later: `IdleTimeoutMode SoftComplete` — persist/broadcast accumulated content as success (airway’s `chat.done` + `IDLE_TIMEOUT` code stays Layer 2 via `onError`/`onComplete` hooks mapping).

**Tasks**:
- [ ] 1.1 Extend `TurnConfig` + wire timer into `Execute` select.
- [ ] 1.2 Apply attachment floor when `len(attachments) > 0`.
- [ ] 1.3 Export `ErrIdleTimeout`; document default = fail path (daemon cancel + error).
- [ ] 1.4 Unit tests (see Testing Strategy § Idle).

**Exit**: Idle silence ends a turn under test with a fake event channel; attachment floor covers 90s case.

---

### Phase 2: Classifier enhancements (G2, G3)

**Goal**: Status-idle completion (opt-in) + subscription-metadata skip.

**API sketch** (`appkit/classifier.go`):

```go
type ClassifierConfig struct {
    DeliverablePhases   map[string]bool
    MinDeliverableRunes int
    ThinkingStepEvents  map[string]bool

    // TreatStatusIdleAsComplete: when true, StatusResponse with State=="idle"
    // and non-empty accumulated assistant text is ChatEventDeliverableComplete.
    // Default false (triarch / current behavior).
    TreatStatusIdleAsComplete bool
}
```

**Behavior**:
1. `StatusResponse` branch: if `TreatStatusIdleAsComplete && state == "idle" && IsSubstantiveAssistantReply(accumulated)` → deliverable with `CompletionEvent: "status.idle"` (or similar stable string); else continue.
2. Before treating a data map as content: if it looks like `{loop_id, latest_seq}` only (both keys present, no text fields), return Continue / empty content.

**Tasks**:
- [ ] 2.1 Add `TreatStatusIdleAsComplete` + status branch.
- [ ] 2.2 Add `isSubscriptionMetadataMap` helper; use in content extract paths.
- [ ] 2.3 Unit tests (see Testing Strategy § Classifier).

**Exit**: Existing classifier tests still pass with default config; opt-in idle tests green.

---

### Phase 3: Attachment compaction helper (G4)

**Goal**: Optional pre-send image downscale; no forced dependency change for apps that skip it.

**Placement**: Prefer `appkit/attachments.go` (or `soothe/attachments.go` if kept Layer 0). Use stdlib + a compact image lib only if already acceptable for the module; otherwise implement with `image`, `image/jpeg`, `image/png` + a small resample (document dependency decision in PR).

**API sketch**:

```go
type CompactImageOptions struct {
    MaxDim  int // default 768
    JPEGQuality int // default 85
}

// CompactImageAttachment downscales image/* payloads when either dimension
// exceeds MaxDim. Non-images and decode failures pass through unchanged.
func CompactImageAttachment(mimeType, dataB64 string, opts *CompactImageOptions) (outMime, outB64 string)

// CompactAttachments applies CompactImageAttachment to each {mime_type, data} map.
func CompactAttachments(atts []map[string]interface{}, opts *CompactImageOptions) []map[string]interface{}
```

**Tasks**:
- [ ] 3.1 Implement helper + defaults matching airway (`768`, Q=85, PNG stay / else JPEG).
- [ ] 3.2 Optional `TurnRunner` config `CompactAttachmentsBeforeSend bool` (default false) calling helper before `buildInput`.
- [ ] 3.3 Unit tests with synthetic large JPEG (see Testing Strategy § Attachments).

**Exit**: Large image shrinks; small / non-image passthrough; opt-in TurnRunner path covered.

---

### Phase 4: Stream-close & teardown policies (G5, G6)

**Goal**: Configurable stream-close semantics; documented drain-friendly teardown.

**API sketch**:

```go
type StreamClosePolicy int
const (
    StreamCloseFail StreamClosePolicy = iota // default: current behavior
    StreamCloseSoftComplete                  // treat accumulated content as success if any
)

type TurnConfig struct {
    // ...
    OnStreamClose StreamClosePolicy
}
```

**ConnectionPool / session teardown** (minimal):
- [ ] 4.1 Document recommended ordering: `QueryGate.Cancel` → wait for `Execute` return (caller WaitGroup) → `pool.Release` / client `Close`.
- [ ] 4.2 Optional helper `DrainAndClose(ctx, sessionID, timeout)` on pool **only if** a clean API fits without exporting airway’s `Add`/`Done`. Prefer documenting + example over a leaky API.
- [ ] 4.3 Unit test: soft-complete path when eventCh closed after partial text; fail path remains default.

**Exit**: Soft-complete is opt-in; default apps unchanged.

---

### Phase 5: mizar-airway consumer thinning (Layer 2 — separate PR / companion IG)

**Goal**: Replace hand-rolled `eventLoop` with `TurnRunner` + local SSE mapping. Tracked for airway as **IG-007** (companion).

**Tasks** (airway repo):
- [ ] 5.1 Bump `soothe-client-go` to version containing Phases 0–4.
- [ ] 5.2 Wire `EventClassifier` with `TreatStatusIdleAsComplete: true`, airway deliverable phases **without** `plan_direct`.
- [ ] 5.3 Map `ErrIdleTimeout` / `ErrQueryTimeout` → RFC-002 codes (`IDLE_TIMEOUT`, `SOOTHE_TIMEOUT`, …) in gateway handlers / publish callback.
- [ ] 5.4 Keep Layer-2-only: empty ack `chat.delta`, `data_base64` reshape, SSE type names.
- [ ] 5.5 Delete or shrink local `extractTextDelta` / `isTerminalEvent` / idle arm once parity proven; keep integration tests green.
- [ ] 5.6 Fix: remove `plan_direct` from local `isDeliverablePhase` even before full appkit adoption (bugfix can ship early).

**Exit**: airway agent package tests green; behavior parity for idle / status-idle / attachments documented.

---

## Testing Strategy (essential — anti-regression)

Port the **intent** of mizar-airway tests; do not depend on `api.Event` or HTTP.

### Phase 0 — Phase sets

| Test | Assert |
|------|--------|
| `TestDefaultDeliverablePhases_ExcludesPlanDirect` | `"plan_direct"` not in map |
| `TestDefaultDeliverablePhases_IncludesDirectHints` | `text_completion`, `image_to_text`, `ocr`, `embed`, `goal_completion`, `quiz` present |
| `TestIsLoopAssistantPhase_IncludesPlanDirect` | `LoopAIMessage` / phase helper accepts `plan_direct` for text extract |

### Phase 1 — Idle timeout (`appkit_test.go` or `turn_runner_idle_test.go`)

| Test | Assert |
|------|--------|
| `TestTurnRunner_IdleTimeout` | No events after send → `ErrIdleTimeout` within ~idle duration |
| `TestTurnRunner_IdleTimeoutResetsOnEvent` | Events spaced &lt; idle keep turn alive until deliverable |
| `TestTurnRunner_IdleDisabledByDefault` | `IdleTimeout=0` does not fire; only query timeout / deliverable |
| `TestTurnRunner_IdleFloorWithAttachments` | Config idle 30ms + floor 90ms + attachments → wait ≥ floor before idle fail (use shortened floor in test, e.g. 50ms) |
| `TestTurnRunner_IdleNotFiredOnDeliverable` | Deliverable before idle → success, no `ErrIdleTimeout` |

### Phase 2 — Classifier

| Test | Assert |
|------|--------|
| `TestClassifier_StatusIdleAfterContent_OptIn` | idle + accumulated text → DeliverableComplete when flag true |
| `TestClassifier_StatusIdleNoContent_Ignored` | idle + empty accumulated → Continue |
| `TestClassifier_StatusIdle_DefaultOff` | flag false → Continue even with content |
| `TestClassifier_SkipsSubscriptionMetadataMap` | `{loop_id, latest_seq}` does not become content |
| `TestClassifier_PlanDirect_NotDeliverableByDefault` | phase `plan_direct` with text → Continue (or stream only), not DeliverableComplete under `DefaultDeliverablePhases` |
| `TestClassifier_GoalCompletion_Deliverable` | regression: `goal_completion` still completes |

### Phase 3 — Attachments

| Test | Assert |
|------|--------|
| `TestCompactImageAttachment_DownscalesLarge` | Synthetic image &gt; max dim → smaller base64; mime jpeg/png rules |
| `TestCompactImageAttachment_PassthroughSmall` | Both dims ≤ max → identical payload |
| `TestCompactImageAttachment_PassthroughNonImage` | `audio/*` / empty → unchanged |
| `TestCompactImageAttachment_BadBase64` | Decode fail → passthrough |

### Phase 4 — Stream close

| Test | Assert |
|------|--------|
| `TestTurnRunner_StreamClose_DefaultFail` | close ch mid-turn → error |
| `TestTurnRunner_StreamClose_SoftComplete` | policy soft + partial text → onComplete with content, nil error |

### Race / concurrency (existing + new)

- [ ] All new tests pass under `go test -race ./appkit/...`
- [ ] Keep `QueryGate` cancel-ordering tests green
- [ ] Optional: pool Release after Cancel during in-flight Execute does not panic (document caller WaitGroup)

### Source mapping (airway → upstream)

| Airway test | Upstream target |
|-------------|-----------------|
| `TestEventLoop_IdleTimeout` / `TestIdleTimeoutEmitsChatDone` | `TestTurnRunner_IdleTimeout` (+ Layer-2 maps code) |
| `TestIdleTimeoutResetsOnEvent` | `TestTurnRunner_IdleTimeoutResetsOnEvent` |
| `TestIdleTimeoutDisabledByDefault` | `TestTurnRunner_IdleDisabledByDefault` |
| `TestEventLoop_StatusIdleAfterContent` | `TestClassifier_StatusIdleAfterContent_OptIn` |
| `TestEventLoop_StatusIdleNoContent` | `TestClassifier_StatusIdleNoContent_Ignored` |
| `attachment_test.go` | `TestCompactImageAttachment_*` |
| (new) plan_direct terminal bug | `TestClassifier_PlanDirect_NotDeliverableByDefault` + airway Phase 5.6 |

---

## Non-goals

- Migrating RFC-002 SSE event type strings into appkit
- Auto-reconnect backoff loop using unused Config fields (separate IG)
- Changing daemon phase tagging or RFC-614 emission
- Forcing all apps onto soft-complete or status-idle (both opt-in)
- Adding `plan_direct` to `DefaultDeliverablePhases`

---

## Default compatibility matrix

| Option | Default | Triarch / pre-IG-608 | Airway recommended |
|--------|---------|----------------------|--------------------|
| `IdleTimeout` | 0 (off) | unchanged | 30s (config) |
| `MinIdleTimeoutWithAttachments` | 0 | unchanged | 90s |
| `TreatStatusIdleAsComplete` | false | unchanged | true |
| `CompactAttachmentsBeforeSend` | false | unchanged | true |
| `OnStreamClose` | Fail | unchanged | SoftComplete (optional) |
| Deliverable phases | `DefaultDeliverablePhases()` | keep | same + **no** `plan_direct` |

---

## Verification

- [ ] `go vet ./...` and `go test -race ./...` in `client/go`
- [ ] New idle / status-idle / compact / soft-close / phase-set tests listed above all present and green
- [ ] README or `appkit/doc.go` documents new TurnConfig / ClassifierConfig knobs
- [ ] Tag / publish soothe-client-go (user-authorized)
- [ ] Airway IG-007 bump + thinning (Phase 5) or at least `plan_direct` terminal fix

---

## Related Documents

- [RFC-629](../specs/RFC-629-client-appkit-architecture.md) — Appkit layers
- [RFC-614](../specs/RFC-614-unified-streaming-messaging.md) — `messages` + `phase`
- [IG-527](../archive/impl/IG-527-go-client-appkit.md) — Appkit extraction
- [IG-532](../archive/impl/IG-532-daemon-intent-hint-direct-model-turns.md) — Direct-model phases
- [IG-578](./IG-578-goal-completion-display-fix.md) — Why `plan_direct` must not mix into final answers
- mizar-airway: `internal/agent/soothe_agent.go`, `attachment.go`, companion **IG-007**

---

*Generated from mizar-airway ↔ soothe-client-go feature-parity analysis (2026-07-15).*
