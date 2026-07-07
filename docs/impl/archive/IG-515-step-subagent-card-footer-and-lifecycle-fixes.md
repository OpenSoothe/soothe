# IG-515: Step / SubAgent Card Footer & Lifecycle Fixes (RFC-628)

**Status**: Completed
**RFC**: [RFC-628](../specs/RFC-628-step-card-display-refactor.md)
**Depends on**: IG-512 (step card refactor), IG-513 (SubAgent card)
**Created**: 2026-06-27
**Verified against**: loop `6b34` (`019f04d2-d46c-7f92-ab31-793630406b34`), loop `ca30027` (`019f04f5-1d65-7302-8aab-781b9ca30027`)

## Problem Summary

After IG-513 landed, live TUI runs still showed incorrect step / SubAgent card behavior:

| Symptom | Loop `6b34` | Loop `ca30027` (partial) |
|---------|-------------|---------------------------|
| Step footer tool count wrong vs visible rows | `11 tools` footer, only Explore + ShellExecute visible | `8 tools, 1 task` footer, only Explore task row visible |
| SubAgent stuck running after step complete | Yes (`Running…` while step `Completed`) | No (completed) |
| SubAgent footer tool count wrong | `11 tools` (included step-wide total) | `8 tools` (executor step total, not subgraph scope) |
| Subgraph tools on step card ledger | Hidden in activity tree but counted in footer | Same |

Executor ground truth for `ca30027`: **8 step tools** = 7 subgraph (`YVC_01:t0:…`) + 1 main task return. RFC-628 flattened model expects **step footer: `1 task`** (0 main tools) and **SubAgent footer: `7 tools`**.

## Root Causes

1. **Dual subgraph ingestion paths** — Message-stream routing called `try_route_subgraph_tool` → step parent only; wire path routed to SubAgent when registered. Subgraph rows could land on the step card, inflating `StepRowIndex.total_tool_count` while `StepActivityTree` only renders `main_tools`.

2. **SubAgent lifecycle not wired** — `soothe.subagent.*.completed` events were dropped (`continue` with no handler). `sync_status_to_step()` existed but was never called. Step `STRANGE_LOOP_STEP_COMPLETED` finalized the step card only, not `_subagent_cards_by_key` entries.

3. **Server `tool_call_count` misuse** — `_status_tool_stats_suffix` promoted executor step totals (main + subgraph) over scope-local row index. Delegated steps showed subgraph counts on the step footer.

4. **SubAgent rows stripped on complete** — `mark_unfinished_tools_on_step_complete()` removed all type-`t` rows. SubAgent cards only hold type-`t` rows, so tool rows and counts were wiped before the footer rendered.

5. **Message-stream task path** — `_ingest_main_task_tool_on_step_card` return value (new SubAgent card) was ignored; SubAgent card not mounted from AIMessage stream path.

## Fixes

### 1. Unified subgraph routing (`textual_adapter.py`)

- Added `_route_subgraph_tool_call`, `_route_pending_subgraph_tools`, `_lookup_subagent_card`, `_rehome_subgraph_rows_to_subagent`.
- Message stream and wire stream both prefer SubAgent registry before step-card fallback.
- Mount SubAgent card from message-stream task ingestion via `_mount_subagent_card_if_needed`.
- `StepTaskRouter.discard_pending_subgraph_tool()` clears buffers after SubAgent ingest.

### 2. SubAgent completion (`textual_adapter.py`)

- `_apply_subagent_wire_lifecycle_event` handles `soothe.subagent.*.completed` / `.failed`.
- `_finalize_subagent_cards_for_step` runs on step complete, goal finalize, and error paths.
- `_complete_subagent_card` → `set_complete` + `sync_status_to_step` on parent step.

### 3. Scope-local footer counts (`cognition_step.py`, `cognition_step_activity.py`)

- `row_counts_for_step_tool_total()` — step footer excludes type-`t` subgraph rows.
- `_status_tool_stats_suffix()` — ignores server fallback when card is SubAgent or step has task delegations; server count only for main-only steps with no tracked rows.
- `mark_unfinished_tools_on_step_complete()` — strips type-`t` rows from **step** cards only (not SubAgent).
- `_step_card_tool_count()` uses `_build_row_index().total_tool_count`.

### 4. SubAgent index hygiene (`cognition_subagent.py`)

- `sync_status_to_step` attached on factory-created cards.
- `_build_row_index` skips `is_task_metadata_only_tool_row` rows.

## File Map

```
packages/soothe-cli/src/soothe_cli/tui/
├── textual_adapter.py              # routing helpers, SubAgent lifecycle, wire events
├── widgets/messages/
│   ├── cognition_step.py           # footer stats, strip t-rows on step complete only
│   ├── cognition_step_activity.py  # row_counts_for_step_tool_total
│   └── cognition_subagent.py       # sync_status_to_step, metadata row filter
└── runtime/state/step_router.py    # discard_pending_subgraph_tool

packages/soothe-cli/tests/unit/
├── runtime/test_step_tool_stats_ingest.py   # SubAgent wire complete, footer scope
└── ux/tui/
    ├── test_cognition_step_activity.py      # classifier excludes t-rows from total
    └── test_step_card_running_stats.py      # delegated step ignores server count
```

## Expected UX (RFC-628)

```
⎿ 🚀 Using the explore subagent, count all files in packages
  ✓ Explore(Count all files…)
  ✓ Completed (46s) · 1 task              ← step: main tools + task count only

⎿ 🎯 explore(Count all files…)
  ○ Glob(…)
  ○ ListFiles(…)
  ✓ Completed (46s) · 7 tools             ← SubAgent: subgraph tools only
```

## Verification

- [x] `./scripts/verify_finally.sh` (soothe-cli unit + lint)
- [x] `test_step_tool_stats_ingest.py` — SubAgent routing, wire completed, footer scope
- [x] `test_step_card_running_stats.py` — delegated step ignores server `tool_call_count`
- [x] `test_cognition_step_activity.py` — `total_tool_count` excludes subgraph rows on step card
- [x] Manual log replay: loops `6b34`, `ca30027` symptoms addressed

## Notes

- Executor `tool_call_count` on `step_completed` remains step-wide (main + subgraph); TUI step footer must not adopt it when task delegations exist.
- Goal-tree aggregate cards may still reconcile against server totals separately (RFC-628 out of scope).
- Remaining agent accuracy issues (e.g. wrong file counts from explore) are not TUI display bugs.
