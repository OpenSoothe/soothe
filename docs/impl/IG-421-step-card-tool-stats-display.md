# IG-421: Step Card Tool Stats Display

## Goal

Fix two issues with tool call statistics display in step cards:

1. **Subagent task tools not shown**: Inner subagent tool calls should appear under their task delegation row in the task activity tree, but they're not being displayed.

2. **Main tool stats incomplete**: Step card status line only shows "XX tools" count, not the per-tool-type breakdown (e.g., "Grep(5) · Glob(3) · Read(2)").

## Scope

- `packages/soothe-cli/src/soothe_cli/tui/widgets/messages.py` - Step card widget
- `packages/soothe-cli/src/soothe_cli/tui/step_task_routing.py` - Task routing
- `packages/soothe-sdk/src/soothe_sdk/ux/task_namespace.py` - Task scope helpers

## Root Cause Analysis

### Issue 1: Subagent task tools not displayed

The namespace → TaskScope binding logic in `task_namespace.py`:
- `task_scope_task_idx()` was a stub returning 0 (fixed in previous commit)
- `_maybe_bind_one_pending_namespace()` only binds when there's exactly one pending namespace, rejecting when multiple namespaces are pending

The binding race condition:
- Subgraph namespaces arrive before task spawns are registered
- When multiple namespaces arrive and then multiple spawns register, binding fails because the logic requires exactly one pending namespace

### Issue 2: Main tool stats incomplete

The `_stats_title_suffix()` and `_status_tool_stats_suffix()` methods aggregate tool counts but don't properly group by tool name to show breakdown.

## Implementation Plan

### Part 1: Fix namespace binding for multiple concurrent tasks

Update `_maybe_bind_one_pending_namespace` and `register_task_spawn_for_step` to handle multiple pending namespaces by matching them to spawns in order.

### Part 2: Fix tool stats display

Update `_stats_title_suffix()` to show per-tool-type breakdown like "Grep(5) · Glob(3)" instead of just "8 tools".

## Files Touching

- `packages/soothe-sdk/src/soothe_sdk/ux/task_namespace.py`
- `packages/soothe-cli/src/soothe_cli/tui/widgets/messages.py`
- `packages/soothe-sdk/tests/unit/test_task_namespace.py`
- `packages/soothe-cli/tests/unit/ux/tui/test_step_card_task_activity.py`
- `packages/soothe-cli/tests/unit/ux/tui/test_step_card_running_stats.py`

## Status

🔄 In Progress

## Progress

- [x] Fix `task_scope_task_idx()` to parse task index from TaskScope
- [ ] Fix namespace binding for multiple concurrent tasks
- [ ] Fix tool stats display to show per-tool-type breakdown
- [ ] Update tests