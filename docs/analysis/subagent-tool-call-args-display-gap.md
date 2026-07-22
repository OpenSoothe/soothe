# Subagent Tool Call Args Display Gap Analysis

**Date**: 2026-06-16  
**Status**: Analysis Complete  

## Problem Statement

When subagent task delegations are displayed in the TUI, the tool call args (description, prompt, subagent_type) are not shown. The task delegation card appears as "Task" without the delegation description, making it hard for users to understand what the subagent is doing.

## Root Cause

**Location**: `packages/soothe/src/soothe/sloop/engine/tool_call_args.py:141-157`

The `filter_redundant_stream_tool_updates()` function drops ALL tool call updates when every entry has complete args. This incorrectly filters out enriched `task` tool call updates that carry delegation metadata.

### Code Flow

```
executor.py:2705-2709
    ↓ _enrich_execute_step_task_kwargs_on_message()
    ↓ fills task args with description/subagent_type
    ↓
executor.py:2714
    ↓ wire_updates_from_ai_message(enriched_msg)
    ↓ generates STREAM_TOOL_CALL_UPDATE events with complete args
    ↓
executor.py:2714 (same line)
    ↓ filter_redundant_stream_tool_updates()
    ↓ sees all updates have args → returns []
    ↓
executor.py:2726-2727
    ↓ for tool_ev in []: yields nothing
    ↓ NO wire events emitted to TUI
    ↓
TUI adapter
    ↓ never receives task delegation args
    ↓ task card shows "Task" without description
```

### The Filter Logic (Problematic)

```python
def filter_redundant_stream_tool_updates(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop stream tool updates when every entry already has complete invocation args."""
    if not updates:
        return []
    for upd in updates:
        if not isinstance(upd, dict):
            return updates
        args = upd.get("args")
        if not isinstance(args, dict) or not args:
            return updates  # Keep if ANY has incomplete args
    return []  # DROP ALL if ALL have complete args ← THE BUG
```

When `_enrich_execute_step_task_kwargs_on_message()` fills in `description` and `subagent_type`, those updates have "complete" args and are dropped.

## Why This Happens for Task Delegations

1. Act-phase streaming emits `AIMessageChunk` with `tool_calls`
2. `_enrich_execute_step_task_kwargs_on_message()` (executor.py:424-491) patches `task` tool calls:
   - Adds `description` from step metadata
   - Adds `subagent_type` from step `preferred_subagent`
3. Enriched tool calls have complete args dict
4. Filter sees complete args → drops all updates
5. TUI never receives `STREAM_TOOL_CALL_UPDATE` for task delegations

## Why Subagent Tool Calls Are Also Affected

Inner subgraph tools use `subgraph_placeholder_update()` (tool_call_args.py:280-296) which emits:
- Real args if known from invocation registry
- Placeholder `{"_subgraph_tool": true}` otherwise

When the placeholder update is the only update and it has args (even just the placeholder), the filter may still drop it depending on the mix of updates in the batch.

## Affected Code Paths

| File | Line | Function | Impact |
|------|------|----------|--------|
| `executor.py` | 2705 | `_enrich_execute_step_task_kwargs_on_message()` | Enriches task args |
| `executor.py` | 2714 | `filter_redundant_stream_tool_updates()` | Drops updates with complete args |
| `tool_call_args.py` | 141 | `filter_redundant_stream_tool_updates()` | Filter implementation (BUG) |
| `textual_adapter.py` | 934-946 | `_ingest_tool_call_update_event()` | Receives wire updates (nothing to receive) |

## Solution Options

### Option 1: Fix Filter Logic (Recommended)

**Location**: `tool_call_args.py:141-157`

Preserve `task` tool call updates even when args are complete, because those args are UI metadata (description) not execution data.

```python
def filter_redundant_stream_tool_updates(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop stream tool updates when redundant, but keep task delegations."""
    if not updates:
        return []
    
    # Always keep task tool updates - their args are UI metadata
    task_updates = [u for u in updates if isinstance(u, dict) and str(u.get("name") or "") == "task"]
    if task_updates:
        # Return task updates plus any updates with incomplete args
        incomplete = [u for u in updates if u not in task_updates and 
                      (not isinstance(u.get("args"), dict) or not u.get("args"))]
        return task_updates + incomplete
    
    # Original logic for non-task updates
    for upd in updates:
        if not isinstance(upd, dict):
            return updates
        args = upd.get("args")
        if not isinstance(args, dict) or not args:
            return updates
    return []
```

### Option 2: Skip Enrich During Streaming

**Location**: `executor.py:2705`

Only enrich task kwargs on terminal chunk or ToolMessage, not during incremental streaming. This prevents the filter from seeing "complete" args prematurely.

Risk: May cause timing issues if terminal chunk doesn't arrive.

### Option 3: Bypass Filter for Task Updates

**Location**: `executor.py:2714`

Don't apply filter to task tool call updates:

```python
tool_update_events = wire_updates_from_ai_message(enriched_msg)
# Don't filter task updates
task_updates = [e for e in tool_update_events if e.get("name") == "task"]
other_updates = filter_redundant_stream_tool_updates([e for e in tool_update_events if e.get("name") != "task"])
tool_update_events = task_updates + other_updates
```

## Recommended Fix

**Option 1** is the cleanest solution:
- Centralized fix in one function
- Clear semantics: task args are UI display data, not execution kwargs
- No changes to enrichment logic
- Maintains existing behavior for other tools

## Testing Strategy

1. Unit test: `test_tool_call_resolution_overlay.py` - add test for task updates with complete args
2. Integration test: verify task delegation card shows description in TUI
3. Regression test: ensure non-task tool updates still filtered correctly

## Additional Notes

- The `_subgraph_tool: true` placeholder in `subgraph_placeholder_update()` is meant to signal "args not yet known" but the filter treats it as "has args" → complete → drop
- This placeholder should perhaps use an empty dict `{}` instead, or the filter should check for `_subgraph_tool` key

## References

- RFC-628: Step-card display (canonical spec, 2026-06-26)
- IG-402: Step-card tool aggregation (historical)
- IG-419: Task delegation nesting
- executor.py: `_enrich_execute_step_task_kwargs_on_message()` docstring explains why enrichment happens