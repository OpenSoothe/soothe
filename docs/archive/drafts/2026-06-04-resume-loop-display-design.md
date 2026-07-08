# Resume-Loop Display: Server-Owned Card Model

**Status:** Draft — Platonic Coding Phase 0 (Brainstorming output)
**Date:** 2026-06-04
**Authors:** xiaming (with Claude)
**Related:** RFC-411 (Event Stream Replay), RFC-503 (Loop-First UX), RFC-000 (Conceptual Design)

---

## 1. Problem

The live TUI display is correct and complete: cognition cards, step cards, tool cards, user prompts, and final assistant text all render via the daemon's live event stream. **Resuming a historical loop produces a broken, incomplete transcript** that does not match what the user saw live.

### 1.1 Symptoms

On resume, the transcript is missing or wrong in:

- **Cognition / step cards** (`strange_loop.step.started`, `step.completed`, `reasoned`) — partly present, but step→tool binding is unreliable.
- **User messages** — present when persisted via `ThreadLogger.log_user_input`, but not always linked to the iteration that consumed them.
- **Assistant streamed text** — only the final consolidated body is persisted; per-step `LoopAIMessage(phase=execute_step)` fragments are lost or mis-attributed.
- **Subagent cards** — completely absent (subagent domain is classified `INTERNAL` and never persisted).

Core-agent thread internal messages are intentionally suppressed live and should remain suppressed on replay (this is by design, not a gap).

### 1.2 Three resume entry points, three behaviors

| Entry point | Path | Today's behavior |
|---|---|---|
| TUI startup with loop id (e.g. `soothe loop continue <id>`) | `_load_loop_history()` → checkpoint + cognition replay merged | Closest to full; subagent cards missing; step binding fragile |
| TUI `/loops` switch inside an active session | `_resume_loop_via_daemon()` wipes screen, listens for new events | **Empty transcript** |
| `loop attach` CLI / `loop_subscribe` RPC | Daemon `handle_loop_reattach()` emits sparse `history_replay` (iteration boundaries only) | SDK discards as stale (`_STALE_TURN_PENDING_TYPES`) → nothing renders |

### 1.3 Root cause

**Live rendering and resume rendering derive from different inputs through different code paths.**

- Live: event stream → TUI binders in `_history.py` / `messages.py` → cards.
- Resume: LangGraph checkpoint + ThreadLogger activity JSONL → a separate TUI converter that tries to reconstruct cards from two stores with different coverage.

The two paths have drifted. Coverage holes in persistence make some cards unrecoverable. The daemon's `handle_loop_reattach` is partly dead code (SDK filters its output frames).

---

## 2. Design Direction

**Move event-binding logic from the CLI into the daemon. The daemon owns an authoritative `DisplayCardLedger` keyed per loop, persisted as append-only JSONL. Clients (TUI, desktop, future web) become passive renderers of typed card frames.**

This eliminates the live/replay drift class entirely by construction — there is one binder, one ledger, one wire schema. Resume is just "stream `cards.jsonl` to the client and render."

### 2.1 Why this over alternatives

| Alternative | Why rejected |
|---|---|
| **A.** Persist every raw event, replay through live pipeline | Functionally correct but costly: 50–500 events per turn → 3–30 MB per loop, 1–3 s replay; binding logic duplicated TUI ↔ desktop |
| **B.** Patch the two-store merger (checkpoint + activity log) | Smaller diff but doesn't fix the architectural split; future card types still need plumbing in two places; `/loops` switch fix is a one-liner we can ship now regardless |
| **C.** TUI-side snapshot of MessageStore | TUI crash → stale; couples persistence schema to UI version; useless for non-TUI clients |
| **D. (chosen)** Server-side card binder + JSONL ledger | Single binding source, 10× smaller wire/disk, ~50 ms first-paint on replay, zero client duplication |

### 2.2 Comparison numbers (100-turn loop, worst case)

|   | Raw event replay (A) | Bound card replay (D) |
|---|---|---|
| Wire frames / turn | 50–500 | 5–20 |
| Disk per loop | 3–8 MB | 200 KB – 1 MB |
| Replay first-paint | ~300 ms | ~50 ms |
| Replay full hydrate | 1–3 s | 100–300 ms |
| Binding code duplication | TUI + desktop | Daemon only |

---

## 3. Architecture

```
Daemon                                              Clients
──────                                              ───────
LangGraph stream ──┐
                   ├─► CardBinder ──► DisplayCardLedger ──► wire ──► Renderer
ThreadLogger     ──┘   (single                │                     (TUI, desktop)
                       binding source)        │
                                              ▼
                                       cards.jsonl
                                       (append-only,
                                        per loop)
```

### 3.1 Components

#### `CardBinder` (new, daemon)

Subscribes to the daemon's internal event bus. Translates raw events into card mutations:

- `strange_loop.step.started` → `StepCard.create(step_id, description, phase="running")`
- `tool_call` (messages-mode) → bind to current open `StepCard` by `step_id` → `StepCard.add_tool_row(tool_call_id, name, args_preview)`
- `tool_result` (messages-mode) → match by `tool_call_id` → `StepCard.complete_tool_row(tool_call_id, status, output_preview)`
- `strange_loop.step.completed` → `StepCard.finalize(step_id, success, duration_ms, tool_count, summary)`
- `strange_loop.reasoned` → `CognitionCard.create_or_update(iteration, action, assessment, strategy)`
- Subagent stream chunks → `SubagentCard.append_progress(...)` (rolled up — not one card per chunk)
- `LoopAIMessage(phase=execute_step)` → append to current `StepCard.body`
- Final consolidated assistant text → `AssistantTextCard.create(content)`
- User input → `UserMessageCard.create(content)`

The binder is the **only** place card-construction rules live. Today these rules are scattered across `_history.py::_convert_messages_to_data`, `_history.py::_collect_cognition_card_replay`, `_history.py::_merge_step_progress`, and live render code paths in the TUI.

#### `DisplayCardLedger` (new, daemon, per loop)

In-memory dict `card_id → CardState` plus the append-only file. Operations:

- `apply(mutation: CardMutation)` — update in-memory state and append a record to `cards.jsonl`.
- `snapshot() -> list[CardState]` — current visible cards in insertion order.
- `replay_to(sink, *, after_seq: int | None = None)` — push card frames to a client, optionally resuming from a sequence number.

Card mutations are recorded as JSON lines:

```jsonl
{"seq":1,"ts":"...","op":"create","card_id":"step_001","kind":"step","data":{...}}
{"seq":2,"ts":"...","op":"update","card_id":"step_001","data":{"tool_count":3}}
{"seq":3,"ts":"...","op":"finalize","card_id":"step_001","data":{"success":true,"duration_ms":4210}}
```

Replay folds the records: the latest update per `card_id` is the final state. History is preserved for debugging and for the desktop's future "scrub to iteration N" view.

#### Wire schema (new frames)

| Frame | Direction | Purpose |
|---|---|---|
| `card.created` | daemon → client | New card appears in transcript |
| `card.updated` | daemon → client | Card state mutated (e.g., step tool count, plan status) |
| `card.finalized` | daemon → client | Terminal state set (success/error/duration) |
| `card.replay_begin` | daemon → client | Resume / attach: start of card stream |
| `card.replay_end` | daemon → client | Resume / attach: end of card stream, live events follow |

Frames include `seq` (monotonic per loop) so clients can resume replay from a known point on reconnect.

#### Client renderers

The TUI and desktop apps become passive: `card_id → widget` map, apply diffs on `card.*` frames. The TUI keeps its existing widget classes (`StepCard`, `AssistantMessage`, etc.) — only the *binding* logic in `_history.py` moves to the daemon. Rendering, animation, theme, autocomplete stay client-side.

### 3.2 Storage layout

The new ledger lives under the per-loop data directory, alongside any future loop-scoped artifacts:

```
~/.soothe/data/loops/<loop_id>/
  └─ cards.jsonl       ← new: bound display cards (NDJSON, append-only)

~/.soothe/data/threads/<thread_id>/logs/
  └─ conversation.jsonl  ← existing ThreadLogger output (thread-scoped, unchanged)
```

A loop binds to one or more execution threads over its lifetime; thread-scoped logs continue to live under `data/threads/`. The card ledger is loop-scoped because the display transcript is the user-facing view of a loop, not of any individual thread.

JSONL chosen over LangGraph state channel (would cause O(N²) checkpoint bloat) and SQLite (over-engineered for append-only single-writer pattern). See §6.1 for the full rationale.

---

## 4. Card Types (initial set)

Inferred from current TUI widget set:

| Card kind | Fields | Notes |
|---|---|---|
| `user_message` | content, timestamp | One per user prompt |
| `assistant_text` | content (markdown), timestamp | Final consolidated body per turn |
| `step` | step_id, description, phase, tool_rows[], success, duration_ms, summary | Tool rows bound from messages-mode tool calls |
| `cognition_plan` | iteration, action, status, assessment, strategy | Updated as plan reflects |
| `cognition_reason` | iteration, content | Per `strange_loop.reasoned` event |
| `subagent` | task, progress[], success | Roll-up of subagent stream |
| `error` | code, message, context | From `soothe.error.*` events |
| `system_notice` | content, kind | `/loops` switch banners, summarization notices |

Future kinds (image attachments, MCP tool cards, etc.) are added in the daemon without client changes — clients fall back to a generic card renderer for unknown kinds.

---

## 5. Phased Migration

**Phase 1 — Ship the `/loops`-switch fix immediately (1 day).**

Wire `_resume_loop_via_daemon` (in `_model.py`) to call `_load_loop_history` after a successful `switch_loop` RPC. This unblocks the worst-broken case today using the existing converter. Zero protocol change. Lands independently of the rest of this design.

**Phase 2 — Extract `CardBinder` as a pure module (~3 days).**

Move binding logic out of `_history.py::_convert_messages_to_data`, `_collect_cognition_card_replay`, `_merge_step_progress`, and `_convert_loop_events_to_data` into a new `soothe_sdk.display.card_binder` module (in the shared SDK so both client and daemon can import it during the transition). Design its interface as if it already lived in the daemon: it consumes a stream of events and emits card mutations, with no Textual or rendering dependencies. Unit-tested against canned event traces. TUI calls it from the existing render path. **No behavior change** — this is a pure refactor. Placing it in `soothe_sdk` (not the CLI) avoids a second move in Phase 3.

**Phase 3 — Make daemon own the binder + ledger, add wire frames (~1 week).**

- Daemon imports `soothe_sdk.display.card_binder` and runs it inside its event pipeline (so the rules live in one place — the SDK — and execute on the daemon).
- Add `DisplayCardLedger` (daemon-owned) writing `cards.jsonl` per loop.
- Add new wire frames `card.created` / `card.updated` / `card.finalized` / `card.replay_begin` / `card.replay_end`.
- Update daemon `handle_loop_reattach` to replay from the ledger instead of reconstructing from checkpoint anchors. Delete `core.events.replay.reconstructor` and `core.events.replay.enricher`.
- Remove `history_replay` / `loop_reattached` from SDK `_STALE_TURN_PENDING_TYPES` — they become real consumed frames.
- TUI gains a `card.*` consumer; existing live-event consumers stay for one release as a fallback during rollout.
- Backfill: on first daemon read of a pre-existing loop with no `cards.jsonl`, lazily build the ledger from checkpoint + thread-scoped `conversation.jsonl` using the same `CardBinder`. One-time cost.

**Phase 4 — Decommission legacy resume path, desktop adopts `card.*` (~3 days).**

- Remove TUI fallback for raw events on resume (live path keeps consuming them).
- Desktop app consumes `card.*` frames directly with no extra binding code.
- Update RFC-411 to reflect card-replay model.

**Total estimate:** ~2 weeks of focused work, with Phase 1 shipping in the first day.

---

## 6. Open Questions and Trade-offs

### 6.1 Why JSONL over other stores

| Option | Verdict |
|---|---|
| **LangGraph state channel** | Rejected. Checkpoint commits serialize the entire channel value per iteration → O(N²) write cost. Couples display projection to graph state, violating RFC-000 "unbounded context, bounded projection." Hard to GC independently. |
| **SQLite per loop** | Rejected. Cards are pure append-only single-writer single-reader; relational layer adds schema/migration cost without enabling needed queries. One DB per loop scales poorly; one shared DB introduces hot-path lock contention. |
| **JSONL per loop** | Chosen. O(1) append, O(N) sequential read; co-located with other per-loop artifacts under `~/.soothe/data/loops/<loop_id>/`; operators can tail/grep/archive in one place; sub-100 ms first paint for 10k cards; sidecar index can be added later if needed. |

### 6.2 Live binder on the hot path

Risk: running `CardBinder` synchronously inside the daemon event broadcast loop could add latency to live streaming. Mitigation: run the binder in a dedicated asyncio task fed from a bounded queue (same pattern as `TurnEventPipeline` in the TUI). Card frames are produced in order but decoupled from the raw event publish path.

### 6.3 Versioning

Card schema is now load-bearing. We need:
- A `card_schema_version` field on each `cards.jsonl` file's first line.
- A compatibility window: new daemon must read old card files; old client must tolerate unknown card kinds (fall back to generic renderer).
- An RFC update (RFC-411) documenting the schema.

### 6.4 Subagent card coverage

Subagent events are currently `INTERNAL` tier and not persisted. Phase 3 adds them via the binder's `SubagentCard` aggregation — we don't need to promote them to `NORMAL` (the binder reads internal events and emits NORMAL card frames). This is a feature of moving binding server-side.

### 6.5 What stays on the client

- All rendering (widgets, layout, theme, animation, autocomplete).
- All input handling.
- Local state (scroll position, expand/collapse, selection).
- The local message store / windowing.

Only **binding rules** move to the daemon. Clients are still rich; they just stop disagreeing about what an event means.

### 6.6 Multi-client behavior

With server-owned cards, two clients attached to the same loop see identical transcripts. Today they could drift (different parse/merge logic). Sequence numbers (`seq` on each frame) let a reconnecting client request "send me everything after seq N" instead of re-replaying the full ledger.

---

## 7. Success Criteria

1. **Live ≡ Replay invariant:** the transcript rendered after `/loops` switch or `loop continue` is bit-identical to what the user saw live during the original session (modulo client-side state like scroll position).
2. **All three resume paths converge** on the same code (`card.*` frame consumption); the dead `history_replay` reconstructor is deleted.
3. **Subagent cards** appear on replay.
4. **Step → tool binding** is correct: every tool row attaches to the right step card, with status, args, and output preserved.
5. **Disk cost** stays under ~1 MB per 100-turn loop (cards.jsonl).
6. **Replay latency** under 100 ms first-paint, under 500 ms full hydrate for 100-turn loops.
7. **Desktop app** consumes the same `card.*` frames with zero CLI-specific code.

---

## 8. Out of Scope

- Image/multimodal card rendering (separate work; the schema supports an `image` kind but rendering details are deferred).
- Per-user view personalization (folded/expanded state per user) — kept client-side.
- Historical card replay UI ("scrub to iteration N") — recorded as a future capability the JSONL append-only history enables.
- Renaming `~/.soothe/data/loops/` or migrating other persistence (thread-scoped `conversation.jsonl` under `data/threads/` stays as-is).

---

## 9. Next Step

Route into Platonic Coding Phase 1: generate an RFC from this draft, then run `specs-refine` to lock the wire schema, card-type catalogue, and migration ordering before implementation.
