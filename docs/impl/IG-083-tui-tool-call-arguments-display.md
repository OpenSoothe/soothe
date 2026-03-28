# IG-083: Fix TUI Tool Call Arguments Display

**Status**: Draft
**Created**: 2026-03-28
**Scope**: TUI/CLI consistency fix

## Objective

Ensure TUI displays tool call arguments in the same format as CLI, resolving the current inconsistency where TUI shows tool calls without arguments in a tree-like format.

## Problem Analysis

### Current Behavior

**CLI Tool Call Display** (cli/renderer.py:109-143):
```
⚙ read_file(file.md) ⏳
  └ ✓ Read 12 B (2 lines) (245ms)
```

**TUI Tool Call Display** (from screenshot):
```
● ToolCall
  └ (no arguments shown)
```

**Root Cause**: Both CLI and TUI use the same `format_tool_call_args()` function, but TUI may be receiving empty or unparseable argument dicts from the event processor.

### Code Flow

1. **Event Processor** receives AIMessage with tool_calls
2. **Coerces args** to dict using `coerce_tool_call_args_to_dict()`
3. **Calls renderer** with potentially empty dict
4. **Renderer formats** using `format_tool_call_args()` → returns "" for empty args
5. **TUI displays** with empty arguments string

### Investigation Needed

Check if the issue is:
- **Args not being parsed**: Streaming chunks not accumulated properly (IG-053)
- **Args empty by design**: Some tools legitimately have no args
- **Display suppression**: TUI-specific filtering hiding args
- **Format mismatch**: TUI and CLI using different `make_tool_block()` implementations

## Implementation Plan

### Phase 1: Investigation

1. **Test tool call flow** with debug logging:
   - Add logging to `coerce_tool_call_args_to_dict()` to see raw args
   - Add logging to `TuiRenderer.on_tool_call()` to see received args
   - Check if args are present before formatting

2. **Compare TUI vs CLI**:
   - Run same query in both modes
   - Capture debug logs to compare args values
   - Identify where args are lost

### Phase 2: Fix Implementation

Based on investigation results, one of these fixes:

**Option A: Args Parsing Fix** (if args not parsed):
```python
# In event_processor.py _handle_ai_message()
# Ensure args are parsed before calling renderer
if not tc_args and raw_tcs:
    # Try to get args from raw_tcs
    for raw_tc in raw_tcs:
        if raw_tc.get("args"):
            tc_args = coerce_tool_call_args_to_dict(raw_tc.get("args"))
            break
```

**Option B: Display Enhancement** (if args empty):
```python
# In tui/renderer.py on_tool_call()
# Show context even when args empty
if not args_summary:
    # Show tool name only (no parentheses)
    args_summary = ""
else:
    args_summary = f"({args_summary})"
```

**Option C: TUI-specific args extraction**:
```python
# In tui/renderer.py on_tool_call()
# Try multiple sources for args
args_to_format = args
if not args and tool_call_id in self._state.current_tool_calls:
    # Try pending tool calls for args
    pending = self._state.current_tool_calls[tool_call_id]
    args_to_format = pending.get("args", {})
```

### Phase 3: Verification

1. **Unit tests** for argument formatting edge cases
2. **Integration tests** comparing TUI vs CLI output
3. **Manual testing** with various tool types:
   - File operations (read_file, write_file)
   - Commands (run_command with args)
   - Web tools (search_web with query)
   - Tools with no args (if any)

## Success Criteria

✅ TUI shows tool call arguments when available
✅ Format matches CLI: `⚙ ToolName(args_summary) ⏳`
✅ Handles empty args gracefully (no parentheses if no args)
✅ All existing tests pass
✅ No regressions in streaming tool call display (IG-053)

## Related Work

- **IG-053**: Tool call streaming with args accumulation
- **IG-064**: Unified display policy
- **RFC-0020**: Enhanced tool execution display with duration

## Files Changed

- `src/soothe/ux/tui/renderer.py`: Fix args display logic
- `src/soothe/ux/core/event_processor.py`: Ensure args passed correctly
- `tests/ux/tui/renderer_test.py`: Add tests for args display

## Implementation Notes

### TUI vs CLI Differences

| Aspect | CLI | TUI | Issue |
|--------|-----|-----|-------|
| Args Format | `format_tool_call_args()` | Same | Should match |
| Display Style | `make_tool_block()` stderr | Rich Text | Different medium |
| Args Source | `event_processor` | Same | Should match |
| Result Display | Child line `└ ✓ ...` | Same pattern | Should match |

### Debug Commands

```bash
# Test with verbose logging
SOOTHE_LOG_LEVEL=DEBUG soothe "read config.yml"

# Compare CLI vs TUI
# CLI mode:
soothe --no-tui "read config.yml"

# TUI mode (check output):
soothe "read config.yml"
# Press Ctrl+C to exit, check conversation log
```

## Timeline

- Investigation: 1 hour
- Fix implementation: 2 hours
- Testing: 1 hour
- Total: ~4 hours