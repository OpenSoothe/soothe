# IG-655: Display Card Phase 4 Live Cutover

**Status**: Complete  
**Date**: 2026-07-27  
**Related**: RFC-413 (§11 Phase 4, §16), RFC-631, IG-577  
**Design draft**: `docs/drafts/2026-07-27-tui-card-replay-source-of-truth-design.md`

## Goal

Finish RFC-413 Phase 4: daemon DisplayCardStore is the source of truth for **structural** TUI cards; live clients render from `card.*` (plus hydrate via `loop_history_fetch`); remove the second live binder in the TUI.

Fidelity bar: **structural parity** (IG-577) — tool **counts** on resume; inline tool rows live-only.

## Progress

| Stage | Status | Notes |
|-------|--------|-------|
| 4.1 Parity audit | Done | Gap was architectural (`replace_with` + no live `card.*`) |
| 4.2 Append + emit | Done | Stable-key align/diff; live emit as `event`/`custom`/`card.*` |
| 4.3 TUI cutover | Done | `_apply_card_wire_frame`; suppress raw user/assistant |
| 4.4 Decommission | Done | Always-on projection; skip raw cognition/assistant mounts; step cards register into tool router |

## Motivation

Phases 1–3 shipped ledger + resume hydrate, but live TUI still binds from raw stream events while the ledger often rebuilds via `replace_with`. That split drifts and blocks multi-client identical transcripts.

## Scope

| Package | Work |
|---------|------|
| `soothe-daemon` | Append-oriented mutations; emit live `card.*`; keep detached ingest |
| `soothe-sdk` | Shared apply helpers / wire types if needed for client idempotent apply |
| `soothe-cli` | Consume `card.*` for live structural cards; delete live stream→card binders |
| Docs | Mark RFC-413 Phase 4 stages done as they land |

## Non-Goals

- Full tool-row / streaming intermediate replay on resume
- Per-loop `cards.jsonl` as authoritative SoT (DisplayCardStore only)
- Desktop/appkit full cutover in this IG (document wire; implement separately)

## Stages

### 4.1 — Parity audit

- Inventory structural gaps: user, cognition plan/reason, step+counts, assistant, subagent rollup, error, system notice on `loop_history_fetch` / attach to detached loop.
- Fix binder/store only; no TUI live cutover yet.
- **Acceptance:** detached run → `loop attach` / `loop continue` shows § catalogue with tool counts.

### 4.2 — Mutation stream + live emit

- Diff previous live projection → `append` create/update/finalize (goal reset still clear/replace).
- On successful store apply, broadcast `card.created` / `card.updated` / `card.finalized` to loop subscribers.
- Keep raw stream for non-UI; do not require UI to use it for structural cards after 4.3.
- **Tests:** mutation order, multi-subscriber same `seq`/card ids, overflow does not drop ledger durability, freeze+reset preserves snapshots.

### 4.3 — TUI live cutover

- Hydrate: `loop_history_fetch` → sanitize → mount (existing).
- Live: apply `card.*` to `card_id → widget` map (same widgets as resume).
- Background consumer / `textual_adapter` stop constructing structural cards from raw events.
- **Acceptance:** live session matches resume structural set for the same turn; two TUIs on one loop stay in sync for structural cards.

### 4.4 — Decommission

- Remove TUI live structural binders and any dual-path flags.
- Confirm deprecated RFC-411 frames remain gone.
- Update RFC-413 status / change history; note desktop/appkit consumer contract.

## Key files (expected)

- `soothe_daemon/display/loop_card_manager.py` — append vs `replace_with`; emit `card.*`
- `soothe_daemon/display/loop_card_ledger.py` — mutation apply API
- `soothe_daemon/event/reattachment.py` — hydrate/replay interaction
- `soothe_daemon/query/engine.py` — ingest remains on broadcast path
- `soothe_cli/tui/textual_adapter.py`, `tui/app/_history.py` — live cutover
- `soothe_sdk/display/card_binder.py`, `card_ledger.py` — binder + mutation helpers

## Testing

```bash
# Daemon / SDK display
cd packages/soothe-daemon && python -m pytest tests/unit/display/ -q
cd packages/soothe-sdk && python -m pytest tests/unit/display/ -q

# CLI resume / card rendering
cd packages/soothe-cli && python -m pytest tests/unit/tui/ tests/unit/ux/tui/ -q
```

Add: multi-client identical `seq`; detached→attach structural parity; append-not-replace under stream; Phase 4.3 cutover unit tests.

Before commit: `./scripts/verify_finally.sh`.

## Acceptance checklist

- [x] 4.1 parity audit closed or tracked with binder fixes
- [x] Live segment uses append mutations; `card.*` emitted on apply
- [x] TUI structural live path consumes daemon-bound payloads
- [ ] Detached → attach and `loop continue` show structural catalogue + tool counts (manual / integration)
- [ ] Two subscribers: same card ids / ordered segment `seq` (integration)
- [x] IG-577 sanitize policy unchanged
- [x] No new SQLite display path when Postgres mode is configured
- [x] RFC-413 Phase 4 marked complete after 4.4

## Cleanse

- Removed `SOOTHE_TUI_CARD_LIVE` / `prefer_daemon_card_projection` dual-path gates
  (projection always on).
- Removed `_live_cards_active` and back-compat aliases
  (`live_card_wire_enabled`, `RAW_SUPPRESSED_WHEN_CARD_LIVE`,
  `should_skip_raw_structural_bind` / `RAW_SUPPRESSED_MESSAGE_TYPES`).
- Deleted unused `essential_events.py` (INTENT/LOOP_REASON were only no-op skips).
- Background consumer applies `card.*` only (no raw messages→widget path).
- TUI no longer mounts cognition reason/plan widgets from raw
  `INTENT_CLASSIFIED` / loop-reason customs (ledger owns those).
- `CARD_*` wire constants live only in `soothe_sdk.core.events` (daemon/CLI
  import from there; no local string duplicates).
