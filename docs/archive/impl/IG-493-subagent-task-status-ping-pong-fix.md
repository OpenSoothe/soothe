# IG-493: Fix Subagent Task Status Ping-Pong in TUI

## Problem

When running the explore subagent, the TUI visually oscillates between "Running..." and "Done" states as tools complete in waves and new ones start.

## Root Cause

In `messages.py`, `_task_children_aggregate_phase` aggregates child tool row phases:
- Returns "running" if any child row is running
- Returns "success" if all children are success

During explore execution:
1. New tool starts → row added with `phase="running"` → aggregate returns "running" → TUI shows "Running..."
2. All current tools complete → all rows become "success" → aggregate returns "success" → TUI shows "Done"
3. Next tool wave starts → new rows with `phase="running"` → aggregate flips back to "running" → TUI shows "Running..."
4. This cycle repeats, creating visual ping-pong

The `_effective_task_delegation_phase` override only applied when step card was already finalized (`_status == "success"`). During execution, `_status == "running"`, so the aggregate directly drove the display.

## Solution

Modified `_effective_task_delegation_phase` to prevent the transient "success" → "Done" flash when child rows are present but all completed:

```python
# While step is executing with child rows, prevent transient "Done" (success)
# flashes between tool waves. Only override "success" → "running" (IG-492).
if self._status == "running" and child_rows and phase == "success":
    return "running"
```

This keeps the task delegation showing "Running..." while:
- Step card is still executing (`_status == "running"`)
- Child tool rows exist (active subgraph execution)
- All current children have completed (`phase == "success`)

When a new tool wave starts, the aggregate flips to "running" naturally. When the step completes (`_status == "success"`), the existing override shows "Done".

The fix does NOT affect:
- Task delegations without child rows (uses task_row.phase directly)
- Error states (errors still show "Failed")
- Completed steps (existing "success" override handles final state)

## Files Changed

- `packages/soothe-cli/src/soothe_cli/tui/widgets/messages.py`: Modified `_effective_task_delegation_phase`

## Testing

- All 23 tests in `test_step_card_task_activity.py` pass
- Visual testing with explore subagent shows stable "Running..." display throughout execution