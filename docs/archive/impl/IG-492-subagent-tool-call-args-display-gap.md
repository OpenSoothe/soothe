# IG-492: Analysis — Subagent Tool Call Args Display Gap

**Date**: 2026-06-16
**Status**: Investigation Complete
**Impact**: Medium - TUI does not display tool call args for subagent executions

---

## Executive Summary

The TUI does not display arguments for tool calls made by subagents (explore, deep_research, etc.). The root cause is a bug in `filter_redundant_stream_tool_updates()` that incorrectly filters ALL tool updates when they have complete args, not just redundant ones. This breaks the display contract for task delegations and subgraph tool activity.

---

## Problem Statement

When a subagent (explore, deep_research) executes and makes tool calls:

- ✅ The subagent's `task` delegation card shows `Explore(description)` or similar
- ❌ **Missing**: Individual tool calls like `grep(pattern=...)`, `ls(path=...)` are not shown
- ❌ **Missing**: Tool call arguments are never displayed

Expected behavior:
- Task delegation should show `Explore(description text)`
- Nested tool calls should show `grep(pattern=*.py)`, `ls(path=/src)`, etc.
- Arguments should be visible in the tool activity display

---

## Root Cause Analysis

### Location: `packages/soothe/src/soothe/loop/engine/tool_call_args.py:141-157`

```python
def filter_redundant_stream_tool_updates(
    updates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop stream tool updates when every entry already has complete invocation args.
    
    Daemon ``tool_call_updates_batch`` carries the same kwargs; keep partial-arg updates
    for providers that stream tool JSON incrementally.
    """
    if not updates:
        return []
    for upd in updates:
        if not isinstance(upd, dict):
            return updates
        args = upd.get("args")
        if not isinstance(args, dict) or not args:
            return updates  # BUG: returns original on incomplete args
    return []  # BUG: returns [] when ALL have complete args
```

### The Bug

The logic is inverted:
- When any update has incomplete args → returns `updates` (keeps them)
- When ALL updates have complete args → returns `[]` (drops them)

This is backwards. Updates with complete args (which contain the actual tool call arguments we want to display) are being dropped, while updates with incomplete args (which may have no args at all) are being kept.

### Code Flow Path

```
executor.py (Act stream)
  ↓
_enrich_execute_step_task_kwargs_on_message()
  ↓ enriches task kwargs with description/subagent_type
wire_updates_from_ai_message()
  ↓ generates tool_call_update events with enriched args
filter_redundant_stream_tool_updates()
  ↓ BUG: filters out ALL updates because they have complete args
  ↓ returns [] 
  ↓
wire_updates dropped
  ↓
TUI never receives tool updates
  ↓
add_tool_call() not called with args
  ↓
Task delegation shown without tool call arguments
```

### Specific Call Sites

1. **executor.py:2714** - Act stream emits tool updates after enrichment:
   ```python
   tool_update_events = filter_redundant_stream_tool_updates(
       wire_updates_from_ai_message(enriched_msg)
   )
   ```

2. **executor.py:2914** - Subgraph placeholder updates (for non-task tools):
   ```python
   tool_ev = tool_args.subgraph_placeholder_update(tcid, tname)
   ```

---

## Impact on Display Components

### TUI Components Affected

1. **CognitionStepMessage._task_delegation_label()** (messages.py:1770-1788)
   - Builds display label `SubAgentName(description)`
   - Args come from task row args: `args.get("description")` or `args.get("prompt")`
   - Without updates, args may only contain placeholder `{"_subgraph_tool": true}`

2. **format_step_tool_activity_command()** (tool_display.py:92-99)
   - Formats tool calls as `DisplayName(arg_preview)`
   - Uses `args_preview()` to show key arguments
   - Without args updates, shows just `DisplayName` with no args

3. **_append_tool_activity_lines()** (messages.py:1639-1665)
   - Renders nested tool calls under task delegations
   - Uses `format_step_tool_activity_command(row.tool_name, row.args or {})`
   - Without args, displays `grep` instead of `grep(pattern=*.py)`

---

## Why Complete Args Updates Should NOT Be Filtered

### The Comment Misunderstanding

The docstring says:
> "Daemon `tool_call_updates_batch` carries the same kwargs; keep partial-arg updates for providers that stream tool JSON incrementally."

This implies:
- TUI already has args from another source → filter to avoid duplication
- Partial args from streaming → keep for progressive display

### Reality Check

1. **No prior batch source**: The TUI receives updates via `tool_call_updates_batch` wire events, but these ARE the updates being filtered. There's no prior args source.

2. **Complete args ARE valuable**: When `wire_updates_from_ai_message()` generates updates with complete args (enriched from `_enrich_execute_step_task_kwargs_on_message()`), those contain the display-ready `description` and `subagent_type` for task delegations.

3. **Filter logic is inverted**: The function drops exactly what we need to keep.

---

## Proposed Fix

### Option 1: Remove the Filter (Simplest)

```python
def filter_redundant_stream_tool_updates(
    updates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep all tool updates - TUI needs them for display.
    
    Historical note: Previous implementation incorrectly filtered complete updates.
    The TUI relies on these updates to display tool call arguments.
    """
    return updates or []
```

**Pros**: Simple, fixes display immediately
**Cons**: May add redundant updates (investigate if this causes TUI issues)

### Option 2: Fix the Logic Inversion

```python
def filter_redundant_stream_tool_updates(
    updates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter updates that are truly redundant (empty or no args).
    
    Keep updates with meaningful args - TUI needs them for display.
    """
    if not updates:
        return []
    # Keep updates with meaningful args
    return [
        upd for upd in updates
        if isinstance(upd, dict) and isinstance(upd.get("args"), dict) and upd.get("args")
    ]
```

**Pros**: Filters truly empty updates, keeps valuable ones
**Cons**: May not address the actual intent of the original filter

### Option 3: Understand the Original Intent (Recommended)

Investigate whether there's a duplicate source of args that this filter was meant to suppress. The comment mentions "daemon tool_call_updates_batch carries the same kwargs". Check:

1. Are there TWO paths sending tool updates?
2. Is one path earlier/faster than this stream path?
3. Should this filter only suppress updates that were already sent via batch?

If there IS a duplicate source, fix should target actual duplicates, not ALL complete updates.

---

## Related Code Locations

| Location | Purpose | Status |
|----------|---------|--------|
| `executor.py:2705` | Enrich task kwargs | ✅ Works correctly |
| `executor.py:2714` | Generate wire updates | ✅ Works correctly |
| `tool_call_args.py:141` | Filter updates | ❌ **BUG HERE** |
| `executor.py:2726` | Emit updates to wire | ❌ Filtered to [] |
| `textual_adapter.py:846` | TUI receives updates | ✅ Handler exists |
| `textual_adapter.py:934-945` | Task delegation handling | ⚠️ No args received |
| `messages.py:1770` | Display label formatting | ⚠️ Missing args |

---

## Testing Recommendations

1. **Unit test**: `test_executor_delegate_finals.py` - Add test verifying enriched task updates reach wire
2. **Integration test**: Verify TUI displays tool call args for subagent task delegations
3. **Regression test**: Ensure fix doesn't break existing tool update flows

---

## Next Steps

1. Confirm the fix approach (remove filter vs. fix logic)
2. Update `filter_redundant_stream_tool_updates()` implementation
3. Add unit tests for the corrected behavior
4. Run `./scripts/verify_finally.sh` to validate
5. Verify TUI displays tool call args for subagent task delegations

---

## References

- IG-416: Unified tool call ID format
- IG-419: Nested task delegation rows
- IG-402: Step-card tool aggregation
- RFC-201: StrangeLoop execute phase