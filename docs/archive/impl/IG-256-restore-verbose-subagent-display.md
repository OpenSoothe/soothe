# IG-256: Restore Verbose Subagent CLI Display Format

## Status

**In Progress** - Started 2026-04-25

## Overview

Restore the verbose 7-line subagent display format that existed before IG-255, without reverting the commit. Create new changes that restore old behavior while keeping IG-255 in git history.

## Motivation

**User Request**: Restore previous verbose format with duplicate markers and full output cascade.

**Why**: User prefers seeing all subagent execution details including:
- Multiple success markers (✓ ✅ ✓)
- Redundant tool execution events (Task results)
- Full result details spread across multiple lines
- No consolidation or deduplication

## Changes Summary

### Files Modified

1. **`packages/soothe-cli/src/soothe_cli/cli/stream/pipeline.py`**
   - Remove deduplication filter (lines 103-110)
   - Allow redundant tool/task result events to display

2. **`packages/soothe-cli/src/soothe_cli/cli/stream/formatter.py`**
   - Restore `format_subagent_done()` to ignore result_preview
   - Use triple markers "✓ ✅ ✓ {summary}"
   - Restore `format_tool_call()` to remove subagent differentiation
   - Use wrench emoji `🔧` for all tools (no 🤖)
   - Restore `format_subagent_milestone()` to use detective emoji `🕵🏻‍♂️`

3. **`packages/soothe-cli/src/soothe_cli/cli/stream/context.py`**
   - Keep state fields for backward compatibility (no changes needed)

## Implementation Details

### 1. Remove Deduplication Filter

**Location**: `pipeline.py:103-110`

Remove the IG-255 filter that suppresses redundant events:

```python
# REMOVE THIS CODE:
if self._context.subagent_completion_shown:
    if event_type in ("tool.execution.completed", "tool.execution.result"):
        tool_name = event.get("name", event.get("tool_name", ""))
        if "Task(" in tool_name or "_subagent" in tool_name.lower():
            return []
```

**Effect**: All events processed without filtering, creating verbose cascade.

### 2. Restore Verbose Completion Format

**Location**: `formatter.py:format_subagent_done()`

Change consolidated format to verbose triple markers:

**Current**: `content = f"✓ {summary} ✓ {preview_text}"`

**Restore**: `content = f"✓ ✅ ✓ {summary}"`

Ignore `result_preview` parameter - results show via separate tool events.

### 3. Restore Tool Icons

**Location**: `formatter.py:format_tool_call()`

Remove subagent differentiation:

**Current**:
```python
is_subagent = "_subagent" in name.lower()
if is_subagent:
    icon_emoji = "🤖"
    icon_char = "●"
else:
    icon_emoji = "🔧"
    icon_char = "⚙"
```

**Restore**:
```python
icon_emoji = "🔧"
icon_char = "⚙"
```

All tools use same wrench/gear icons.

### 4. Restore Milestone Emoji

**Location**: `formatter.py:format_subagent_milestone()`

**Current**: `content = f"🔄 {brief}"`

**Restore**: `content = f"🕵🏻‍♂️ {brief}"`

## Expected Output

### Before (IG-255 Consolidated)

```
● 🤖 BrowserSubagent("Search for current time") [running]
  ✓ success (0ms) ✓ Current Time: 12:24:49 AM
```

### After (Verbose Restored)

```
● I'll search for the current time for you.
● 🔧 BrowserSubagent("Search for...") [running]
  ✓ ✅ ✓ success (0ms)
⚙ Task(browser, Search for...)
✓ Current Time: 12:24:49 AM... (Current Time: ...)
**Current Time:**  12:24:49 AM
```

## Testing

### Manual Test

```bash
soothe "search for current time"
```

Verify verbose output with 7+ lines showing duplicate markers.

### Automated Tests

```bash
./scripts/verify_finally.sh
```

- All unit tests must pass (900+ tests)
- Linting must pass (zero errors)
- Update tests in `test_cli_stream_display_pipeline.py` for verbose format

## Progress

- [x] Create implementation guide
- [x] Remove deduplication filter in pipeline.py
- [x] Suppress explicit subagent event processing in pipeline.py
- [x] Restore verbose completion format in formatter.py
- [x] Restore tool icons in formatter.py
- [x] Restore milestone emoji in formatter.py
- [x] Run verification script - PASSED (1279 tests)
- [x] Final verification - PASSED

## Notes

- IG-255 commit remains in history (no revert)
- State tracking fields kept for backward compatibility
- Tests may need updates for verbose format expectations