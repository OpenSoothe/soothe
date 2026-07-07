# IG-421: Step Card Tool Stats Display

## Goal

Fix two issues with tool call statistics display in step cards:

1. **Subagent task tools not shown**: Inner subagent tool calls should appear under their task delegation row in the task activity tree, but they're not being displayed.

2. **Main tool stats incomplete**: Step card status line only shows "XX tools" count, not the per-tool-type breakdown (e.g., "Grep(5) · Glob(3) · Read(2)").

## Scope

- `packages/soothe-cli/src/soothe_cli/tui/widgets/messages.py` - Step card widget
- `packages/soothe-cli/src/soothe_cli/tui/step_task_routing.py` - Task routing
- `packages/soothe-sdk/src/soothe_sdk/ux/task_namespace.py` - Task scope helpers
- `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` - Event handling

## Root Cause Analysis

### Issue 1: Subagent task tools displayed under wrong step card (CRITICAL BUG)

**Discovery from logs:**
```
ns=('tools:af5d40c0-...') bound to MFE_01:s:task:0 (step MFE-01)
But display='MFE_02:t0:task:0' (step MFE-02 embedded!)
```

The daemon sends task-level unified IDs that already contain a step_id in the format `{step_wire}:t{idx}:{tool}:{n}`. However, the step_id embedded in the daemon's tool_call_id doesn't match the namespace's bound task_scope.

**Root cause in `row_key_for_subgraph_tool` (line 239-250):**
```python
def row_key_for_subgraph_tool(...):
    _, type_code, _, _ = parse_unified_tool_call_id(tid)
    if type_code == "t":
        return tid  # BUG: Returns unchanged even when step_id mismatches binding!
```

The function returns task-level IDs unchanged without re-mapping the step_id/task_idx to the namespace's bound task_scope. This causes tools from one subagent namespace to appear under a different step card.

### Fix

Re-map task-level IDs to use the bound task_scope's step_id and task_idx:

```python
def row_key_for_subgraph_tool(...):
    parsed_sid, type_code, parsed_idx, tool_info = parse_unified_tool_call_id(tid)
    if type_code == "t" and task_scope is not None:
        bound_step_id = task_scope_step_id(task_scope)
        bound_task_idx = task_scope_task_idx(task_scope, bound_step_id)
        if bound_step_id and (parsed_sid != bound_step_id or parsed_idx != bound_task_idx):
            return _format_unified_tool_call_id(bound_step_id, f"t{bound_task_idx}", tool_info)
    if type_code == "t":
        return tid
    return scoped_subgraph_tool_key(namespace, tid, task_scope=task_scope)
```

### Issue 2: Tool stats display

The `_stats_title_suffix()` code was already correct - it properly groups by tool display name.

## Files Touching

- `packages/soothe-sdk/src/soothe_sdk/ux/task_namespace.py` - Fixed `row_key_for_subgraph_tool`
- `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` - Added step completion logging
- `packages/soothe-cli/src/soothe_cli/tui/step_task_routing.py` - Added routing debug logging
- `packages/soothe-sdk/tests/unit/test_task_namespace.py` - Added remapping tests
- `scripts/verify_finally.sh` - Improved uv sync handling

## Status

✅ Completed

## Progress

- [x] Fix `task_scope_task_idx()` to parse task index from TaskScope
- [x] Fix namespace binding for multiple concurrent tasks (FIFO matching)
- [x] **Fix `row_key_for_subgraph_tool` to remap mismatched step_id/task_idx**
- [x] Add detailed step completion logging for debugging
- [x] Add routing debug logging in step_task_routing.py
- [x] Update tests with remapping test cases
- [x] Fix unrelated test failure
- [x] Improve verify_finally.sh uv sync handling

## Changes Summary

1. **task_namespace.py:239-260**: Fixed `row_key_for_subgraph_tool` to remap task-level IDs when step_id/task_idx don't match the bound task_scope. This ensures tools appear under the correct parent step card.

2. **textual_adapter.py:426-478**: Added `_log_step_completion_stats` helper for debugging.

3. **step_task_routing.py**: Added debug/info logging for namespace binding, task spawn registration, and subgraph tool routing.

4. **test_task_namespace.py**: Added `test_row_key_for_subgraph_tool_remaps_wrong_step_id` and `test_row_key_for_subgraph_tool_remaps_wrong_task_idx`.

5. **scripts/verify_finally.sh**: Made `uv sync` a hard requirement that must succeed before verification continues.

## Testing

Run a new query with parallel subagents to verify the fix. Check logs:
```bash
grep "\[Router\]" ~/.soothe/logs/cli.log
grep "\[Step\]" ~/.soothe/logs/cli.log
```

Tools should now appear under their correct parent step card based on namespace binding, not the daemon's embedded step_id.