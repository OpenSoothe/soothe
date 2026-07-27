# RFC-631: Goal-Bound Display Snapshots

**RFC**: 631
**Title**: Goal-Bound Display Snapshots for Loop History Recovery
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-07-05
**Authors**: xiaming (with Claude)
**Depends on**: RFC-225 (Goal Record Enrichment), RFC-413 (Display Card Ledger), RFC-450 (Daemon Protocol), RFC-503 (Loop-First UX)
**Related**: RFC-628 (Step Card Display), RFC-803 (Checkpoint Backend)
**Design**: [docs/archive/drafts/2026-07-05-goal-display-snapshot-design.md](../archive/drafts/2026-07-05-goal-display-snapshot-design.md)

---

## 1. Abstract

This RFC defines **goal-bound display snapshots** — immutable, collapsed display records written when a goal completes (`running → idle`). Loop history recovery becomes:

```text
transcript = concat(frozen snapshots for completed goals) + live card tail for the active goal
```

RFC-413's card ledger remains the **live projection buffer** for the in-flight goal. Completed goals no longer depend on unbounded card mutation replay. Clients reuse the same `MessageData` wire shape and renderers; only the resume fetch path changes.

---

## 2. Scope and Non-Goals

### 2.1 Scope

* `GoalDisplaySnapshot` schema (execution + collapsed display sections).
* `goal_display_snapshots` table in `display.db`.
* `CardManager.freeze_goal_display()` at goal idle transition.
* `loop_history_fetch` daemon RPC (RFC-450).
* TUI resume path switch from `loop_cards_fetch` to `loop_history_fetch`.
* Lazy migration for pre-existing loops.
* Reattach replay scoped to **live tail only**.

### 2.2 Non-Goals

* Replacing `GoalExecutionRecord` / checkpoint as execution authority.
* Pixel-perfect replay of every streaming tick for completed goals.
* Client-side widget or theme changes.
* Historical scrub UI ("show transcript as of goal N mid-flight").
* Removing CardBinder or live `soothe.card.*` frames.

---

## 3. Motivation

RFC-413 eliminated live/replay **binding drift** but persisted history at **card-mutation grain**. Symptoms in production:

* Missing user prompts across goal boundaries.
* Resume races when history load runs twice (duplicate widget IDs).
* Reattach replaying hundreds of cards while fetch also hydrates the ledger.
* `/history` and transcript resume share a lossy flat card list.

Goal history is **readonly after completion** (RFC-225). The durability boundary should match the goal lifecycle, not the streaming cadence of card updates.

---

## 4. Guiding Principles

1. **Goal boundary = freeze boundary.** One snapshot write per completed goal.
2. **Execution vs display separation.** Execution fields mirror `GoalExecutionRecord`; display fields are collapsed `MessageData[]`.
3. **Live tail stays display-faithful.** Current goal uses RFC-413 card ledger + streaming unchanged.
4. **Clients stay dumb renderers.** Collapse happens daemon-side at freeze; clients mount cards as today.
5. **Fail open on freeze errors.** Goal completion must not block if snapshot write fails.
6. **Lazy migration.** Old loops synthesize snapshots on first read; no destructive rewrite.

---

## 5. Component Overview

```text
LangGraph stream ──► CardBinder ──► LiveCardLedger (current goal only)
                                           │
                           goal idle ◄─────┘
                               │
                               ▼
                    SnapshotCollapser.fold()
                               │
                               ▼
                    GoalDisplaySnapshot ──► display.db
                               │
                               ▼
              loop_history_fetch ──► clients (TUI, desktop, appkit)
```

| Component | Package (target) | Role |
|-----------|------------------|------|
| `GoalDisplaySnapshot` | `soothe_sdk.display.snapshot_types` | Wire + storage schema |
| `SnapshotCollapser` | `soothe_sdk.display.snapshot_collapser` | Fold live cards → collapsed list |
| `GoalSnapshotStore` | `soothe.backends.persistence.display_store` | SQLite CRUD |
| `LoopCardManager.freeze_goal_display` | `soothe_daemon.display.loop_card_manager` | Orchestrate freeze + ledger reset |
| `loop_history_fetch` handler | `soothe_daemon.protocol.router` | Read path |

---

## 6. GoalDisplaySnapshot Schema

```python
@dataclass
class GoalDisplaySnapshot:
    goal_id: str              # "{loop_id}_goal_{seq}"
    goal_index: int           # 0-based position in loop
    goal_text: str            # user prompt
    status: str               # completed | failed | cancelled
    started_at: str           # ISO-8601 UTC
    completed_at: str | None
    duration_ms: int
    tokens_used: int
    # Execution section (/history, debug)
    plan_summary: dict[str, Any] | None
    step_outcomes: list[dict[str, Any]]
    goal_completion: str
    # Display section (transcript resume)
    display_cards: list[MessageData]  # collapsed, ordered
    card_count: int
    schema_version: int = 1
```

### 6.1 Collapse Rules

Applied by `SnapshotCollapser` over the live ledger segment at freeze time:

| Live behavior | Frozen representation |
|---------------|---------------------|
| Streaming cognition ticks | Final plan card + final reason card per iteration |
| Step in-progress updates | One terminal step card per `step_id` |
| Tool rows (live) | Inline on step card during active turn |
| Tool rows (resume) | **Omitted** — only `step_tool_call_count` on step footer (IG-577) |
| Assistant stream chunks | One consolidated assistant card |
| User prompt | Exactly one user card (required) |
| Subagent / error cards | Include if bound at freeze; omit if never created |

### 6.2 Invariants

* Every completed goal MUST have a snapshot row with `card_count >= 2` (user + assistant) for non-empty goals.
* `display_cards[].id` MUST be unique within a snapshot.
* Snapshots are **immutable** after insert; no update path in v1.

---

## 7. Storage

### 7.1 Table

Added to `display.db` (same database as `display_card_mutations`):

```sql
CREATE TABLE goal_display_snapshots (
    loop_id       TEXT NOT NULL,
    goal_index    INTEGER NOT NULL,
    goal_id       TEXT NOT NULL,
    frozen_at     TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    card_count    INTEGER NOT NULL,
    PRIMARY KEY (loop_id, goal_index)
);
CREATE INDEX idx_goal_snapshots_loop ON goal_display_snapshots(loop_id, goal_index);
```

### 7.2 Live Card Ledger Scope (RFC-413 amendment)

After this RFC:

* `display_card_mutations` stores mutations for the **active goal only**.
* On freeze, mutations for the completed goal are folded into the snapshot; the live ledger segment is **reset** (header + empty) before the next goal starts.
* Full-loop unbounded mutation retention is deprecated.

---

## 8. Write Path

### 8.1 Trigger

Same hook as RFC-225 §6.4: checkpoint transition `running → idle` after `GoalExecutionRecord` is finalized.

### 8.2 Sequence

```text
1. snapshot = SnapshotCollapser.fold(live_ledger.snapshot())
2. merge execution fields from active GoalExecutionRecord
3. GoalSnapshotStore.insert(loop_id, goal_index, snapshot)
4. live_ledger.reset_for_next_goal()
5. (existing) checkpoint save
```

### 8.3 Failure Handling

| Failure | Behavior |
|---------|----------|
| Collapse error | Log exception; skip snapshot insert; retain live ledger |
| DB insert error | Log exception; goal completion still succeeds |
| Missing user card | Synthesize from `goal_text`; log warning |

Emit optional `system_notice` card in live stream when freeze fails so operators can detect incomplete history.

### 8.4 Trivial Goals

Trivial fast-path goals (e.g. weather lookup) MUST still produce snapshots. Minimum: user card + assistant card.

---

## 9. Read Path

### 9.1 `loop_history_fetch` RPC

**Request** (RFC-450 `type: request`):

```json
{ "method": "loop_history_fetch", "params": { "loop_id": "<uuid>" } }
```

**Response**:

```json
{
  "loop_id": "<uuid>",
  "goals": [ "<GoalDisplaySnapshot wire dict>" ],
  "live_cards": [ "<MessageData wire dict>" ],
  "live_goal_index": 2,
  "context_tokens": 0,
  "success": true
}
```

| Field | Semantics |
|-------|-----------|
| `goals` | Frozen snapshots ordered by `goal_index` ascending |
| `live_cards` | Current goal tail from live ledger; empty when loop idle |
| `live_goal_index` | Index of active goal; `null` when idle |
| `context_tokens` | Best-effort persisted token count (same as `loop_cards_fetch`) |

**Client assembly** (IG-577):

```text
cards = flatten(goal.display_cards for goal in goals) + live_cards
cards = sanitize_resume_display_cards(cards)   # drop TOOL stubs; strip step_tool_calls_json
dedupe by MessageData.id (last wins)
merge_consecutive_assistant_cards(cards)
mount visible window
```

Resume shows step **tool-call counts** only; inline tool-row replay is live-only.

### 9.2 `loop_cards_fetch` (deprecated)

Retained during migration. Returns:

```text
{ "cards": flatten(goals.display_cards) + live_cards, "seq": ..., "context_tokens": ... }
```

New clients SHOULD use `loop_history_fetch`. Removal targeted for Phase P2 (IG-548).

### 9.3 Reattach Replay

`handle_loop_reattach` replays **live tail only** via `soothe.card.replay.*` (typically tens of cards, not hundreds). Completed goals come from snapshots via explicit fetch, not wire replay.

---

## 10. Migration

On first `loop_history_fetch` when `goal_display_snapshots` is empty for a loop:

1. Load `goal_history` from checkpoint (RFC-225 / RFC-803 `goal_records`).
2. For each completed goal, synthesize `GoalDisplaySnapshot`:
   * Execution section from `GoalExecutionRecord`.
   * Display section from best-effort fold of existing card mutations tagged to that goal's time range, or minimal user + assistant cards from `goal_text` / `goal_completion`.
3. Insert rows; set loop metadata flag `snapshots_migrated=true`.

Migration is idempotent and read-triggered.

---

## 11. Client Impact

### 11.1 TUI

| Area | Change |
|------|--------|
| `_fetch_loop_history_data` | Call `loop_history_fetch`; flatten goals + live tail |
| `_load_loop_history` | Dedupe before mount; load guard (single fetch per loop) |
| `message_to_widget` | **No change** |
| Live streaming | **No change** |
| `/history` | Render `goals[].execution` sections (Phase P1) |

### 11.2 SDK / Appkit

Add `loop_history_fetch` to protocol params and `TuiDaemonSession.fetch_loop_history()`.

---

## 12. Testing

| Test | Asserts |
|------|---------|
| Freeze on goal idle | Snapshot row exists; live ledger reset |
| Multi-goal resume | N snapshots + 0 live cards when idle |
| In-flight resume | N−1 snapshots + live tail; unique widget ids |
| Trivial goal | Snapshot with user + assistant |
| Collapse | 200 live mutations → ≤30 display cards |
| Migration | Legacy loop synthesizes snapshots on first fetch |
| Freeze failure | Goal still completes; warning logged |

---

## 13. Phased Rollout

| Phase | Scope |
|-------|-------|
| P0 | Schema, freeze hook, RPC, TUI resume |
| P1 | `/history` structured view, lazy migration |
| P2 | Live-only ledger enforcement; deprecate `loop_cards_fetch` |
| P3 | Desktop / Go / TS appkit |

See [IG-548](../impl/IG-548-goal-display-snapshots.md).

---

## 14. Relationship to Other RFCs

| RFC | Relationship |
|-----|--------------|
| RFC-413 | Card ledger scoped to live goal; binding rules unchanged |
| RFC-225 | Snapshot write co-located with `GoalExecutionRecord` finalize |
| RFC-450 | Adds `loop_history_fetch` method |
| RFC-503 | `/history` command consumes snapshot execution section |

---

## 15. Open Questions (defaults chosen)

1. **Trim old card mutations on freeze?** → Yes (reset live segment); historical mutations optional archive in P2.
2. **Snapshot in checkpoint vs display.db?** → `display.db` (presentation concern).
3. **Include failed/cancelled goals?** → Yes, with status preserved.
