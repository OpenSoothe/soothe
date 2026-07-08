# Goal-Bound Display Snapshots for Loop History Recovery

**Status:** Approved design draft (Platonic Coding Phase 0)
**Date:** 2026-07-05
**Authors:** xiaming (with Claude)
**Related:** RFC-413 (Display Card Ledger), RFC-225 (Goal Record Enrichment), RFC-450 (Daemon Protocol), RFC-503 (Loop-First UX)

---

## 1. Problem

RFC-413 unified live and replay card binding, but **card mutations are the wrong durability grain** for multi-goal loop history:

- Card ingest is async, stream-derived, and unbounded (hundreds of mutations per goal).
- User prompts and goal boundaries are not first-class in the flat card stream.
- Resume depends on `loop_cards_fetch` replaying the full ledger — fragile under races and backfill gaps.
- Observed on loop `019f3093-…`: 328 cards in `display.db`, only one user card across multiple goals; resume failed with duplicate widget IDs when history loaded twice.

Meanwhile, **goal history is already readonly** after completion (RFC-225 `GoalExecutionRecord` in checkpoint). Execution truth exists; display recovery does not use it.

---

## 2. Decision (Option C)

| Segment | Source | Fidelity | Mutability |
|---------|--------|----------|------------|
| Completed goals | `GoalDisplaySnapshot` | Execution-complete + **collapsed** display | Immutable after write |
| Current goal | Card ledger + live `card.*` stream | **Display-faithful** (streaming) | Live append until goal ends |

**Keep** CardBinder, MessageData wire shape, TUI widgets, and live streaming. **Change** what is durable and how resume composes history.

```text
Loop transcript = snap(goal₀) ⊕ snap(goal₁) ⊕ … ⊕ snap(goalₙ₋₁) ⊕ live_tail(goalₙ)
```

---

## 3. GoalDisplaySnapshot

Written once when checkpoint transitions `running → idle`.

```text
GoalDisplaySnapshot
├── identity: goal_id, goal_index, goal_text
├── lifecycle: status, started_at, completed_at, duration_ms, tokens_used
├── execution (for /history, continuation, debug)
│   ├── plan_summary
│   ├── step_outcomes[]
│   └── goal_completion
└── display (collapsed MessageData[] for transcript resume)
    ├── user (exactly one)
    ├── cognition_* (final state per iteration; no streaming ticks)
    ├── step_* (terminal card per step_id)
    └── assistant (consolidated final answer)
```

**Collapse rules** (daemon-side at freeze, same binder):

- Cognition: final plan + final reason per iteration.
- Steps: terminal step card per `step_id`.
- Assistant: one consolidated card (`stop_stream` equivalent).
- Tool rows folded into step cards where possible.

---

## 4. Storage

New table in `display.db`:

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
```

Card mutation table retains **live tail only** for the active goal. On freeze: fold segment → snapshot, reset live ledger for next goal.

---

## 5. Write Path

Hook: goal completion (same boundary as RFC-225 `GoalExecutionRecord` mirror).

```text
running → idle
  1. CardManager.freeze_goal_display(loop_id, goal_index)
  2. CardManager.reset_live_ledger(loop_id)
  3. (existing) persist GoalExecutionRecord
```

Freeze failure: log warning, emit `system_notice`; do not block goal completion.

---

## 6. Read Path

New RPC `loop_history_fetch(loop_id)`:

```json
{
  "goals": [ "GoalDisplaySnapshot wire dicts, ordered by goal_index" ],
  "live_cards": [ "MessageData wire dicts for current goal" ],
  "live_goal_index": 2,
  "context_tokens": 12345
}
```

TUI: `flatten(g.display.cards) + live_cards` → dedupe by id → mount window.

`/history`: render execution sections from `goals[]`.

`loop_cards_fetch`: deprecated wrapper returning flattened view for old clients during migration.

Reattach replay: **live tail only** (small N), not full loop.

---

## 7. Migration

Lazy per loop on first `loop_history_fetch`:

- For each completed `GoalExecutionRecord` in checkpoint: synthesize snapshot from execution fields + best-effort fold of existing card mutations in that goal's range.
- Mark loop migrated.

---

## 8. What Stays Unchanged

- CardBinder and live ingest queue
- `MessageData` / `message_to_widget` / TUI widgets
- Live streaming via `textual_adapter` and bg event consumer
- GoalExecutionRecord as execution authority

---

## 9. Phasing

| Phase | Deliverable |
|-------|-------------|
| P0 | Snapshot write + `loop_history_fetch` + TUI resume switch |
| P1 | `/history` structured view + lazy migration |
| P2 | Live-only card ledger; deprecate full-loop backfill |
| P3 | Desktop / appkit consume `loop_history_fetch` |

---

## 10. Success Criteria

1. Multi-goal loop resume shows every completed goal's user prompt and collapsed transcript.
2. In-flight goal resume shows frozen prior goals + live tail without duplicate widget IDs.
3. Trivial fast-path goals produce snapshots (user + assistant).
4. Resume read cost O(goals + live_tail), not O(total card mutations).
5. CardBinder and TUI rendering code reused without a second display stack.

---

## 11. Downstream Artifacts

- **RFC-631**: Goal Display Snapshots (normative)
- **RFC-413 amendment**: live-only ledger role
- **RFC-225 amendment**: display freeze at goal completion
- **RFC-450 amendment**: `loop_history_fetch` RPC
- **IG-548**: Implementation guide
