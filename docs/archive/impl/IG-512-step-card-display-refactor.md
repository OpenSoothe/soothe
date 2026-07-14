# IG-512: Step Card Display Refactor

**Status**: Implemented (2026-06-26)  
**RFC**: [RFC-628](../specs/RFC-628-step-card-display-refactor.md) — **canonical step card design spec**  
**Design**: `docs/archive/drafts/2026-06-26-cognition-step-activity-panel-design.md` (historical; RFC-628 supersedes for normative reference)

## Objective

Refactor `CognitionStepMessage` per RFC-628: extract `cognition_step_activity.py`, fix missing `· N tools` on running lines, remove auto-collapse, unify surface sync.

## Implementation checklist

- [x] Add `cognition_step_activity.py` with `StepToolRow`, `StepRowIndex`, `StepRowClassifier`
- [x] Add `StepActivityTree.render` (migrate `_step_task_activity_content`)
- [x] Add `StepCardStatusLine.build` (footer + branch status lines)
- [x] Add shared row renderer via `append_tool_activity_lines`
- [x] Add `finalize_tool_rows_on_step_end`
- [x] Add `branched_prose_body` helper (detail zone)
- [x] Refactor `cognition_step.py`: `_sync_step_card_surface`, deferred flush, cache `_activity_widget`
- [x] Remove auto-collapse + dead code (`collapse-hint`, unused helpers)
- [x] Update `preview_limits.py` comment
- [x] Add `test_cognition_step_activity.py`
- [x] Update `test_step_card_running_stats.py`, `test_step_card_task_activity.py`
- [x] `./scripts/verify_finally.sh`

## File map

```
packages/soothe-cli/src/soothe_cli/tui/widgets/messages/
├── cognition_step.py              # slim widget (~800 lines target)
├── cognition_step_activity.py     # NEW pure render + index
└── _helpers.py                    # unchanged throttling

packages/soothe-cli/tests/unit/ux/tui/
├── test_cognition_step_activity.py  # NEW
├── test_step_card_running_stats.py
└── test_step_card_task_activity.py
```

## Order of work

1. Scaffold module + classifier tests (no widget changes)
2. Move renderers; keep `CognitionStepMessage` delegating to new module
3. Wire `_sync_step_card_surface`; delete old refresh chains
4. Remove auto-collapse; fix tests
5. Verify

## Notes

- Do not change `StepTaskRouter` or `textual_adapter` routing in this IG unless required for tests.
- Preserve `snapshot_tool_rows` / `apply_tool_rows_snapshot` public API.
- Manual `toggle_collapse` stays; only auto-collapse is removed.
