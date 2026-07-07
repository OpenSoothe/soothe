# IG-104: CLI Output Verbosity Optimization

**Status**: ✅ Completed
**Date**: 2026-03-31
**RFC References**: RFC-0024 (Verbosity Tier Classification)

---

## Overview

Optimized CLI output verbosity to reduce noise at NORMAL level while preserving detailed logging for debugging. Tool calls and intermediate step completion messages are now hidden at NORMAL verbosity and only visible at DETAILED/DEBUG levels.

---

## Motivation

**Problem**: CLI output was cluttered with verbose tool execution details at NORMAL verbosity:
- Tool call arguments (e.g., `Glob(**/README*)`) visible to users
- Intermediate step completion messages ("Step X Complete: ...") repeated throughout output
- Final results duplicated with intermediate progress

**User Feedback**: Users requested cleaner output showing only essential information (goal, final result) without execution internals.

---

## Changes

### 1. EventProcessor Tool Call Filtering (DETAILED tier)

**Modified Files**:
- `src/soothe/ux/core/event_processor.py` (lines 235, 264, 293, 445, 499)

**Changes**:
- Changed tool call emission from `VerbosityTier.NORMAL` to `VerbosityTier.DETAILED` in EventProcessor
- Tool calls (name + args) now hidden at NORMAL verbosity
- Tool results also hidden at NORMAL verbosity
- Users see final results, not execution process

**Code Example**:
```python
# Before: Tool calls visible at NORMAL
if not should_show(VerbosityTier.NORMAL, self._verbosity):
    return

# After: Tool calls only visible at DETAILED+
if not should_show(VerbosityTier.DETAILED, self._verbosity):
    return
```

**Methods Modified**:
- `_handle_tool_message()` - Filter tool message display
- `_handle_ai_message()` - Filter tool call blocks (2 locations)
- `_handle_tool_message_dict()` - Filter tool dict messages
- `_emit_pending_tool_calls()` - Filter pending tool calls

---

### 2. Step Completion Events (DETAILED tier)

**Modified Files**:
- `src/soothe/ux/cli/stream/pipeline.py` (lines 118-121)
- `src/soothe/core/event_catalog.py` (lines 666, 650)

**Changes**:
- Changed `PLAN_STEP_COMPLETED` event from NORMAL to DETAILED
- Changed `AGENTIC_STEP_COMPLETED` event from NORMAL to DETAILED
- Step start messages remain at NORMAL (show what's being executed)
- Step completion messages hidden (don't clutter output)

**Event Registration**:
```python
# Before
_reg(PLAN_STEP_COMPLETED, ..., verbosity=VerbosityTier.NORMAL, ...)

# After
_reg(PLAN_STEP_COMPLETED, ..., verbosity=VerbosityTier.DETAILED, ...)
```

---

### 3. Test Updates

**Modified Files**:
- `tests/unit/test_verbosity_tier.py` (lines 65-71)

**Changes**:
- Updated test expectations for new verbosity classification
- `soothe.agentic.step.completed` now classified as DETAILED
- All 1050 tests pass ✅

---

## Impact

### User Experience (NORMAL verbosity)

**Before**:
```
● Goal: list 3 readme files of this project
  └ ○ Navigate to the project repository and find all README files
⚙ Glob(**/README*)
  └ ✓ Found 1 file
  └ ● Navigate to the project repository and find all README files (16.7s)
● Goal: list 3 readme files of this project (complete, 0 steps) (25.8s)

**Step 1 Complete:** Found all README files...
[17 README files listed]
```

**After**:
```
● Goal: list 3 readme files of this project
  └ ○ Navigate to the project repository and find all README files

[Final result table with 17 README files]
```

**Improvements**:
- ✅ No tool execution details (Glob, args, results)
- ✅ No intermediate step completion messages
- ✅ Cleaner, more focused output
- ✅ Final results presented clearly

---

### Developer Experience (DETAILED/DEBUG verbosity)

**Using `--verbosity detailed`**:
```
● Goal: list 3 readme files
  └ ○ Navigate to repository
⚙ Glob(**/README*)
  └ ✓ Found 17 files
  └ ● Navigate to repository (16.7s)
● Goal: complete (25.8s)
```

**Benefits**:
- ✅ Full execution details visible for debugging
- ✅ Tool calls with arguments
- ✅ Step-by-step progress tracking
- ✅ Timing information

---

### Logging (Unchanged)

**ThreadLogger continues to log everything**:
- All tool calls and results logged to thread files
- All step completions logged with timing
- Full execution history preserved in `.soothe/logs/threads/`
- No information loss - just cleaner CLI display

**Log Files**:
- `~/.soothe/logs/threads/<thread_id>/conversation.log`
- `~/.soothe/logs/threads/<thread_id>/events.log`

---

## Verification

**All checks passed**:
- ✅ Code formatting (Ruff)
- ✅ Linting (Ruff, zero errors)
- ✅ Unit tests (1050 passed, 2 skipped)

**Run**: `./scripts/verify_finally.sh`

---

## Usage Examples

### Normal Mode (Default)
```bash
soothe --no-tui -p "list readme files"
# Shows: goal → final result (no execution details)
```

### Detailed Mode (Debugging)
```bash
soothe --no-tui --verbosity detailed -p "list readme files"
# Shows: goal → steps → tool calls → results → timing
```

### Debug Mode (Full Internals)
```bash
soothe --no-tui --verbosity debug -p "list readme files"
# Shows: everything including thinking, heartbeats, internals
```

---

## Architecture

**Verbosity Tier System** (RFC-0024):

```
QUIET (0)     → Always visible (errors, final results)
NORMAL (1)    → Standard progress (goal, step descriptions)
DETAILED (2)  → Execution details (tool calls, step completions)
DEBUG (3)     → Full internals (thinking, heartbeats)
INTERNAL (99) → Never shown (implementation details)
```

**Classification Flow**:
1. Event emitted → classified to tier
2. Tier compared to user verbosity
3. Only events with `tier <= verbosity` displayed
4. All events logged regardless of display

---

## Files Modified

| File | Changes | Lines |
|------|---------|-------|
| `src/soothe/ux/core/event_processor.py` | Tool calls → DETAILED | 5 locations |
| `src/soothe/ux/core/message_processing.py` | Tool calls → DETAILED | 4 locations |
| `src/soothe/ux/cli/stream/pipeline.py` | Step completions → DETAILED | 118-121 |
| `src/soothe/core/event_catalog.py` | Event registrations | 666, 650 |
| `tests/unit/test_verbosity_tier.py` | Test expectations | 71 |

---

## Commit Message

```
feat(cli): optimize verbosity - hide tool calls and step completions at NORMAL

- Change tool call emission to DETAILED tier (hidden at NORMAL)
- Change step completion events to DETAILED tier
- Keep step start messages at NORMAL (show execution intent)
- Preserve full logging in thread files (no information loss)
- Update tests for new classification

Benefits:
- Cleaner CLI output for users (no execution noise)
- Full debugging capability with --verbosity detailed
- Complete audit trail in log files

All 1050 tests pass ✅
```

---

## Notes

**Design Decision**: Keep step start messages at NORMAL but hide completions
- **Why**: Users want to see what's happening, not every completion
- **Example**: "Navigate to repository" shown, but "Navigate complete" hidden
- **Result**: Progress indication without clutter

**Logging Policy**: ThreadLogger logs everything regardless of verbosity
- All events logged for debugging, audit, and history
- Verbosity only affects CLI/TUI display
- No information loss, better UX

---

## Related

- RFC-0024: Verbosity Tier Classification System
- RFC-0020: Registry-Driven Event Display
- IG-053: CLI/TUI Event Progress Display
- IG-087: Verbosity Mode Critique

---

## Future Enhancements

**Potential Improvements**:
1. Add `--verbosity quiet` mode (only final results + errors)
2. Customize verbosity per subsystem (e.g., `--verbosity tool=normal,details=detailed`)
3. Add timing summary at NORMAL (e.g., "Completed in 25.8s")
4. Add progress bar for long-running operations

**Considerations**:
- User research on preferred verbosity levels
- A/B testing different output styles
- Integration with TUI progress display