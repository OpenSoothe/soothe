# RFC-413: Server-Owned Display Card Ledger

**RFC**: 413
**Title**: Server-Owned Display Card Ledger
**Status**: Draft (Phases 1–4 shipped; structural live path via ``soothe.card.*`` — IG-655)
**Kind**: Architecture Design
**Created**: 2026-06-04
**Updated**: 2026-07-27
**Authors**: xiaming (with Claude)
**Dependencies**: RFC-225 (Goal Record Enrichment), RFC-401 (Event Processing), RFC-403 (Unified Event Naming), RFC-411 (Event Stream Replay), RFC-503 (Loop-First UX), RFC-631 (Goal Display Snapshots)
**Supersedes**: RFC-411 (history reconstruction model)
**Amended by**: [RFC-631](RFC-631-goal-display-snapshots.md) (goal-bound display snapshots; live-only ledger scope); 2026-07-19 persistence backend follows `persistence.default_backend` (PostgreSQL `soothe_metadata` when configured); 2026-07-27 Phase 4 completion (live `soothe.card.*` cutover, append-oriented ledger, DisplayCardStore as SoT — see §11 / §16 and [design draft](../drafts/2026-07-27-tui-card-replay-source-of-truth-design.md))
**Implemented by**: IG-655 (Phase 4 cutover)

---

## 1. Abstract

This RFC defines a server-owned **display card** model for rendering loop transcripts in Soothe clients (TUI, future web). The daemon hosts a `CardBinder` that converts raw execution events into bound card mutations, and a per-loop `DisplayCardLedger` that persists them via the configured persistence backend: SQLite (`display.db`) by default, or PostgreSQL (`soothe_metadata` tables) when `persistence.default_backend: postgresql`. Clients become passive renderers consuming a stable `soothe.card.*` wire schema.

The design eliminates the live/replay drift class by construction: live rendering and historical resume both flow through the same binding logic. It supersedes the checkpoint-tree reconstruction model in RFC-411 with a forward-write ledger that is recorded as the loop runs.

**RFC-631 amendment (2026-07-05):** The card ledger is scoped to the **active goal's live tail** only. Completed goals are recovered from immutable **goal display snapshots** (see RFC-631). Resume clients SHOULD use `loop_history_fetch` (snapshots + live tail) rather than replaying the full mutation history.

---

## 2. Scope and Non-Goals

### 2.1 Scope

* `CardBinder`: daemon-resident, single source of card-construction rules.
* `DisplayCardLedger`: in-memory + durable store of bound card mutations for the **active goal's live tail** (RFC-631). Backend follows `persistence.default_backend` (SQLite `display.db` or PostgreSQL `soothe_metadata`).
* `soothe.card.*` wire frames: `soothe.card.created`, `soothe.card.updated`, `soothe.card.finalized`, `soothe.card.replay.begin`, `soothe.card.replay.end`.
* Catalogue of card kinds (user message, assistant text, step, cognition plan/reason, subagent, error, system notice).
* Storage: `display_card_mutations` (+ RFC-631 `goal_display_snapshots`) in SQLite `display.db` or PostgreSQL `soothe_metadata`.
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

Symptoms on resume (pre–IG-577; largely addressed):

* **Cognition / step cards** — present; step cards show description, duration, and **tool-call count** on resume (inline tool-row replay is live-only).
* **User messages** — present when persisted via `ThreadLogger.log_user_input`.
* **Assistant streamed text** — consolidated assistant cards; `AssistantMessage` renders body on mount (no dot-only flash).
* **Standalone tool stubs** — suppressed; display ledger never emits `MessageType.TOOL` cards.
* **Orchestration-internal checkpoint rows** — `intent_classify`, `plan_gap_analysis`, `continuation`, and existing internal phases are stripped before bind.
* **Subagent cards** — roll-up cards appear when bound at freeze; per-chunk subagent wire remains live-only.

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

A patch (wire `/loops` switch to existing `_load_loop_history`, audit persistence holes, delete dead daemon code) closes today's symptoms but preserves the architectural split: two stores, two code paths, future card types still need plumbing in both. Other protocol-1 clients would need to duplicate the TUI's binding logic without a server-owned ledger.

The fix here is to **collapse live and replay onto one binding source**, owned by the daemon, with a wire schema designed for replay.

---

## 4. Guiding Principles

1. **Single binding source.** All event → card translation lives in one module. Live and replay are the same code path with different event sources (live bus vs. ledger replay).
2. **Server owns the projection.** The daemon decides what a card is; clients render it. Multiple clients attached to the same loop see identical transcripts.
3. **Append-only ledger.** Card state changes are recorded as a sequence of mutations, not as snapshots. Replay folds mutations to derive the latest state per card. History is preserved for free.
4. **Unbounded log, bounded projection** (per RFC-000). The mutation log in DisplayCardStore may grow unboundedly; clients render a bounded window.
5. **Stable wire schema.** `soothe.card.*` frames are versioned and forward-compatible — unknown card kinds degrade to a generic renderer.
6. **Backfill, don't migrate.** Pre-existing loops without ledger rows are lazily rebuilt / snapshot-migrated on first read; no destructive migration.
7. **Clients stay rich.** Only binding rules move server-side. Rendering, theming, input, local state remain client concerns.

---

## 5. Component Overview

```
Daemon                                              Clients
──────                                              ───────
LangGraph / runner stream
        │
        ▼
  LoopCardManager (ingest queue)
        │
        ▼
  CardBinder ──► append CardMutation(s)
        │              │
        │              ├─► DisplayCardStore  (SoT: live tail + goal snapshots)
        │              └─► wire soothe.card.created / updated / finalized
        │                        │
        │                        ▼
        │                 all loop subscribers (0..N)
        │
        └─► raw stream broadcast may continue for non-UI consumers;
            UI clients MUST NOT construct structural cards from raw events
            once Phase 4 lands
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
* Persists mutations in `display_card_mutations` (SQLite `display.db` or PostgreSQL `soothe_metadata` when `persistence.default_backend: postgresql`).
* Assigns a monotonic `seq` to every mutation within the active goal segment.
* `apply(mutation)` — update memory + append a record.
* `snapshot() -> list[CardState]` — current visible cards in insertion order.
* `reset_for_next_goal()` — clear segment after RFC-631 freeze (see IG-548).
* `replay_to(sink, *, after_seq: int | None = None)` — push live-tail card frames to a client on reattach.

**Note (RFC-631):** Completed goals are **not** recovered by replaying the full mutation log. On goal idle, the daemon folds the segment into a `GoalDisplaySnapshot` and resets this ledger. Historical resume uses `loop_history_fetch`.

**Interfaces**:
* Provides: card frame stream for the wire layer.
* Requires: durable store access (SQLite under `$SOOTHE_HOME/data/`, or PostgreSQL `metadata` DSN).

### 5.3 Wire Layer

**Purpose**: deliver bound card frames to clients.

**Frames added** (RFC-403 grammar compliant — verbs report state changes):

| Frame type | Direction | Purpose |
|---|---|---|
| `soothe.card.created` | daemon → client | New card appears in the transcript |
| `soothe.card.updated` | daemon → client | Card state mutated (e.g., step tool count, plan status) |
| `soothe.card.finalized` | daemon → client | Terminal state set (success / error / duration) |
| `soothe.card.replay.begin` | daemon → client | Resume / attach: start of historical card stream |
| `soothe.card.replay.end` | daemon → client | Resume / attach: end of historical card stream — live frames follow |

Every frame carries `seq` (monotonic per loop) so clients can request "resume from seq N" on reconnect.

The legacy `history_replay`, `loop_reattached`, and `replay_complete` frames are deprecated. They remain on the wire only for the duration of Phase 3 to avoid client breakage; Phase 4 removes them.

### 5.4 Client Renderer

**Purpose**: paint cards on screen, handle input, manage local UI state.

**Capabilities**:
* `card_id → widget` registry; apply diffs from `soothe.card.*` frames.
* Reuses existing TUI widget classes (`StepCard`, `AssistantMessage`, `CognitionMessage`, etc.) unchanged.
* Keeps local-only state (scroll position, expand/collapse, selection, autocomplete).
* Falls back to a generic renderer for unknown card kinds (forward compatibility).

**Interfaces**:
* Provides: pluggable widget registry per card kind.
* Requires: `soothe.card.*` frame stream from the daemon.

---

## 6. Data Flow

### 6.1 Live Turn

1. Daemon receives user prompt; emits `user_input` event.
2. `CardBinder.bind(user_input)` → `CardMutation(op="create", kind="user_message", ...)`.
3. `DisplayCardLedger.apply(mutation)` → appends to DisplayCardStore, sets in-memory state, returns the new card.
4. Daemon publishes `soothe.card.created` frame on the loop's subscription topic (Phase 4: this is the live UI path).
5. Loop graph executes: `strange_loop.step.started` → binder creates `step` card → `soothe.card.created`.
6. Tool call streams in (`messages` mode AIMessage with tool_calls) → binder binds to the open step card → `soothe.card.updated` adds a tool row.
7. Tool result streams in (`messages` mode ToolMessage) → binder matches by `tool_call_id` → `soothe.card.updated` completes the tool row.
8. `strange_loop.step.completed` → binder finalizes the step → `soothe.card.finalized`.
9. Final consolidated assistant text emitted → binder creates `assistant_text` card → `soothe.card.created`.

Throughout, `CardBinder` runs in a dedicated asyncio task fed by a bounded queue so it never blocks the live event publish path (see §10.2).

### 6.2 Resume / Reattach

**Completed goals (RFC-631):**

1. Client calls `loop_history_fetch(loop_id)`.
2. Daemon returns ordered `GoalDisplaySnapshot[]` + `live_cards` for the active goal (if any).
3. Client flattens `display_cards`, dedupes by id, mounts visible window.

**Live tail on reattach (this RFC):**

1. Client connects (`loop_subscribe` / TUI startup).
2. Daemon sends `soothe.card.replay.begin` → replays **live tail only** (current goal segment) → `soothe.card.replay.end`.
3. Live `soothe.card.*` frames stream for the in-flight goal.

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

**Authoritative SoT** is `DisplayCardStore`, selected by `persistence.default_backend`:

| Backend | Location |
|---|---|
| `sqlite` | `$SOOTHE_HOME/data/display.db` (tables `display_card_mutations`, `goal_display_snapshots`) |
| `postgresql` | PostgreSQL database `soothe_metadata` (same logical schema; IG-623) |

```
~/.soothe/data/threads/<thread_id>/logs/
  └─ conversation.jsonl  ← ThreadLogger (thread-scoped debug / non-display; unchanged)
```

Per-loop `cards.jsonl` under `data/loops/<loop_id>/` was the **original** RFC sketch and is **not** the production SoT. Optional JSONL export under a loop folder may exist for debugging only and MUST NOT be treated as authoritative.

A loop may bind to multiple execution threads over its lifetime; thread-scoped logs continue under `data/threads/`. The card ledger is loop-scoped because the display transcript is the user-facing view of a loop, not of any individual thread.

### 7.1 Record Format

Each persisted mutation is a JSON-compatible object (same shape whether SQLite or Postgres):

```json
{"seq":1,"ts":"2026-06-04T10:15:30.123Z","op":"create","card_id":"step_001","kind":"step","data":{"step_id":"step_001","description":"Read auth config","phase":"running"}}
{"seq":2,"ts":"...","op":"update","card_id":"step_001","data":{"tool_call_count":3}}
{"seq":3,"ts":"...","op":"finalize","card_id":"step_001","data":{"success":true,"duration_ms":4210,"tool_call_count":3}}
```

* `op=update` records send **diffs**, not whole-card snapshots. Replay folds them.
* `op=finalize` is a terminal `update` that locks the card from further mutations.
* A header record (`op=header`, `card_schema_version`) begins each live segment.

### 7.2 Size and Retention

* Typical loop (100 turns, ~10 cards/turn, ~5 mutations/card): **5,000 records / ~500 KB**.
* Worst-case loop with deep subagent telemetry: ~1 MB.
* Retention follows the existing per-loop GC policy (see RFC-225 / loop-continuity); when a loop is purged, its display mutations and goal snapshots are deleted with it.

---

## 8. Card Type Catalogue

Inferred from the current TUI widget set; covers everything the live UI renders today.

| Card kind | Required fields | Notes |
|---|---|---|
| `user_message` | `content`, `timestamp` | One per user prompt |
| `assistant_text` | `content` (markdown), `timestamp` | Final consolidated body per turn |
| `step` | `step_id`, `description`, `phase`, `tool_call_count?`, `duration_ms?`, `summary?` | **Live:** optional inline `tool_rows[]` on the step card. **Resume:** footer stats only (`tool_call_count`); inline rows are not replayed (`sanitize_resume_display_cards`). Phase ∈ `{running, success, error}` |
| `cognition_plan` | `iteration`, `action`, `status`, `assessment?`, `strategy?` | Updated as plan reflects |
| `cognition_reason` | `iteration`, `content` | Per `soothe.cognition.strange_loop.reasoned` |
| `subagent` | `task`, `progress[]`, `success?` | Roll-up of subagent stream — not one card per chunk |
| `error` | `code`, `message`, `context?` | From `soothe.error.*` events |
| `system_notice` | `content`, `kind` (e.g., `loop_switch`, `summarization`, `clarification`) | `/loops` switch banners, summarization notices, clarification relays |

Future kinds (image attachments, MCP-specific tool cards, etc.) extend the catalogue server-side without client changes — clients render unknown kinds via a generic fallback widget.

---

## 9. Architectural Constraints

1. **Binder runs off the publish hot path.** A bounded queue between the daemon event bus and the `CardBinder` task isolates binding latency from live broadcast. Under pressure, emit `stream_degraded`; the ledger MUST remain durable (overflow deque / zero-loss ingest). Live `soothe.card.*` may lag; SoT stays correct for attach/resume.
2. **Ledger is single-writer.** Exactly one daemon process writes a given loop's display mutations. Multi-daemon deployments require a loop-to-daemon affinity rule (already true per RFC-450 / daemon communication).
3. **Wire schema is load-bearing.** Mutations carry `card_schema_version` (header). Daemon must read all prior versions; clients tolerate unknown fields and unknown card kinds.
4. **No client-side card construction.** Once Phase 4 lands, the TUI's live stream→card binders are removed. Live frames and resume hydrate go through the same renderer.
5. **Backfill is read-only-safe.** Backfilling an old loop must not lose data; if `CardBinder` cannot produce a card (e.g., a missing iteration), the ledger records a `system_notice` rather than silently skipping.
6. **Sequence numbers are monotonic and gap-free within the active live goal segment.** After RFC-631 freeze/reset, `seq` may restart for the new segment; historical goals are addressed by snapshot index, not live `seq`. Clients that need `after_seq` reconnect within a segment use the current segment's `seq`.

---

## 10. Trade-offs and Rejected Alternatives

### 10.1 Why JSONL over Other Stores

| Option | Verdict |
|---|---|
| **LangGraph state channel** | Rejected. Checkpoint commits serialize the entire channel value per iteration → O(N²) write cost; couples display projection to graph state, violating RFC-000 "unbounded context, bounded projection"; hard to GC independently. |
| **SQLite per loop** | Rejected. Cards are pure append-only single-writer single-reader; relational layer adds schema/migration cost without enabling needed queries. One DB per loop scales poorly; one shared DB introduces hot-path lock contention. |
| **Shared SQLite `display.db`** | Default for `persistence.default_backend: sqlite`. Compact local ledger under `$SOOTHE_HOME/data/`. |
| **PostgreSQL `soothe_metadata`** | Chosen when `persistence.default_backend: postgresql` (RFC-612). Same schema as SQLite (`display_card_mutations`, `goal_display_snapshots`); avoids host-mounted SQLite corruption under Docker/Colima bind mounts. |
| **JSONL per loop** | Historical choice superseded by shared SQLite (IG-529), then by backend-aware store selection above. |

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

**Phase 1 — `/loops`-switch history load.** ✅ Shipped.  
Wire switch/resume paths to load history after successful loop switch.

**Phase 2 — Extract `CardBinder` as a pure module.** ✅ Shipped.  
`soothe_sdk.display.card_binder` owns conversion rules; unit-tested.

**Phase 3 — Daemon owns binder + ledger; `soothe.card.*` + `loop_history_fetch`.** ✅ Largely shipped.  
* `LoopCardManager` ingests stream tuples off the hot path; persists via DisplayCardStore (SQLite/Postgres).  
* RFC-631 goal snapshots + `loop_history_fetch` for resume.  
* `loop_reattach` streams `soothe.card.replay.*` for the live tail.  
* Resume policy IG-577 (`sanitize_resume_display_cards`).  
* **Gap:** live TUI still binds from raw stream events; ledger often `replace_with` full rebind on debounce rather than append mutations + live `soothe.card.*` emit.

**Phase 4 — Live cutover + decommission (IG-655).** ✅ Shipped (2026-07-27):

| Stage | Work | Status |
|---|---|---|
| **4.1** | Structural parity audit for resume/attach vs catalogue (§8 / §15) | Done |
| **4.2** | Append-oriented mutations; emit live `soothe.card.*` as `event`/`custom` | Done |
| **4.3** | TUI consumes `soothe.card.*`; suppress duplicate raw user/assistant mounts | Done |
| **4.4** | Always-on daemon projection; skip raw cognition/assistant mounts; step cards from ledger register into tool router; keep raw tool-row updates on step widgets | Done |

**Fidelity locked for Phase 4:** structural parity only (user, cognition/plan/reason, step + tool **counts**, assistant text, subagent rollups, error, system notice). Inline tool rows remain live-only via raw tool wire onto ledger-mounted step cards (§15).

**Hydrate policy:** clients prefer `loop_history_fetch` first; apply live `soothe.card.*` idempotently by `card_id`. `soothe.card.replay.*` remains for subscribers that skip fetch.

**Assistant streaming:** coalesce assistant `soothe.card.updated` on the existing debounce flush; main-namespace TUI no longer mounts standalone assistant cards from raw `messages` mode.

---

## 12. Success Criteria

1. **Live ≡ Replay invariant (structural):** user-visible transcript structure matches after `/resume`, `loop continue`, or attach — user prompts, cognition/step/plan cards, assistant text, subagent rollups, errors, system notices. Inline step/subagent tool rows are **live-only**; resume shows tool-call **counts** on step footers (§15).
2. **All resume/attach paths converge** on DisplayCardStore output (`loop_history_fetch` + live `soothe.card.*`), not a second client binder.
3. **Subagent cards** appear on replay when frozen in the goal snapshot.
4. **Step tool activity on resume:** `step_tool_call_count` preserved; standalone `TOOL` cards and inline tool-row replay suppressed (IG-577).
5. **Disk cost** stays under ~1 MB per 100-turn loop (mutation store).
6. **Replay latency** under 100 ms first-paint, under 500 ms full hydrate for 100-turn loops.
7. **Phase 4:** Live TUI structural cards come only from daemon-bound payloads; two subscribers on one loop observe the same card ids and ordered segment `seq`.
8. **Appkit / protocol-1 clients** (RFC-629) can consume `soothe.card.*` with zero CLI-specific binding code.
9. **Persistence** remains unified — no SQLite display writes when `default_backend: postgresql`.

---

## 13. Open Questions

1. **Card schema versioning policy.** When does a card-schema bump require a wire-protocol bump? Likely only for breaking field renames or kind removals; additive fields are forward-compatible.
2. **Backfill failure handling.** Prefer `system_notice` placeholder over refuse-to-resume (§9 constraint 5).
3. **Concurrent client reads during write.** Covered by DisplayCardStore (SQLite/Postgres), not file-tail JSONL; keep integration coverage for multi-subscriber.
4. **`after_seq` on schema upgrade.** Schema-version mismatch triggers full hydrate via `loop_history_fetch` rather than diff.
5. **Tool-row identity across retries.** Sibling rows for distinct attempts (live-only); resume keeps counts only.
6. **Raw stream retention after Phase 4.** Keep raw broadcast for headless / non-UI consumers; UI ignores raw for structural card construction.

---

## 15. Resume display policy (IG-577)

**Implemented 2026-07-11.** Clients fetching history via `loop_history_fetch` / `loop_cards_fetch` apply `sanitize_resume_display_cards()` before mount:

| Data | Live | Resume |
|------|------|--------|
| Step card header + summary | Yes | Yes |
| Step `tool_call_count` footer | Yes | Yes |
| Inline step/subagent tool rows | Yes | **No** (stripped) |
| Standalone `TOOL` cards | Never (live) | **No** (dropped) |
| `intent_classify` / planning checkpoint rows | Never (live) | **No** (binder filter) |
| Cognition plan/reason cards | Yes | Yes (from activity log replay) |

Binder module: `soothe_sdk.display.card_binder` — expanded `_LOOP_INTERNAL_CHECKPOINT_PHASES`, always suppresses checkpoint `ToolMessage` pairs, removed offline `_build_step_tool_rows_map` replay attachment.

TUI (pre–Phase 4.3): `_fetch_loop_history_data` → sanitize → `message_to_widget`; live path still binds from raw stream. Phase 4.3+ live path consumes `soothe.card.*`.

---

## 16. Phase 4 completion notes (2026-07-27)

Design draft: [`docs/drafts/2026-07-27-tui-card-replay-source-of-truth-design.md`](../drafts/2026-07-27-tui-card-replay-source-of-truth-design.md). Implementation guide: **IG-655**.

**End state:** daemon appends mutations to DisplayCardStore and broadcasts `soothe.card.*` in parallel; zero clients still persist (detached); attach/resume hydrates from SoT then continues on the same frame stream; multiple clients see identical structural transcripts.

**Non-goals restated:** full tool-row replay; per-loop JSONL as SoT; client MessageStore as authority.

---

## 14. References

* RFC-000 — System Conceptual Design (unbounded context, bounded projection)
* RFC-401 — Event Processing
* RFC-403 — Unified Event Naming Semantics
* RFC-411 — Event Stream Replay & History Reconstruction (superseded by this RFC)
* RFC-450 — Daemon Communication Protocol
* RFC-503 — Loop-First User Experience
* RFC-631 — Goal Display Snapshots
* RFC-612 / RFC-801 — Persistence backends (DisplayCardStore placement)
* RFC-631 — Goal Display Snapshots
* Design draft (2026-06-04): `docs/archive/drafts/2026-06-04-resume-loop-display-design.md`
* Design draft (2026-07-27): `docs/drafts/2026-07-27-tui-card-replay-source-of-truth-design.md`
* IG-655 — Phase 4 live cutover

---

*RFC-413 generated from Platonic Coding Phase 1 RFC formalization; Phase 4 plan updated 2026-07-27.*
