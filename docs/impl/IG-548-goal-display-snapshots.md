# IG-548: Goal-Bound Display Snapshots

**RFC**: [RFC-631](../specs/RFC-631-goal-display-snapshots.md), [RFC-413](../specs/RFC-413-server-owned-display-card-ledger.md) (amended), [RFC-225](../specs/RFC-225-loop-continuity-and-goal-record-enrichment.md) (amended), [RFC-450](../specs/RFC-450-daemon-communication-protocol.md)  
**Design**: [docs/drafts/2026-07-05-goal-display-snapshot-design.md](../drafts/2026-07-05-goal-display-snapshot-design.md)  
**Created**: 2026-07-05  
**Status**: In progress (P0 + P1 landed)  
**Priority order**: P0 → P1 → P2

---

## Executive Summary

Implement immutable **goal display snapshots** at goal completion and switch loop resume to `loop_history_fetch` (frozen goals + live card tail). Keeps RFC-413 CardBinder and TUI rendering; changes durability grain from unbounded card mutations to goal-bound snapshots.

---

## Phase P0 — Core path (resume works)

| Task | Status | Files / notes |
|------|--------|---------------|
| P0.1 `GoalDisplaySnapshot` types + wire serde | Pending | `soothe_sdk/display/snapshot_types.py` |
| P0.2 `SnapshotCollapser.fold()` | Pending | `soothe_sdk/display/snapshot_collapser.py` — unit tests with canned card lists |
| P0.3 `goal_display_snapshots` schema + store CRUD | Pending | `soothe/backends/persistence/display_store.py` |
| P0.4 `LoopCardManager.freeze_goal_display()` | Pending | `soothe_daemon/display/loop_card_manager.py` |
| P0.5 `reset_live_ledger()` after freeze | Pending | `soothe_daemon/display/loop_card_ledger.py` |
| P0.6 Hook freeze on goal idle | Pending | `strange_loop.py` / `sloop_manager.py` — same path as RFC-225 §6.4 |
| P0.7 `loop_history_fetch` router handler | Pending | `soothe_daemon/protocol/router.py`, `schemas.py` |
| P0.8 SDK protocol params + session fetch | Pending | `soothe_sdk/client/protocol_params.py`, `soothe_cli/runtime/transport/session.py` |
| P0.9 TUI `_fetch_loop_history_data` switch | Pending | `soothe_cli/tui/app/_history.py` |
| P0.10 TUI load guard + dedupe (keep existing fix) | Pending | `soothe_cli/tui/app/_messages_mixin.py` |
| P0.11 Reattach replay live tail only | Pending | `soothe_daemon/event/reattachment.py`, `loop_card_manager.replay_to_client` |
| P0.12 `loop_cards_fetch` compatibility wrapper | Pending | Returns flattened `loop_history_fetch` response |

**Exit criteria**

- [ ] Multi-goal loop resume shows all completed goals' user prompts + collapsed cards
- [ ] In-flight goal resume: prior snapshots + live tail; no duplicate widget IDs
- [ ] Trivial goal produces snapshot (user + assistant)
- [ ] Unit tests: collapser, store, freeze hook (daemon)
- [ ] Integration: `loop_history_fetch` e2e in `test_protocol1_e2e.py`

---

## Phase P1 — `/history` + migration

| Task | Status | Files / notes |
|------|--------|---------------|
| P1.1 Lazy migration on first fetch | Pending | `LoopCardManager.ensure_snapshots_migrated()` |
| P1.2 Synthesize snapshots from checkpoint + legacy cards | Pending | Uses `GoalExecutionRecord` + mutation time ranges |
| P1.3 `/history` structured rendering | Pending | TUI command handler — execution section from `goals[]` |
| P1.4 Daemon `history` RPC returns snapshot execution sections | Pending | Optional: extend existing `history` method |

**Exit criteria**

- [ ] Loop `019f3093-…` class loops migrate on first resume
- [ ] `/history` lists goals with plan summary and step outcomes

---

## Phase P2 — Live-only ledger cleanup

| Task | Status | Files / notes |
|------|--------|---------------|
| P2.1 Stop full-loop card mutation retention | Pending | Trim on freeze; optional archive table |
| P2.2 Remove lazy full-ledger backfill on fetch | Pending | `loop_card_manager.ensure_for_loop` |
| P2.3 Deprecate `loop_cards_fetch` (log warning) | Pending | Router + docs |
| P2.4 Remove duplicate `_load_loop_history` scheduling remnants | Pending | Verify `_startup.py` single path |

**Exit criteria**

- [ ] `display_card_mutations` row count bounded per active goal
- [ ] Reattach never replays > live tail size

---

## Phase P3 — Multi-client

| Task | Status | Files / notes |
|------|--------|---------------|
| P3.1 Go / TS appkit `LoopHistoryFetch` | Pending | `client/go`, `client/typescript` |
| P3.2 Desktop transcript resume | Pending | RFC-505 consumers |

---

## Key Implementation Notes

### Freeze hook location

Co-locate with RFC-225 §6.4 / §6.5 write path — when `StrangeLoopCheckpoint.status` transitions to `idle` and `GoalExecutionRecord` is finalized:

```python
await card_manager.freeze_goal_display(loop_id, goal_index, goal_record)
await card_manager.reset_live_ledger(loop_id)
```

### Collapser algorithm (sketch)

```python
def fold(cards: list[MessageData]) -> list[MessageData]:
    # 1. Keep last card per id (terminal state)
    # 2. Drop in-progress duplicates for step/cognition kinds
    # 3. Ensure exactly one USER card (from goal_text if missing)
    # 4. Ensure one ASSISTANT final (from goal_completion if missing)
    # 5. Preserve insertion order of surviving cards
```

### TUI resume assembly

```python
payload = await session.fetch_loop_history(loop_id)
cards = [c for g in payload.goals for c in g.display_cards] + payload.live_cards
cards = dedupe_by_id(cards)  # last wins
message_store.bulk_load(cards, replace=True)
```

### What NOT to change

- `CardBinder` live binding rules
- `message_to_widget` / TUI widget classes
- `textual_adapter` streaming pipeline
- Live `card.created` wire frames during active turns

---

## Testing

```bash
# Unit
uv run pytest packages/soothe-sdk/tests/unit/display/test_snapshot_collapser.py -q
uv run pytest packages/soothe-daemon/tests/unit/display/test_goal_snapshot_freeze.py -q
uv run pytest packages/soothe-cli/tests/unit/tui/test_loop_history_load_guard.py -q

# Integration
uv run pytest packages/soothe-daemon/tests/integration/protocol/test_protocol1_e2e.py -k loop_history_fetch -q

# Full verify before commit
./scripts/verify_finally.sh
```

---

## Related Work

- Resume duplicate widget fix (TUI load guard) — prerequisite, already landed in working tree
- RFC-413 card ingest isolation (IG-534) — live path unchanged
- Trivial fast-path checkpoint finalize — ensures goals reach idle for freeze hook
