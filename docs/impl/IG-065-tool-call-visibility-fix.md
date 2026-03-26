# IG-065: Tool Call Visibility Fix for Normal Verbosity

**Date**: 2026-03-26
**Status**: Completed
**Related**: RFC-0015 (Event Classification), RFC-0019 (Unified Event Processing)

## Overview

This implementation guide documents a bug fix where tool calls were not being displayed in CLI mode at "normal" verbosity level. The issue affected all tool calls, including research tool and browser subagent calls.

## Problem Statement

### Symptoms

When running with `--no-tui` flag at default "normal" verbosity, tool calls were not being displayed to users. For example:

```bash
uv run soothe --no-tui -p "/research meaning of balabalaxmx"
```

Would show only plan events but not the research tool call itself.

### Root Cause

The `CliRenderer.on_tool_call()` and `CliRenderer.on_tool_result()` methods were checking for the `"tool_activity"` category:

```python
if not should_show("tool_activity", self._verbosity):
    return
```

However, at "normal" verbosity level (the default), only these categories are visible:
- `"assistant_text"`
- `"protocol"`
- `"subagent_progress"`
- `"error"`

The `"tool_activity"` category is only shown at `"detailed"` and `"debug"` verbosity levels.

## Solution

Changed the category check from `"tool_activity"` to `"protocol"` for tool calls and results in `src/soothe/ux/cli/renderer.py`:

### Changes to `on_tool_call()`

**Before**:
```python
if not should_show("tool_activity", self._verbosity):
    return
```

**After**:
```python
if not should_show("protocol", self._verbosity):
    return
```

### Changes to `on_tool_result()`

**Before**:
```python
if not should_show("tool_activity", self._verbosity):
    return
```

**After**:
```python
if not should_show("protocol", self._verbosity):
    return
```

## Rationale

Tool calls are fundamental protocol events that users need to see at all verbosity levels (except "minimal"). They are part of the agent's execution flow and should be visible by default.

The `"tool_activity"` category is meant for more detailed tool information that would be shown at higher verbosity levels, but basic tool call/result visibility is essential at "normal" verbosity.

## Testing

### Verification Steps

1. Run research tool with normal verbosity:
   ```bash
   uv run soothe --no-tui -p "/research meaning of example"
   ```

   Expected: Tool calls should be visible with `⚙` icon

2. Run with minimal verbosity:
   ```bash
   uv run soothe --no-tui --verbosity minimal -p "/research meaning of example"
   ```

   Expected: Tool calls should NOT be visible (only assistant text and errors)

3. Run with detailed verbosity:
   ```bash
   uv run soothe --no-tui --verbosity detailed -p "/research meaning of example"
   ```

   Expected: Tool calls should be visible with more details

### Unit Tests

All existing unit tests pass with this change:
- `test_progress_rendering.py`: 8 tests
- `test_event_processor.py`: 13 tests
- Total: 929 tests passing

## Impact

### Positive
- Tool calls are now visible at default verbosity level
- Users can see what the agent is doing
- Better user experience for CLI mode

### Neutral
- No breaking changes
- Behavior at other verbosity levels remains the same

## Files Modified

1. `src/soothe/ux/cli/renderer.py`: Changed `on_tool_call()` and `on_tool_result()` category checks

## References

- RFC-0015: Event Classification and Verbosity
- RFC-0019: Unified Event Processing Architecture
- IG-064: Unified Display Policy and Internal Event Filtering
- `src/soothe/ux/core/progress_verbosity.py`: Verbosity level definitions