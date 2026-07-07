# IG-556: Stream Termination Unification

**RFCs**: [RFC-614](../specs/RFC-614-unified-streaming-messaging.md) (messages + `phase`), [RFC-450](../specs/RFC-450-daemon-communication-protocol.md) (subscription `complete` / `idle` ordering)
**Created**: 2026-07-07
**Status**: Complete
**Related**: [IG-533](IG-533-goal-completion-tui-worker-lifecycle-fixes.md), [IG-441](IG-441-goal-completion-stream-delivery-modes.md) (code comments / stream_delivery), [IG-436](IG-436-daemon-delivery-priority.md) (session drain priority), [IG-535](IG-535-phase4-hidden-bottleneck-optimizations.md) (undroppable terminal frames)
**Supersedes (partial)**: IG-533 §1.2 post-idle 30s drain workaround; IG-533 §1.3 turn-end flush safety nets

---

## Executive Summary

Six overlapping termination signals currently compete to tell clients “this stream is done.” Each layer invented its own end marker when the prior signal was dropped, reordered, or misinterpreted. The result is duplicated finalization paths, empty terminal frames, 30-second post-idle drains, and TUI safety nets that mask root-cause ordering bugs.

| # | Signal | Emitter | Problem |
|---|--------|---------|---------|
| 1 | `chunk_position=last` on content | Runner / coalescer | Used as terminal without `stream_terminal`; ambiguous when content is empty |
| 2 | `stream_terminal=true` | `StreamDeliveryCoalescer` (adaptive chunked only) | Omitted in `streaming` passthrough; sometimes emitted on **empty** marker frame |
| 3 | `_emit_goal_completion_terminal_marker()` | `stream_delivery.py` | Extra empty `AIMessageChunk` when buffer already drained |
| 4 | `strange_loop.completed` custom event | Runner | Sets `turn_complete_pending` but QueryEngine never consumes it for ordering |
| 5 | `complete` (subscription) | QueryEngine | May precede tail content when drain is heuristic |
| 6 | `status: idle` | QueryEngine | Clients treat as turn end; 30s post-idle drain compensates for (5) |

**This IG unifies termination into one strict wire contract and deletes all legacy / backward-compat fallbacks.** The optimized path (terminal content → `soothe.stream.end` → `complete` → `idle`) is the **only** path — no feature flags, no `chunk_position`-only fallback, no empty markers, no 30s client drain.

Breaking changes are intentional: older clients that infer termination from `chunk_position=last` alone or from `idle` without `stream.end` must upgrade.

---

## Related Work

| Doc | Relevance |
|-----|-----------|
| **IG-533** | Surfaced tail-loss and post-idle drain workarounds this IG removes |
| **IG-441** | Adaptive / streaming / batch delivery modes; source of chunked `stream_terminal` |
| **IG-436** | HIGH/CRITICAL priority settle in `await_loop_delivery_drained` — extend to ack-based drain |
| **IG-535** | SDK priority-aware drop policy; terminal frames must stay undroppable |
| **RFC-614** | `messages` + `phase` streaming; updated with `stream_terminal` + `soothe.stream.end` |
| **RFC-450** | Subscription lifecycle: `complete` then `idle` after stream quiescence |

---

## Goals

1. **Single authoritative termination sequence** on every turn, every delivery mode, every client.
2. **`stream_terminal=true` on the last content frame** — never on a separate empty message.
3. **New `soothe.stream.end` custom event** with `scope` ∈ `{generation, phase, turn}` so clients finalize the correct UI scope without heuristics.
4. **QueryEngine consumes `turn_complete_pending`** to gate `complete` / `idle` emission after coalescer final flush.
5. **Ack-based delivery drain** replaces time-based settle guesses; client post-idle window shrinks to **0.5s** (ordering fix, not compensation).
6. **Idempotent client finalization** — duplicate terminals or late frames do not corrupt UI state.
7. **Delete legacy paths** — no backward-compat branches in SDK or TUI.

## Non-Goals

- Changing goal_completion synthesis logic or StrangeLoop phase graph.
- New feature flags or dual wire contracts (“old clients keep working”).
- Revisiting IG-535 batching/coalescing throughput optimizations (only termination edges).
- Gateway / mizar-airway changes (IG-533 P2).
- File-output threshold delivery shape (still one terminal content frame + `stream.end`).

---

## Problem: Overlapping Termination Today

```
Runner / Coalescer                QueryEngine                 Client (TUI / SDK)
      │                                │                              │
      ├─ AIMessageChunk (content)      │                              ├─ append text
      ├─ chunk_position=last ──────────┼──────────────────────────────┤─ maybe finalize?
      ├─ stream_terminal (sometimes)   │                              ├─ maybe finalize?
      ├─ EMPTY terminal marker ────────┼──────────────────────────────┤─ finalize (again)
      ├─ strange_loop.completed        │                              │
      │   (turn_complete_pending=true) │                              │
      │         ✗ never consumed       │                              │
      ├─ flush() safety net ───────────┼──────────────────────────────┤─ turn-end flush
      │                                ├─ await_loop_delivery_drained   │
      │                                │   (time-based, IG-436 margin) │
      │                                ├─ complete ─────────────────────┤─ subscription end
      │                                ├─ status: idle ───────────────┤─ turn cleanup
      │                                │                              └─ 30s post-idle drain
```

**Failure modes (observed / latent)**:

- `consume_turn_complete_pending()` exists on `StreamDeliveryCoalescer` but **is never called** from `QueryEngine` — `complete` / `idle` are not coupled to coalescer turn completion.
- `streaming` mode passthrough never stamps `stream_terminal` on the final LLM chunk.
- Adaptive chunked mode emits **empty** `build_goal_completion_stream_terminal_message()` when buffer is already empty.
- SDK `is_goal_completion_stream_terminal()` falls back to `chunk_position=last` when `stream_terminal` is absent (backward compat).
- TUI maintains parallel finalization: `is_goal_completion_stream_terminal`, `chunk_position=last` generic branch, `_flush_inflight_goal_completion_streams` at turn end, and stream-end safety nets.
- `_POST_IDLE_DRAIN_DEADLINE_S = 30.0` in `session.py` compensates for daemon ordering uncertainty.

---

## Target Wire Contract

### 1. Terminal content frame (last user-visible chunk)

Every phase-scoped assistant stream that ends with content must emit **one** final `mode="messages"` frame where:

```json
{
  "type": "AIMessageChunk",
  "phase": "<phase>",
  "content": "<final text or empty only when synthesis truly produced no text>",
  "chunk_position": "last",
  "stream_terminal": true
}
```

**Rules**:

- `stream_terminal=true` is **required** on the terminal frame; clients must not infer termination from `chunk_position` alone.
- **No empty marker frames** — delete `_emit_goal_completion_terminal_marker()` and `build_goal_completion_stream_terminal_message()` empty-content path.
- `streaming` passthrough must stamp `stream_terminal=true` on the last forwarded chunk (detect via upstream `chunk_position=last` or stream close).
- Adaptive / batch modes attach `stream_terminal=true` to the last **content-bearing** block.

### 2. `soothe.stream.end` custom event (new)

After all terminal content frames for a scope are broadcast, the daemon emits:

```json
{
  "type": "soothe.stream.end",
  "scope": "generation | phase | turn",
  "phase": "<phase when scope=phase>",
  "namespace": ["..."],
  "loop_id": "<uuid>",
  "turn_id": "<uuid when scope=turn>"
}
```

| `scope` | Meaning | When emitted |
|---------|---------|--------------|
| `generation` | One LLM generation within a phase | After each `stream_terminal` content frame |
| `phase` | Entire `phase=*` assistant stream (e.g. `goal_completion`) | After last `generation` in that phase |
| `turn` | Full user turn (all phases + tool telemetry) | After `strange_loop.completed` processing + coalescer `flush()` |

Clients use `scope` to finalize the correct UI binding without scanning for `chunk_position`.

### 3. Strict ordering (mandatory)

```
terminal content (stream_terminal=true)
    → soothe.stream.end (scope=generation)
    → … (repeat per open generation)
    → soothe.stream.end (scope=phase)   # per assistant phase
    → strange_loop.completed            # internal; not a client finalization signal
    → coalescer flush (final tuples + stream.end scopes)
    → soothe.stream.end (scope=turn)
    → await_loop_delivery_drained (ack-based)
    → complete (subscription, reason=stream_end)
    → status: idle
```

**Hard invariant**: `status: idle` MUST NOT precede `complete`, which MUST NOT precede `soothe.stream.end` (scope=turn), which MUST NOT precede terminal content.

---

## Implementation Plan

### P0 — Correctness: stop losing the tail

#### P0.1 Wire `consume_turn_complete_pending` in QueryEngine

**Problem**: `StreamDeliveryCoalescer` sets `_turn_complete_pending` on `strange_loop.completed` ingest but QueryEngine never reads it before emitting `complete` / `idle`.

**Files**:

| File | Change |
|------|--------|
| `packages/soothe-daemon/src/soothe_daemon/query/engine.py` | After stream iterator exhaustion: call `coalescer.flush()`, then `consume_turn_complete_pending()`; only proceed to drain / `complete` / `idle` when pending was true (or cancel/error path documented) |
| `packages/soothe-daemon/src/soothe_daemon/query/stream_delivery.py` | Document contract: `turn_complete_pending` means “all flush tuples queued”; no second `strange_loop.completed` append after flush |

**Acceptance**:

- Unit test: `strange_loop.completed` → flush tuples broadcast → `consume_turn_complete_pending()` returns `True` → then `complete` → then `idle`.
- Integration test: goal_completion chars in coalescer buffer at completed event all reach client before `idle`.

#### P0.2 SDK undroppable terminal frames

**Problem**: Under load, inbound queue drop policy (IG-535) must never evict `stream_terminal` content or `soothe.stream.end`.

**Files**:

| File | Change |
|------|--------|
| `packages/soothe-sdk/src/soothe_sdk/client/websocket.py` | Extend `_inbound_frame_drop_priority()` — CRITICAL (0) for `stream_terminal=true`, `soothe.stream.end`, `complete`, `status:idle` |
| `packages/soothe-sdk/tests/unit/test_websocket_priority_drop.py` | Add cases for `stream_terminal` and `soothe.stream.end` |

**Acceptance**: Load harness with full inbound queue — terminal content and `stream.end` always delivered.

#### P0.3 Remove empty goal_completion terminal marker

**Problem**: `_emit_goal_completion_terminal_marker()` emits content-free `AIMessageChunk` with `stream_terminal=true`.

**Files**:

| File | Change |
|------|--------|
| `packages/soothe-daemon/src/soothe_daemon/query/stream_delivery.py` | Delete `_emit_goal_completion_terminal_marker()`; ensure `_flush_goal_completion(final=True)` always attaches `stream_terminal=true` to last **content** block; if synthesis produced zero chars, emit single empty content frame with both flags (legitimate empty synthesis, not a duplicate marker) |
| `packages/soothe-sdk/src/soothe_sdk/ux/loop_stream.py` | Deprecate `build_goal_completion_stream_terminal_message()` — remove in P2 |
| `packages/soothe-daemon/tests/unit/query/test_stream_delivery.py` | Update adaptive chunked tests: no separate empty terminal tuple |

**Acceptance**: Wire capture shows exactly one terminal frame per goal_completion stream; never two consecutive `stream_terminal` frames.

#### P0.4 Idempotent TUI finalize

**Problem**: Multiple finalization entry points (`is_goal_completion_stream_terminal`, turn-end flush, safety nets) double-stop streams or leave cards running.

**Files**:

| File | Change |
|------|--------|
| `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` | Centralize `_finalize_assistant_stream(ns_key, reason)` — no-op if already finalized; call only from `stream_terminal` handler (P0) and `soothe.stream.end` (P2) |
| `packages/soothe-cli/tests/unit/ux/tui/test_goal_completion_stream_terminal.py` | Duplicate terminal does not double-append or corrupt card state |

**Acceptance**: Replay terminal frame + `stream.end` → card state unchanged after first finalize.

---

### P1 — Ordering hardening

#### P1.1 Immediate coalescer flush on `chunk_position=last`

**Problem**: Plain-text coalescer already flushes on `_chunk_position_last(msg)` but goal_completion / tool paths may defer trailing text to `flush()` at turn end.

**Files**:

| File | Change |
|------|--------|
| `packages/soothe-daemon/src/soothe_daemon/query/stream_delivery.py` | On any ingested message with `chunk_position=last`, force synchronous `final=True` flush for that namespace before returning tuples |
| `packages/soothe-daemon/tests/unit/query/test_stream_delivery.py` | `chunk_position=last` mid-turn emits immediately without waiting for `strange_loop.completed` |

#### P1.2 `stream_terminal` on streaming-mode passthrough

**Problem**: `_ingest_goal_completion` in `streaming` mode returns chunks verbatim — final chunk may lack `stream_terminal`.

**Files**:

| File | Change |
|------|--------|
| `packages/soothe-daemon/src/soothe_daemon/query/stream_delivery.py` | When passthrough sees `chunk_position=last` (or stream closes), clone wire dict and set `stream_terminal=true` |
| `packages/soothe-daemon/tests/unit/query/test_stream_delivery.py` | `test_streaming_mode_stamps_stream_terminal_on_last_chunk` |

#### P1.3 Ack-based `await_loop_delivery_drained`

**Problem**: IG-436 time-based settle (0.15s HIGH margin + batch timeout) is heuristic; tail frames can slip after drain returns.

**Files**:

| File | Change |
|------|--------|
| `packages/soothe-daemon/src/soothe_daemon/server/session.py` | Track per-loop delivery sequence; client acks via existing WS path (or new lightweight `delivery_ack`); drain waits until all tuples through `stream.end` (scope=turn) are acked or client disconnects |
| `packages/soothe-daemon/src/soothe_daemon/query/engine.py` | Pass turn boundary id into drain call |
| `packages/soothe-sdk/src/soothe_sdk/client/websocket.py` | Send ack after CRITICAL frames applied |
| `packages/soothe-daemon/tests/unit/server/test_delivery_drain.py` | Ack-based drain tests |

**Acceptance**: `complete` emitted only after server receives ack for final terminal + `stream.end` (or timeout with explicit degraded log).

#### P1.4 Post-idle drain: 0.5s not 30s

**Problem**: IG-533 raised `_POST_IDLE_DRAIN_DEADLINE_S` to 30s as compensation.

**Files**:

| File | Change |
|------|--------|
| `packages/soothe-cli/src/soothe_cli/runtime/transport/session.py` | `_POST_IDLE_DRAIN_DEADLINE_S = 0.5` |
| `packages/soothe-cli/src/soothe_cli/cli/execution/daemon.py` | Align headless client constant |

**Acceptance**: Fast turns return within 0.5s after `idle`; synthesis tail still received (ordering fix in P0/P1.3).

---

### P2 — Contract cleanup and legacy deletion

#### P2.1 Emit `soothe.stream.end`

**Files**:

| File | Change |
|------|--------|
| `packages/soothe-daemon/src/soothe_daemon/query/stream_delivery.py` | Emit `soothe.stream.end` tuples from coalescer after terminal content flush |
| `packages/soothe-daemon/src/soothe_daemon/query/engine.py` | Emit `scope=turn` `stream.end` after `consume_turn_complete_pending` + final flush |
| `packages/soothe/src/soothe/foundation/events/catalog.py` | Register `StreamEndEvent` with summary template |
| `packages/soothe-sdk/src/soothe_sdk/core/events.py` | Constant + wire shape |

#### P2.2 Unified client handlers

**Files**:

| File | Change |
|------|--------|
| `packages/soothe-sdk/src/soothe_sdk/ux/loop_stream.py` | `is_stream_terminal(msg)` — **only** `stream_terminal=true`; remove `chunk_position=last` fallback |
| `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` | Single handler table: `stream_terminal` → finalize generation; `soothe.stream.end` → finalize scope |
| `packages/soothe-cli/src/soothe_cli/tui/app/_history.py` | Same unified helpers |
| `packages/soothe-sdk/` Go/TS clients (if present) | Mirror handler |

#### P2.3 DELETE legacy paths

Remove entirely (no deprecation period):

| Legacy path | Location |
|-------------|----------|
| `chunk_position=last`-only terminal detection | `soothe_sdk/ux/loop_stream.py` `is_goal_completion_stream_terminal` |
| `build_goal_completion_stream_terminal_message()` empty marker | `soothe_sdk/ux/loop_stream.py` |
| `_emit_goal_completion_terminal_marker()` | `stream_delivery.py` |
| Turn-end `_flush_inflight_goal_completion_streams` safety net | `textual_adapter.py` (replace with `stream.end` scope=turn) |
| Stream-end safety net on generic `chunk_position=last` | `textual_adapter.py` |
| `not is_gc_chunk` branch hacks | `textual_adapter.py` |
| 30s `_POST_IDLE_DRAIN_DEADLINE_S` | already 0.5s in P1.4 |
| Tests asserting backward-compat fallback | `test_loop_stream_phases.py`, `test_goal_completion_stream_terminal.py` |

#### P2.4 RFC-614 update

**Files**:

| File | Change |
|------|--------|
| `docs/specs/RFC-614-unified-streaming-messaging.md` | Add § Stream termination: `stream_terminal`, `soothe.stream.end` scopes, ordering table, explicit breaking change note |
| `docs/wiki/api-reference/daemon-api.md` | Document ordering for client implementers |

---

## Breaking Changes (Intentional)

| Change | Client impact |
|--------|---------------|
| `stream_terminal` required | Clients must not use `chunk_position=last` alone |
| `soothe.stream.end` introduced | Clients should finalize UI on `scope=turn` event |
| Empty terminal markers removed | No more content-free finalize frames |
| Post-idle drain 30s → 0.5s | Requires correct daemon ordering |
| Turn-end TUI safety nets removed | Relies on wire contract |

**No feature flags.** Daemon and SDK ship together; CLI/TUI updated in same release.

---

## Verification

All changes must pass:

```bash
./scripts/verify_finally.sh
```

**Required test coverage**:

| Area | Tests |
|------|-------|
| Coalescer | Terminal on last content only; streaming passthrough stamp; no empty marker |
| QueryEngine | `consume_turn_complete_pending` ordering; `complete` → `idle` sequence |
| Session drain | Ack-based drain unit + integration |
| SDK | Undroppable terminals; `is_stream_terminal` strict |
| TUI | Idempotent finalize; `stream.end` scope handling |
| Contract | Golden wire trace: terminal → stream.end → complete → idle |

**Manual smoke**:

1. TUI: long goal_completion synthesis — full report visible, no duplicate cards, fast return to prompt after idle.
2. Headless CLI: stdout receives all chars before process exit.
3. `/clear` mid-synthesis: cancel ordering unchanged (IG-533 P0.1 stays valid).

---

## Task Checklist

### P0 — Correctness

- [x] **P0.1** QueryEngine calls `coalescer.flush()` + `consume_turn_complete_pending()` before drain
- [x] **P0.1** Unit test: completed → flush → pending consumed → complete → idle
- [x] **P0.2** SDK CRITICAL priority for `stream_terminal` and `soothe.stream.end`
- [x] **P0.2** Priority drop tests for new frame types
- [x] **P0.3** Remove `_emit_goal_completion_terminal_marker()`
- [x] **P0.3** Last content frame always carries `stream_terminal=true`
- [x] **P0.4** Idempotent `_finalize_assistant_stream` in TUI
- [x] **P0.4** Duplicate terminal replay test

### P1 — Ordering

- [x] **P1.1** Immediate namespace flush on `chunk_position=last`
- [x] **P1.2** `stream_terminal` stamped in `streaming` passthrough
- [x] **P1.3** Ack-based `await_loop_delivery_drained`
- [x] **P1.3** SDK sends delivery acks for CRITICAL frames
- [x] **P1.4** `_POST_IDLE_DRAIN_DEADLINE_S = 0.5` (CLI + headless)

### P2 — Cleanup

- [x] **P2.1** Register and emit `soothe.stream.end` (generation / phase / turn)
- [x] **P2.2** Unified client handler table (SDK + TUI + history)
- [x] **P2.3** Delete `build_goal_completion_stream_terminal_message`
- [x] **P2.3** Delete `chunk_position`-only fallback in `is_goal_completion_stream_terminal`
- [x] **P2.3** Delete TUI turn-end flush safety nets
- [x] **P2.4** RFC-614 stream termination section
- [x] **P2.4** daemon-api.md ordering docs

### Exit

- [x] `./scripts/verify_finally.sh` green
- [x] Golden wire trace checked into `packages/soothe-daemon/tests/`
- [x] IG-533 cross-link to IG-556 (done in IG-533 header)

---

## File Touch Map

```
packages/soothe-daemon/src/soothe_daemon/
├── query/engine.py              # P0.1 consume_turn_complete_pending, P1.3 drain, P2.1 turn stream.end
├── query/stream_delivery.py     # P0.3, P1.1, P1.2, P2.1 phase/generation stream.end
└── server/session.py            # P1.3 ack-based drain

packages/soothe-sdk/src/soothe_sdk/
├── client/websocket.py          # P0.2 undroppable, P1.3 acks
├── ux/loop_stream.py            # P2.2 strict terminal, P2.3 deletions
└── core/events.py               # P2.1 StreamEnd constant

packages/soothe-cli/src/soothe_cli/
├── tui/textual_adapter.py       # P0.4, P2.2, P2.3 safety-net deletion
├── tui/app/_history.py          # P2.2
└── runtime/transport/session.py # P1.4 drain constant

packages/soothe/src/soothe/foundation/events/catalog.py  # P2.1

docs/specs/RFC-614-unified-streaming-messaging.md  # P2.4
docs/wiki/api-reference/daemon-api.md                # P2.4
```

---

## Risks

| Risk | Mitigation |
|------|------------|
| Ack-based drain deadlock on slow clients | Timeout + explicit log; disconnect clears pending |
| Third-party clients not updated | Release notes; breaking change called out in RFC-614 |
| Zero-char synthesis | One legitimate empty content terminal frame — not a second marker |
| Cancel mid-stream | Cancel path emits `stream.end` scope=turn with `reason=cancelled` before `complete` |

---

## Success Criteria

1. Exactly **one** terminal content frame per assistant phase stream (with `stream_terminal=true`).
2. Wire trace ordering holds: **terminal → stream.end → complete → idle** on every turn type (quiz, direct model, full loop + goal_completion).
3. TUI shows complete goal_completion text without 30s post-idle wait.
4. No `_emit_goal_completion_terminal_marker`, no `chunk_position`-only fallback, no turn-end flush safety nets in codebase.
5. `./scripts/verify_finally.sh` passes with new tests.

## Progress / Handoff (2026-07-07 15:01 UTC+8)
### Completed
- P0 committed: `d211fe3e`
- P1 committed: `672fa333`
- P1 verify passed and post-idle drain reduced to 0.5s.
- P2 committed: stream termination unification (`soothe.stream.end`, legacy deletion, AsyncAPI `delivery_ack`, golden wire trace, verify green).