# IG-168: Remove Dead Code from soothe.ux Module

**Status**: In Progress
**Created**: 2026-04-14
**Scope**: Code cleanup - remove unused code from `src/soothe/ux/`

## Objective

Remove all dead code from the `soothe.ux` module to improve maintainability and reduce confusion.

## Dead Code Identified

### 1. Dead Files (deleted)

| File | Reason |
|------|--------|
| `src/soothe/ux/shared/event_formatter.py` | Only consumed by test file, no production use |
| `src/soothe/ux/tui/widgets/protocol_event.py` | Never imported anywhere |
| `tests/unit/test_event_formatter.py` | Tests deleted module |

### 2. Dead Functions/Classes (removed)

| File | Item | Type | Notes |
|------|------|------|-------|
| `ux/shared/rendering.py` | `_update_name_map_from_ai_message()` | Function | Never called |
| `ux/shared/rendering.py` | `_resolve_namespace_label()` | Function | Never called |
| `ux/shared/rendering.py` | `resolve_namespace_label()` | Function | Never called externally |
| `ux/shared/message_processing.py` | `is_multi_step_plan()` | Function | Never used |

### 3. Dead Constants (removed)

| File | Item | Notes |
|------|------|-------|
| `ux/tui/_ask_user_types.py` | `OTHER_CHOICE_LABEL` | Duplicated in `ask_user.py` |
| `ux/tui/_ask_user_types.py` | `OTHER_VALUE` | Never used |

### 4. Dead Re-exports (removed from `__init__.py`)

- `is_multi_step_plan`, `resolve_namespace_label` (dead functions)
- `extract_text_from_ai_message`, `render_plan_tree` (redundant - consumers use original modules)
- `VerbosityTier`, `should_show`, `classify_event_to_tier` (redundant - consumers use `soothe.foundation`)

### 5. Kept (per user request)

- `ux/tui/widgets/autopilot_dashboard.py` - `AutopilotApp`, `_parse_autopilot_files()` retained for future autopilot TUI integration

## Success Criteria

- [x] Dead files deleted
- [x] Dead functions/classes removed
- [x] Dead re-exports cleaned up
- [ ] All tests pass (`./scripts/verify_finally.sh`)
- [ ] No import errors
