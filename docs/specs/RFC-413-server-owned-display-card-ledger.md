# RFC-413: Server-Owned Display Card Ledger

**RFC**: 413
**Title**: Server-Owned Display Card Ledger
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-06-04
**Authors**: xiaming (with Claude)
**Dependencies**: RFC-225 (Goal Record Enrichment), RFC-401 (Event Processing), RFC-403 (Unified Event Naming), RFC-411 (Event Stream Replay), RFC-503 (Loop-First UX), RFC-505 (Soothe Desktop Client), RFC-631 (Goal Display Snapshots)
**Supersedes**: RFC-411 (history reconstruction model)
**Amended by**: [RFC-631](RFC-631-goal-display-snapshots.md) (goal-bound display snapshots; live-only ledger scope)

---

## 1. Abstract

This RFC defines a server-owned **display card** model for rendering loop transcripts in Soothe clients (TUI, desktop, future web). The daemon hosts a `CardBinder` that converts raw execution events into bound card mutations, and a per-loop `DisplayCardLedger` that persists them in SQLite (`display.db`). Clients become passive renderers consuming a stable `card.*` wire schema.

The design eliminates the live/replay drift class by construction: live rendering and historical resume both flow through the same binding logic. It supersedes the checkpoint-tree reconstruction model in RFC-411 with a forward-write ledger that is recorded as the loop runs.

**RFC-631 amendment (2026-07-05):** The card ledger is scoped to the **active goal's live tail** only. Completed goals are recovered from immutable **goal display snapshots** (see RFC-631). Resume clients SHOULD use `loop_history_fetch` (snapshots + live tail) rather than replaying the full mutation history.

---

## 2. Scope and Non-Goals

### 2.1 Scope

* `CardBinder`: daemon-resident, single source of card-construction rules.
* `DisplayCardLedger`: in-memory + SQLite-backed store of bound card mutations for the **active goal's live tail** (RFC-631).
* `card.*` wire frames: `card.created`, `card.updated`, `card.finalized`, `card.replay_begin`, `card.replay_end`.
* Catalogue of card kinds (user message, assistant text, step, cognition plan/reason, subagent, error, system notice).
* Storage in `display.db` (`display_card_mutations` table).
* Live streaming and reattach replay of the **current goal tail** only.
* Resume of completed goals via RFC-631 goal display snapshots (`loop_history_fetch`).

### 2.2 Non-Goals

* Client-side widget implementation, themes, animation, autocomplete, scroll/selection state.
* Image / multimodal card rendering details (schema reserves a slot; rendering is deferred).
* Per-user view personalization (folded/expanded state per user account).
* Historical scrub UI ("show cards as of iteration N") — the append-only ledger enables it, but the UI affordance is out of scope here.
* Renaming `~/.soothe/data/` or migrating thread-scoped `conversation.jsonl` under `data/threads/`.

---

## 3. Motivation

### 3.1 Current Problem

The live TUI display is complete and correct: cognition cards, step cards, tool cards, user prompts, and final assistant text all render via the daemon's live event stream. **Resuming a historical loop produces a broken, incomplete transcript** that does not match what the user saw live.

Symptoms on resume:

* **Cognition / step cards** — partly present, but step→tool binding is unreliable.
* **User messages** — present when persisted via `ThreadLogger.log_user_input`, but not always linked to the iteration that consumed them.
* **Assistant streamed text** — only the final consolidated body is persisted; per-step `LoopAIMessage(phase=execute_step)` fragments are lost or mis-attributed.
* **Subagent cards** — completely absent (subagent domain is classified `INTERNAL` and never persisted).

Core-agent thread internal messages are intentionally suppressed live and remain suppressed on replay (by design, not a gap).

### 3.2 Three Resume Entry Points, Three Behaviors

| Entry point | Path | Today's behavior |
|---|---|---|
| TUI startup with loop id (`soothe loop continue <id>`) | `_load_loop_history()` → checkpoint + cognition replay merged | Closest to full; subagent cards missing; step binding fragile |
| TUI `/loops` switch inside an active session | `_resume_loop_via_daemon()` wipes screen, listens for new events | **Empty transcript** |
| `loop attach` CLI / `loop_subscribe` RPC | Daemon `handle_loop_reattach()` emits sparse `history_replay` (iteration boundaries only) | SDK discards as stale via `_STALE_TURN_PENDING_TYPES`; nothing renders |

### 3.3 Root Cause

Live rendering and resume rendering derive from **different inputs through different code paths**:

* **Live**: event stream → TUI binders in `_history.py` / `messages.py` → cards.
* **Resume**: LangGraph checkpoint + `ThreadLogger` activity JSONL → a separate TUI converter that reconstructs cards from two stores with different coverage.

The two paths have drifted. Coverage holes in persistence make some cards unrecoverable. The daemon's `handle_loop_reattach` (per RFC-411) emits sparse iteration-only events that the SDK explicitly filters out, leaving it as partly dead code.

### 3.4 Why a New Architecture, Not a Patch

A patch (wire `/loops` switch to existing `_load_loop_history`, audit persistence holes, delete dead daemon code) closes today's symptoms but preserves the architectural split: two stores, two code paths, future card types still need plumbing in both. The desktop client (RFC-505) would need to duplicate the TUI's binding logic.

The fix here is to **collapse live and replay onto one binding source**, owned by the daemon, with a wire schema designed for replay.

---

## 4. Guiding Principles

1. **Single binding source.** All event → card translation lives in one module. Live and replay are the same code path with different event sources (live bus vs. ledger replay).
2. **Server owns the projection.** The daemon decides what a card is; clients render it. Multiple clients attached to the same loop see identical transcripts.
3. **Append-only ledger.** Card state changes are recorded as a sequence of mutations, not as snapshots. Replay folds mutations to derive the latest state per card. History is preserved for free.
4. **Unbounded log, bounded projection** (per RFC-000). The cards.jsonl ledger may grow unboundedly; clients render a bounded window.
5. **Stable wire schema.** `card.*` frames are versioned and forward-compatible — unknown card kinds degrade to a generic renderer.
6. **Backfill, don't migrate.** Pre-existing loops without a cards.jsonl are lazily rebuilt from checkpoint + thread log on first read; no destructive migration.
7. **Clients stay rich.** Only binding rules move server-side. Rendering, theming, input, local state remain client concerns.

---

## 5. Component Overview

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

### 5.1 `CardBinder`

**Purpose**: convert raw daemon events into card mutations.

**Capabilities**:
* Subscribes to the daemon's internal event bus.
* Maintains per-loop binding state (open step id, pending tool calls awaiting results, current cognition card).
* Emits typed `CardMutation` objects (`create`, `update`, `finalize`) keyed by `card_id`.
* Pure module: no I/O, no daemon-host dependencies. Lives in `soothe_sdk` so client code paths can call it during the migration window.

**Interfaces**:
* Provides: `CardBinder.bind(event) -> Iterable[CardMutation]`.
* Requires: a typed event envelope (raw events from the daemon stream, normalized).

### 5.2 `DisplayCardLedger`

**Purpose**: persist and replay card mutations for the **active goal's live tail**.

**Capabilities**:
* Owns the in-memory dict `card_id → CardState` for the current goal segment.
* Persists mutations in `display.db` (`display_card_mutations` table).
* Assigns a monotonic `seq` to every mutation within the active goal segment.
* `apply(mutation)` — update memory + append a record.
* `snapshot() -> list[CardState]` — current visible cards in insertion order.
* `reset_for_next_goal()` — clear segment after RFC-631 freeze (see IG-548).
* `replay_to(sink, *, after_seq: int | None = None)` — push live-tail card frames to a client on reattach.

**Note (RFC-631):** Completed goals are **not** recovered by replaying the full mutation log. On goal idle, the daemon folds the segment into a `GoalDisplaySnapshot` and resets this ledger. Historical resume uses `loop_history_fetch`.

**Interfaces**:
* Provides: card frame stream for the wire layer.
* Requires: file system access under `~/.soothe/data/loops/<loop_id>/`; an append serializer.

### 5.3 Wire Layer

**Purpose**: deliver bound card frames to clients.

**Frames added** (RFC-403 grammar compliant — verbs report state changes):

| Frame type | Direction | Purpose |
|---|---|---|
| `card.created` | daemon → client | New card appears in the transcript |
| `card.updated` | daemon → client | Card state mutated (e.g., step tool count, plan status) |
| `card.finalized` | daemon → client | Terminal state set (success / error / duration) |
| `card.replay_begin` | daemon → client | Resume / attach: start of historical card stream |
| `card.replay_end` | daemon → client | Resume / attach: end of historical card stream — live frames follow |

Every frame carries `seq` (monotonic per loop) so clients can request "resume from seq N" on reconnect.

The legacy `history_replay`, `loop_reattached`, and `replay_complete` frames are deprecated. They remain on the wire only for the duration of Phase 3 to avoid client breakage; Phase 4 removes them.

### 5.4 Client Renderer

**Purpose**: paint cards on screen, handle input, manage local UI state.

**Capabilities**:
* `card_id → widget` registry; apply diffs from `card.*` frames.
* Reuses existing TUI widget classes (`StepCard`, `AssistantMessage`, `CognitionMessage`, etc.) unchanged.
* Keeps local-only state (scroll position, expand/collapse, selection, autocomplete).
* Falls back to a generic renderer for unknown card kinds (forward compatibility).

**Interfaces**:
* Provides: pluggable widget registry per card kind.
* Requires: `card.*` frame stream from the daemon.

---

## 6. Data Flow

### 6.1 Live Turn

1. Daemon receives user prompt; emits `user_input` event.
2. `CardBinder.bind(user_input)` → `CardMutation(op="create", kind="user_message", ...)`.
3. `DisplayCardLedger.apply(mutation)` → appends to `cards.jsonl`, sets in-memory state, returns the new card.
4. Daemon publishes `card.created` frame on the loop's subscription topic.
5. Loop graph executes: `strange_loop.step.started` → binder creates `step` card → `card.created`.
6. Tool call streams in (`messages` mode AIMessage with tool_calls) → binder binds to the open step card → `card.updated` adds a tool row.
7. Tool result streams in (`messages` mode ToolMessage) → binder matches by `tool_call_id` → `card.updated` completes the tool row.
8. `strange_loop.step.completed` → binder finalizes the step → `card.finalized`.
9. Final consolidated assistant text emitted → binder creates `assistant_text` card → `card.created`.

Throughout, `CardBinder` runs in a dedicated asyncio task fed by a bounded queue so it never blocks the live event publish path (see §10.2).

### 6.2 Resume / Reattach

**Completed goals (RFC-631):**

1. Client calls `loop_history_fetch(loop_id)`.
2. Daemon returns ordered `GoalDisplaySnapshot[]` + `live_cards` for the active goal (if any).
3. Client flattens `display_cards`, dedupes by id, mounts visible window.

**Live tail on reattach (this RFC):**

1. Client connects (`loop_subscribe` / TUI startup).
2. Daemon sends `card.replay_begin` → replays **live tail only** (current goal segment) → `card.replay_end`.
3. Live `card.*` frames stream for the in-flight goal.

Legacy full-ledger replay via `loop_cards_fetch` is deprecated; see RFC-631 migration path.

**Pre-existing loops without snapshots:** lazy migration synthesizes goal snapshots on first `loop_history_fetch`; live ledger backfill rules unchanged until P2 (IG-548).

### 6.3 `/loops` Switch Inside an Active TUI

1. User selects a different loop from `/resume` modal.
2. TUI clears renderer state for the current loop.
3. TUI calls `switch_loop` / `loop_subscribe` for the new `loop_id`.
4. TUI awaits `loop_history_fetch` and paints frozen goal snapshots + live tail (RFC-631).

This replaces fetching the full card mutation history on every switch.

---

## 7. Storage Layout

```
~/.soothe/data/loops/<loop_id>/
  └─ cards.jsonl       ← new: bound display cards (NDJSON, append-only)

~/.soothe/data/threads/<thread_id>/logs/
  └─ conversation.jsonl  ← existing ThreadLogger output (thread-scoped, unchanged)
```

A loop may bind to multiple execution threads over its lifetime; thread-scoped logs continue to live under `data/threads/`. The card ledger is loop-scoped because the display transcript is the user-facing view of a loop, not of any individual thread.

### 7.1 Record Format

Each line in `cards.jsonl` is a JSON object:

```jsonl
{"seq":1,"ts":"2026-06-04T10:15:30.123Z","op":"create","card_id":"step_001","kind":"step","data":{"step_id":"step_001","description":"Read auth config","phase":"running"}}
{"seq":2,"ts":"...","op":"update","card_id":"step_001","data":{"tool_rows":[{"id":"call_a1","name":"read_file","args_preview":"{\"path\":\"...\"}","status":"running"}]}}
{"seq":3,"ts":"...","op":"update","card_id":"step_001","data":{"tool_rows":[{"id":"call_a1","status":"success","output_preview":"..."}]}}
{"seq":4,"ts":"...","op":"finalize","card_id":"step_001","data":{"success":true,"duration_ms":4210,"tool_call_count":1}}
```

* `op=update` records send **diffs**, not whole-card snapshots. Replay folds them.
* `op=finalize` is a terminal `update` that locks the card from further mutations.
* The first line of every `cards.jsonl` is a header record:

```jsonl
{"seq":0,"ts":"...","op":"header","card_schema_version":1,"loop_id":"loop_abc123","created_by":"soothe-daemon/0.x.y"}
```

### 7.2 Size and Retention

* Typical loop (100 turns, ~10 cards/turn, ~5 mutations/card): **5,000 records / ~500 KB**.
* Worst-case loop with deep subagent telemetry: ~1 MB.
* Retention follows the existing per-loop GC policy (see RFC-225 / loop-continuity); when a loop is purged, its `cards.jsonl` is deleted with it.

---

## 8. Card Type Catalogue

Inferred from the current TUI widget set; covers everything the live UI renders today.

| Card kind | Required fields | Notes |
|---|---|---|
| `user_message` | `content`, `timestamp` | One per user prompt |
| `assistant_text` | `content` (markdown), `timestamp` | Final consolidated body per turn |
| `step` | `step_id`, `description`, `phase`, `tool_rows[]`, `success?`, `duration_ms?`, `tool_call_count?`, `summary?` | Tool rows bound from `messages`-mode tool calls; phase ∈ `{running, success, error}` |
| `cognition_plan` | `iteration`, `action`, `status`, `assessment?`, `strategy?` | Updated as plan reflects |
| `cognition_reason` | `iteration`, `content` | Per `soothe.cognition.strange_loop.reasoned` |
| `subagent` | `task`, `progress[]`, `success?` | Roll-up of subagent stream — not one card per chunk |
| `error` | `code`, `message`, `context?` | From `soothe.error.*` events |
| `system_notice` | `content`, `kind` (e.g., `loop_switch`, `summarization`, `clarification`) | `/loops` switch banners, summarization notices, clarification relays |

Future kinds (image attachments, MCP-specific tool cards, etc.) extend the catalogue server-side without client changes — clients render unknown kinds via a generic fallback widget.

---

## 9. Architectural Constraints

1. **Binder runs off the publish hot path.** A bounded queue between the daemon event bus and the `CardBinder` task isolates binding latency from live broadcast. Queue full → drop oldest live `card.*` frames and emit a single `system_notice` "transcript may be incomplete"; the ledger is authoritative for replay regardless.
2. **Ledger is single-writer.** Exactly one daemon process writes a given `cards.jsonl`. Multi-daemon deployments require a loop-to-daemon affinity rule (already true per RFC-450 / daemon communication).
3. **Wire schema is load-bearing.** Every `cards.jsonl` carries `card_schema_version`. Daemon must read all prior versions; clients tolerate unknown fields and unknown card kinds.
4. **No client-side card construction.** Once Phase 4 lands, the TUI's `_history.py` binding logic is removed. Live frames and replay frames go through the same renderer.
5. **Backfill is read-only-safe.** Backfilling an old loop must not lose data; if `CardBinder` cannot produce a card (e.g., a missing iteration), the ledger records a `system_notice` rather than silently skipping.
6. **Sequence numbers are monotonic and gap-free per loop.** Required for client-side `after_seq` reconnects to work.

---

## 10. Trade-offs and Rejected Alternatives

### 10.1 Why JSONL over Other Stores

| Option | Verdict |
|---|---|
| **LangGraph state channel** | Rejected. Checkpoint commits serialize the entire channel value per iteration → O(N²) write cost; couples display projection to graph state, violating RFC-000 "unbounded context, bounded projection"; hard to GC independently. |
| **SQLite per loop** | Rejected. Cards are pure append-only single-writer single-reader; relational layer adds schema/migration cost without enabling needed queries. One DB per loop scales poorly; one shared DB introduces hot-path lock contention. |
| **JSONL per loop** | Chosen. O(1) append, O(N) sequential read; co-located with other per-loop artifacts under `~/.soothe/data/loops/<loop_id>/`; operators tail/grep/archive in one place; sub-100 ms first paint for 10k cards; sidecar index can be added later if needed. |

### 10.2 Why Server-Side Binding over Shared-SDK Binding

A shared SDK module (binder lives in `soothe_sdk`, clients import) was considered. It avoids a daemon hot-path concern but reinstates the duplicate-execution problem: every client runs the binder, and bugs that affect rendering manifest only in some clients. Server-side binding gives the daemon authority — when fixing a transcript bug, you fix it once, in one place.

The chosen design takes the middle path: the `CardBinder` module lives in `soothe_sdk` (so it can be unit-tested in isolation and called from the CLI during Phase 2 staging), but **only the daemon runs it in production** once Phase 3 lands. The SDK location simplifies the move.

### 10.3 Why Mutation Stream over Snapshot Stream

Mutations (`update` with diffs) over snapshots (`update` with whole card) costs more decode complexity on the client but:

* Reduces wire bytes ~3–10× on long-running steps (a step card with 50 tool rows mutates once per row; sending the full row list each time is wasteful).
* Preserves history for free in the ledger (snapshot stream would either lose history or duplicate it).
* Enables `after_seq` resume from a known point without re-sending unchanged cards.

The client decode complexity is bounded — diffs are shallow per-field merges on typed card kinds.

### 10.4 Relationship to RFC-411

RFC-411 (Event Stream Replay & History Reconstruction) proposed reconstructing a chronological event stream from the StrangeLoop checkpoint tree on reattach, then replaying those events through the live TUI pipeline. The reconstruction has shipped (`soothe.core.events.replay.reconstructor`) but:

* The reconstructed stream only emits iteration boundaries + branch events — too sparse to rebuild cards.
* The daemon's `handle_loop_reattach` emits frames the SDK explicitly filters out as stale.
* Clients still hold all the binding logic, so reconstruction would need to replay raw events through duplicate parsers anyway.

RFC-413 replaces this approach: instead of reconstructing events on demand, record bound cards forward as the loop runs. RFC-411 is marked **superseded** when RFC-413 reaches Implemented status. The reconstructor module is deleted in Phase 3; the lazy backfill in §6.2 step 2 covers pre-413 loops.

---

## 11. Phased Migration

**Phase 1 — Ship the `/loops`-switch fix immediately (1 day).**
Wire `_resume_loop_via_daemon` (`_model.py`) to call `_load_loop_history` after a successful `switch_loop` RPC. Uses the existing converter; zero protocol change; lands independently of the rest of this RFC. Closes the worst-broken symptom today.

**Phase 2 — Extract `CardBinder` as a pure module (~3 days).**
Move binding logic from `_history.py::_convert_messages_to_data`, `_collect_cognition_card_replay`, `_merge_step_progress`, `_convert_loop_events_to_data` into `soothe_sdk.display.card_binder`. No Textual or rendering deps. Unit-tested against canned event traces. TUI continues to call it from the existing render path. **No behavior change** — pure refactor. Placing the module in `soothe_sdk` (not the CLI) avoids a second move in Phase 3.

**Phase 3 — Daemon owns the binder + ledger; new wire frames (~1 week).**
* Daemon imports `soothe_sdk.display.card_binder` and runs it inside its event pipeline behind a bounded queue.
* Add `DisplayCardLedger` writing `cards.jsonl` per loop.
* Add `card.*` wire frames; route `loop_subscribe` and `loop_reattach` through ledger replay.
* Remove `history_replay` / `loop_reattached` / `replay_complete` from the SDK `_STALE_TURN_PENDING_TYPES` filter; deprecate (do not delete) those frames.
* TUI gains a `card.*` consumer; existing live-event consumers stay one release as a rollout fallback.
* Lazy backfill for pre-existing loops: daemon builds `cards.jsonl` from checkpoint + thread log on first read.

**Phase 4 — Decommission legacy resume path (~3 days).**
* Remove TUI's checkpoint+activity-log fallback for resume.
* Delete `soothe.core.events.replay.reconstructor` and `enricher`.
* Remove deprecated wire frames (`history_replay` et al.).
* Desktop client (RFC-505) consumes `card.*` directly.
* Mark RFC-411 as superseded by this RFC.

**Total estimated effort:** ~2 weeks of focused work, with Phase 1 shipping in the first day.

---

## 12. Success Criteria

1. **Live ≡ Replay invariant**: the transcript rendered after `/loops` switch or `loop continue` is bit-identical to what the user saw live during the original session (modulo client-side state like scroll position).
2. **All three resume paths converge** on the same code (`card.*` frame consumption); the dead `history_replay` reconstructor is deleted.
3. **Subagent cards** appear on replay.
4. **Step → tool binding** is correct: every tool row attaches to the right step card, with status, args, and output preserved.
5. **Disk cost** stays under ~1 MB per 100-turn loop (`cards.jsonl`).
6. **Replay latency** under 100 ms first-paint, under 500 ms full hydrate for 100-turn loops.
7. **Desktop app** (RFC-505) consumes `card.*` frames with zero CLI-specific code.

---

## 13. Open Questions

1. **Card schema versioning policy.** When does a card-schema bump require a wire-protocol bump? Likely only for breaking field renames or kind removals; additive fields are forward-compatible. To be finalized in the impl-interface RFC.
2. **Backfill failure handling.** If `CardBinder` cannot reconstruct a legacy loop (corrupted checkpoint, missing thread log), do we (a) refuse to resume, (b) resume with a `system_notice` placeholder, or (c) fall back to today's renderer for that loop only? §9 constraint 5 favors (b); needs validation.
3. **Concurrent client reads during write.** Today the daemon serves one live + multiple readers per loop. Need to confirm Python file-handle semantics suffice for tail-read while another writer appends (POSIX `O_APPEND` should, but worth explicit test coverage).
4. **`after_seq` semantics on schema upgrade.** If a daemon restart re-binds an in-progress loop under a newer card schema, can a client resume with the old `seq`? Provisional answer: yes, schema-version mismatch triggers a full replay rather than diff.
5. **Tool-row identity across retries.** When a tool call is retried within a step, does the new attempt mutate the existing `tool_row` (same `tool_call_id`) or create a sibling row? Live UI today appears to create a sibling; needs explicit binder rule.

---

## 14. References

* RFC-000 — System Conceptual Design (unbounded context, bounded projection)
* RFC-401 — Event Processing
* RFC-403 — Unified Event Naming Semantics
* RFC-411 — Event Stream Replay & History Reconstruction (superseded by this RFC)
* RFC-450 — Daemon Communication Protocol
* RFC-503 — Loop-First User Experience
* RFC-505 — Soothe Desktop Client
* Design draft: `docs/drafts/2026-06-04-resume-loop-display-design.md`

---

*RFC-413 generated from Platonic Coding Phase 1 RFC formalization.*
