# TUI Card Replay: Daemon Display Source of Truth (Phase 4 Completion)

**Status:** Draft — Platonic Coding Phase 0 (Brainstorming output)
**Date:** 2026-07-27
**Authors:** xiaming (with Composer)
**Related:** RFC-413 (Server-Owned Display Card Ledger), RFC-631 (Goal Display Snapshots), RFC-450 (Daemon Protocol), RFC-505 (Desktop Client), IG-577 (Resume Transcript Hardening)
**Supersedes / refines:** Completes the unfinished Phase 4 end state of RFC-413; does not replace RFC-413 or RFC-631

**Formalized:** 2026-07-27 — decisions merged into [RFC-413](../specs/RFC-413-server-owned-display-card-ledger.md) (§11 Phase 4, §16); implementation tracked in [IG-655](../impl/IG-655-display-card-phase4-live-cutover.md).

---

## 1. Problem

Daemon already persists a display projection (`LoopCardManager` → `DisplayCardStore` / goal snapshots) and resume uses `loop_history_fetch`. Live TUI still binds cards from raw stream events in the client. That split means:

- Live and resume can drift whenever a new card kind or binder rule ships.
- Multiple clients attached to the same loop each re-bind independently.
- `card.*` reattach frames exist on the daemon, but the TUI does not consume them for live rendering.
- Ledger flushes often **rebuild** the live segment via `replace_with` rather than appending true create/update/finalize mutations suitable for live broadcast.

The product goal is **structural parity** between live and resume/attach — not byte-for-byte live fidelity (inline tool rows remain live-only per IG-577).

---

## 2. Decisions (locked in brainstorm)

| Decision | Choice |
|---|---|
| Resume fidelity | **A — structural parity**: user prompts, cognition/plan/reason, step cards + tool **counts**, assistant text, subagent rollups, errors, system notices. Inline step/subagent tool rows are live-only. |
| Long-term architecture | **Daemon owns projection**; clients are passive renderers for **both** live and resume. |
| Delivery | **Staged** to that end state (harden SoT → mutation stream + `card.*` → TUI cutover → decommission client binders). |
| Persistence SoT | Existing **DisplayCardStore** (SQLite `display.db` or PostgreSQL `soothe_metadata` per `persistence.default_backend`). **Not** per-loop `cards.jsonl` as authority. Optional JSONL export for debug only. |

---

## 3. Goals and Non-Goals

### 3.1 Goals

1. One binder (`soothe_sdk.display.card_binder`) runs in production only inside the daemon.
2. Live wire and resume hydrate the same card kinds with the same structural fields.
3. Detached loops keep writing the ledger; attach/resume replays SoT then continues on the same live frame stream.
4. Multiple subscribers to one loop see identical card sequences (`seq`-ordered).
5. TUI (then desktop / appkit) delete local stream→card construction for the catalogue in scope.

### 3.2 Non-Goals

- Replaying inline tool rows / streaming intermediate tool UI on resume.
- Replacing unified display persistence with per-loop JSONL as SoT.
- Client-local MessageStore as authoritative history.
- Per-user fold/expand persistence.
- Historical scrub UI (“cards as of iteration N”) — mutation log may enable it later; not required now.

---

## 4. Current State (baseline)

```text
Runner stream
    ├─► broadcast raw tuples / event_batch → TUI local bind → widgets   (live)
    └─► LoopCardManager.ingest (always) → CardBinder → DisplayCardStore
            ├─ live tail (often replace_with on debounce flush)
            └─ freeze → GoalDisplaySnapshot (RFC-631)

Resume/attach:
    TUI → loop_history_fetch (snapshots + live_cards) → mount widgets
    loop_reattach → card.replay_* (live tail) — TUI does not drive live UI from card.*
```

Key modules today:

| Role | Location |
|---|---|
| Binder | `soothe_sdk.display.card_binder` |
| Ledger / ingest | `soothe_daemon.display.loop_card_manager`, `loop_card_ledger` |
| Store | `soothe_daemon.display.display_store` (+ postgres) |
| Reattach | `soothe_daemon.event.reattachment` |
| Live TUI bind | `soothe_cli.tui.textual_adapter`, `tui/app/_history.py` |
| Resume hydrate | `tui/app/_messages_mixin._load_loop_history` + `_fetch_loop_history_data` |

---

## 5. Target Architecture

```text
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
        │              └─► wire card.created / card.updated / card.finalized
        │                        │
        │                        ▼
        │                 all loop subscribers (0..N)
        │
        └─► (optional) still broadcast raw stream for non-UI consumers
            until decommission; UI ignores raw for card construction

Attach / resume:
  loop_history_fetch → snapshots + live_cards → same client renderer as card.*
  then subscribe → card.replay_* (if needed) + live card.*
```

### 5.1 Components

**`LoopCardManager` (daemon)**  
Owns per-loop ingest workers, debounce, binder invocation, persistence, and `card.*` emission. Must become **append-oriented**: each bind pass produces new mutations (create/update/finalize), not a wholesale `replace_with` of the live segment (except goal reset / explicit repair).

**`DisplayCardLedger` + `DisplayCardStore`**  
Authoritative live-tail mutation log and folded card snapshot. Goal completion still freezes via RFC-631 `GoalDisplaySnapshot` and resets the live segment.

**Wire (`card.*`)**  
Already defined in RFC-413: `card.created`, `card.updated`, `card.finalized`, `card.replay_begin`, `card.replay_end`, each with monotonic `seq` per loop (or per live segment — see open questions). Clients apply frames to a `card_id → widget` map.

**Client renderer**  
Mount/update widgets from bound `MessageData` (or wire dict). Resume path already does this after `loop_history_fetch`; live path must converge on the same code.

### 5.2 Structural card catalogue (parity set)

| Kind | Live | Resume / attach |
|---|---|---|
| `user_message` | Yes | Yes |
| `assistant_text` | Yes | Yes (consolidated) |
| `step` (+ `tool_call_count`) | Yes | Yes (no inline tool rows) |
| `cognition_plan` / `cognition_reason` | Yes | Yes |
| `subagent` rollup | Yes | Yes when frozen / bound |
| `error` / `system_notice` | Yes | Yes |

`sanitize_resume_display_cards` remains the policy gate for resume-only stripping of live detail.

---

## 6. Data Flows

### 6.1 Live turn (detached or attached)

1. Runner emits stream tuples; `QueryEngine` broadcasts raw events (compat) and enqueues `ingest_stream_tuple`.
2. Ingest worker buffers messages / derivable custom events; debounce flush runs binder.
3. Diff against previous live projection → append mutations to store; assign `seq`.
4. For each mutation, broadcast `card.*` to loop subscribers (no-op if zero clients).
5. On goal idle: freeze snapshot, reset live ledger, emit any terminal system card if needed.

### 6.2 Client attach / resume

1. Client calls `loop_history_fetch(loop_id)` → ordered goal snapshots + `live_cards`.
2. Client clears local transcript for that loop, mounts structural cards (sanitized).
3. Client `loop_subscribe` / reattach; daemon may emit `card.replay_*` for live tail if client did not already apply `live_cards` (prefer **one** hydrate path — see open questions).
4. Subsequent live `card.*` frames apply as diffs; ignore duplicate `card_id` creates after hydrate.

### 6.3 Multi-client

- Ledger write is single-writer (daemon process affinity unchanged).
- Each subscriber receives the same `card.*` stream after its own hydrate.
- Late joiner: `loop_history_fetch` (or reattach replay) then live frames; no client-to-client sync.

---

## 7. Migration Plan (staged)

### Stage 1 — Parity audit (resume/attach SoT)

- Inventory structural gaps vs live catalogue for `loop_history_fetch` / reattach.
- Fix binder/store holes only; no TUI live cutover yet.
- Acceptance: attach to detached running loop and `loop continue` show the structural set in §5.2.

### Stage 2 — True mutation stream + live `card.*` emit

- Replace debounce `replace_with` full rebuild with append create/update/finalize (goal reset still replace/clear).
- Emit `card.*` on apply; keep raw broadcast for compatibility.
- Tests: mutation ordering, multi-subscriber identical `seq`, overflow/`stream_degraded` does not drop ledger durability.

### Stage 3 — TUI live cutover

- TUI renders live from `card.*` (and initial hydrate from `loop_history_fetch`).
- Feature flag / short dual-path window: if `card.*` missing, fall back to raw bind once.
- Background consumer and `textual_adapter` stop constructing structural cards from raw events.

### Stage 4 — Decommission

- Remove TUI live stream→card binders for the structural catalogue.
- Document wire contract for desktop (RFC-505) and appkit consumers.
- Mark RFC-413 Phase 4 complete; update change history.

---

## 8. Error Handling and Backpressure

- Ingest queue remains bounded with overflow deque (zero-loss to ledger); emit `stream_degraded` when pressure rises (existing).
- Binder failures: log + `system_notice` card; do not crash the runner stream.
- Store write failure: fail the mutation apply; do not broadcast a card the store did not accept (SoT stays ahead of or equal to wire).
- Corrupt / empty legacy loops: lazy snapshot migration (existing) or `system_notice` placeholder; never silent empty success when store errors.

---

## 9. Testing Strategy

| Layer | Coverage |
|---|---|
| Unit | Binder structural catalogue; mutation diff (create vs update); `sanitize_resume_display_cards` |
| Daemon unit | Append vs replace; freeze+reset; `fetch_loop_history` shape; `card.*` emission order |
| Integration | Detached run → attach → structural parity; two clients same loop identical card ids/`seq`; Postgres + SQLite backends |
| CLI/TUI | Live cutover: mount/update from `card.*`; resume after Stage 3 uses same renderer |

Do not weaken tests to match incomplete live bind; fix binder/ledger instead (AGENTS.md §8).

---

## 10. Storage Clarification

RFC-413 originally described `~/.soothe/data/loops/<loop_id>/cards.jsonl`. That layout is **historical**. Authoritative storage is:

- SQLite: display card mutations + goal snapshots in `display.db` (under SOOTHE data dir)
- PostgreSQL: same logical tables in `soothe_metadata` when `persistence.default_backend: postgresql`

A debug export to JSONL under the loop folder is optional and non-authoritative.

---

## 11. Open Questions (to resolve in RFC refine / IG)

1. **Hydrate dedupe:** Prefer `loop_history_fetch` only on attach, and skip `card.replay_*` for clients that already applied `live_cards`? Or always replay and make clients idempotent?
2. **`seq` scope:** Monotonic for entire loop lifetime vs reset per live goal segment after freeze?
3. **Raw stream retention:** Keep raw broadcast indefinitely for headless/JSONL consumers, or scope-reduce after UI cutover?
4. **Assistant streaming:** Should live assistant tokens still use a dedicated stream frame, with `card.updated` only on coalesce boundaries, to avoid one mutation per token?

Provisional answers for implementation start: (1) fetch-first + idempotent clients; (2) reset `seq` per live segment with snapshot index for history; (3) keep raw for non-UI; (4) coalesce assistant updates (debounce aligned with existing flush).

---

## 12. Success Criteria

1. Live TUI structural cards are produced only from daemon-bound payloads (`card.*` and/or hydrate RPC), not from a second client binder.
2. Detached → attach and `loop continue` show the §5.2 catalogue with tool **counts**, without requiring the original client session.
3. Two subscribers on one loop observe the same card ids and ordered `seq` for live updates.
4. Resume policy IG-577 unchanged (no inline tool-row replay).
5. Display persistence remains backend-unified (no new SQLite path under Postgres mode).

---

## 13. Relationship to Existing Specs

- **RFC-413:** This draft is the completion plan for Phase 4; formalization should **update RFC-413** (status, Phase 4 details, storage note, migration) rather than spawn a parallel architecture RFC unless scope balloons.
- **RFC-631:** Unchanged contract for goal snapshots + live tail; Stage 2–3 must preserve freeze/reset.
- **IG follow-up:** After RFC refine, prefer a new IG for Phase 4 cutover (or revive/extend archived display IGs only if numbering/process requires).

---

*End of design draft.*
