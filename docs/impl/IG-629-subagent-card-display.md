# IG-629: SubAgent Card — Flattened Step/Task Display

**Status**: Completed
**RFC**: [RFC-628](../specs/RFC-628-step-card-display-refactor.md) — Part II: SubAgent Card
**Design**: `docs/drafts/2026-06-26-subagent-card-flattened-display.md`

## Objective

Implement flattened step/task display:
1. Create `SubAgentMessage` widget (subclasses `CognitionStepMessage`)
2. Add routing registry in message list to route inner tools to SubAgent cards
3. Simplify `StepRowIndex` — remove `children_by_task`, `orphan_tools`, nesting logic
4. Add status sync — SubAgent completion updates step's task row icon

## Implementation checklist

- [x] Create `cognition_subagent.py` with `SubAgentMessage` class
  - [x] Factory function `create_subagent_card()` (injects fields into CognitionStepMessage)
  - [x] Override header glyph (🎯)
  - [x] Simplified lifecycle (running → success/error, no pending/queued)
  - [x] Custom `_build_row_index()` filtered by task_idx
- [x] Add `_subagent_cards_by_key` registry in TextualUIAdapter
- [x] Update routing logic in `textual_adapter.py`
  - [x] Parse unified IDs for type `t` → route to SubAgent card
  - [x] Create SubAgent card on task call (type `s:task:`)
  - [x] Async mounting guard for test compatibility
- [x] Simplify `StepRowIndex` (Phase 3-4)
  - [x] Remove `children_by_task` field
  - [x] Remove `orphan_tools` field
  - [x] Remove legacy `_child_rows_for_task`, `_orphan_subgraph_tool_rows` methods
  - [x] Remove dead functions: `task_children_stats_tone`, `task_children_aggregate_phase`, `effective_task_delegation_phase`
- [x] Simplify `StepActivityTree.render` (Phase 5)
  - [x] Remove nested child rendering (task_branch, orphan_branch_running)
  - [x] Remove task-branch status lines
  - [x] Flat tool/task row list only
- [x] Add status sync (Phase 6)
  - [x] SubAgent `sync_status_to_step()` → step's `_sync_task_row_status_from_subagent()`
- [x] Update `messages/__init__.py` — export `create_subagent_card`
- [x] Add `_sync_task_row_status_from_subagent()` to CognitionStepMessage
- [x] Update existing tests (test_step_tool_stats_ingest.py)
- [x] `./scripts/verify_finally.sh`

## File map

```
packages/soothe-cli/src/soothe_cli/tui/widgets/messages/
├── cognition_step.py              # added status sync method
├── cognition_step_activity.py     # simplified: removed dead nested-child functions
├── cognition_subagent.py          # NEW: SubAgent card factory
└── __init__.py                    # export create_subagent_card

packages/soothe-cli/src/soothe_cli/tui/
├── textual_adapter.py             # routing + SubAgent registry

packages/soothe-cli/tests/unit/runtime/
└── test_step_tool_stats_ingest.py # updated for SubAgent routing
```

## Notes

- SubAgent card uses parent step ID for row classification (`step_id` passed to CognitionStepMessage)
- Custom `_build_row_index()` filters rows by `task_idx` for SubAgent-specific activity
- Subgraph tools (type `t`) route directly to SubAgent card via `_subagent_cards_by_key` lookup
- Step card displays flat task delegation markers with phase icons synced from SubAgent completion
- Removed dead code: `orphan_branch_running`, `task_branch`, `task_children_stats_tone`,
  `task_children_aggregate_phase`, `effective_task_delegation_phase` — these were for the old
  nested-child display model that IG-629 replaces with flattened SubAgent cards.