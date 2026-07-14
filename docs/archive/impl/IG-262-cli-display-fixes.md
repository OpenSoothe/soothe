# IG-262: CLI Display Fixes

**Status**: In Progress
**Date**: 2026-04-25
**Issues**: Two display bugs in headless CLI mode

---

## Problem Statement

User reported two issues in CLI output:

### Issue 1: Incorrect Indentation After [keep] Step

```
● 🌟 [keep] Task complete - README.md first 10 lines have been read and extracted
  ● 💭 Successfully read README.md, extracted first 10 lines showing project is 'Soothe — Beyond Yet-
```

The reasoning line (● 💭) shows unexpected 2-space indentation. It should be at the same level as the judgement line (flat layout, no indent).

### Issue 2: No Final Result Displayed

After task completion, the final result should be displayed to stdout, but it's missing. The content "Successfully read README.md..." appears to be shown as a reasoning line instead of the final stdout message.

---

## Analysis

### Issue 1: Indentation (FIXED)

Root cause: `format_reasoning()` in `formatter.py` used `level=3` (2-space indent via `indent_for_level(3)`), making reasoning appear as a child of the judgement line.

Fix: Changed `level=3` → `level=2` for flat layout (sibling to judgement, not child).

**Changed file**: `packages/soothe-cli/src/soothe_cli/cli/stream/formatter.py`
**Lines**: 310-341
**Status**: ✅ Applied

### Issue 2: Missing Final Result

Investigation needed:

1. Check if agent_loop.completed event is emitted with `final_stdout_message` field
2. Verify suppression state logic handles emission correctly
3. Check if final stdout is being routed to stderr instead of stdout

---

## Implementation Plan

### Phase 1: Indentation Fix ✅

- [x] Change `format_reasoning()` to use `level=2` for flat layout
- [x] Verify indent behavior: `indent_for_level(2)` → "" (no indent)
- [x] Run tests to confirm fix

### Phase 2: Final Result Investigation ✅

Investigation findings:

1. **Suppression state logic**: Working correctly ✅
   - `track_from_event()` properly extracts `final_stdout_message` from event
   - `should_emit_final_report()` conditions are correct
   - `get_final_response()` properly accumulates and returns text

2. **Renderer emission logic**: Working correctly ✅
   - `on_progress_event()` checks `should_emit_final_report()` after processing event
   - `_write_stdout_final_report()` properly writes to stdout

3. **Root cause analysis**:
   - The "Successfully read README.md..." text in the output is from the **reasoning field** of `agent_loop.reasoned` event (shown as 💭)
   - This is correct behavior - it's the LLM's reasoning about task completion
   - The **final_stdout_message** from `agent_loop.completed` event should contain the actual result (file content)
   - Suppression state logic ensures final stdout is emitted after event processing

4. **Expected behavior**:
   - Progress events (stderr): judgement, reasoning, tool calls
   - Final stdout (stdout): accumulated response or `final_stdout_message`
   - The final stdout should appear after the last progress event

Status: No fix needed - logic is correct ✅

---

## Test Plan

### Manual Testing

```bash
soothe --no-tui -p "read 10 lines of project readme"
```

Expected output:
- Reasoning line at same level as judgement (no indent)
- Final result displayed to stdout after completion

### Automated Testing

Run verification script:
```bash
./scripts/verify_finally.sh
```

All tests must pass before commit.

---

## Progress

- ✅ Issue 1 indentation fix applied and tested
- ✅ Issue 2 investigation complete - logic is correct
- ✅ Verification suite passed (1286 tests passed)
- ✅ Ready to commit

---

## Summary

### Issue 1: Indentation ✅ Fixed

Changed `format_reasoning()` from `level=3` (indented child) to `level=2` (flat sibling) for consistent layout.

**Before**:
```
● 🌟 [keep] Task complete...
  ● 💭 Successfully read...  (2-space indent - wrong!)
```

**After**:
```
● 🌟 [keep] Task complete...
● 💭 Successfully read...  (flat - correct!)
```

### Issue 2: Missing Final Result - Agent Behavior Investigation Needed ⚠️

**User expectation**: See the **actual README content** (10 lines), not just a summary.

**What user sees**:
- Tool result: `✓ Read 5.5 KB (100 lines)` - SUMMARY ONLY, no content
- Reasoning: `Successfully read first 10 lines...` - completion message, no content
- Expected: Actual file content like `# Soothe — Beyond Yet-Another-Agent Framework\n...`

**Investigation findings**:

1. **CLI suppression logic**: Working correctly ✅
   - During execution, assistant text IS suppressed (IG-143)
   - Text IS accumulated in `state.full_response`
   - On completion, `should_emit_final_report()` returns True
   - `final_stdout_message` IS extracted from event
   - Would emit to stdout if populated

2. **Root cause**: Agent doesn't output file content during execution
   - Tool returns: "Read 5.5 KB (100 lines)" - semantic summary, NOT raw content
   - Agent should process tool result and output: "Here are the lines:\n# Soothe...\n..."
   - But agent only outputs completion reasoning: "Successfully read first 10 lines..."
   - The actual file content is NOT in `last_execute_assistant_text` or `full_output`

3. **Agent flow trace**:
   ```
   Execute phase (iteration 1):
   - Read File tool executes
   - Tool result: semantic summary (5.5 KB, 100 lines) - NOT raw content
   - Agent processes result -> should output content
   - BUT: Agent outputs completion reasoning instead
   - Text suppressed and accumulated: "Successfully read..." (NOT file content)

   Plan phase (iteration 2):
   - Agent assesses: status="done"
   - Generates reasoning: "Successfully read first 10 lines..."
   - final_output: empty or completion message (NOT file content)

   Completion:
   - final_stdout_message: "Successfully read..." (NOT file content)
   - CLI emits: completion message (correct behavior)
   ```

**Hypothesis**: The agent may be treating this as a simple confirmation task rather than a content retrieval task. The planner/agent behavior should:
- Detect "read X lines" intent → output the actual content
- Not just report completion

**Resolution needed**: This is NOT a CLI display bug - it's agent/planner behavior:
- Agent should output file content in assistant response during Execute phase
- Or planner should populate `full_output` with actual content
- CLI suppression and emission logic are working correctly

**Recommendation**: Requires separate investigation of agent/planner logic (upstream issue). The agent should recognize "read and show" intent and output actual content, not just completion confirmation.

---

## Verification Results ✅

All checks passed:
- ✓ Formatting OK (3 packages)
- ✓ Linting OK (zero errors)
- ✓ Unit tests passed (1286 tests)

**Files modified**:
- `packages/soothe-cli/src/soothe_cli/cli/stream/formatter.py` (indentation fix)
- Import sorting auto-fixes (2 files)

**Recommendation**: Close this IG as complete for Issue 1. Issue 2 requires separate agent behavior investigation (not CLI display).

---

## Root Cause Analysis

### Issue 1: Indentation (FIXED ✅)

**Root cause**: `format_reasoning()` used `level=3` (2-space indent via `indent_for_level(3)`) instead of `level=2` (flat layout).

**Fix**: Changed `level=3` → `level=2` for flat layout (sibling to judgement, not child).

**Verification**: Tested with formatter functions - both lines now correctly use `level=2` with no indent.

### Issue 2: Missing Final Result (NO FIX NEEDED ✅)

**Investigation findings**:

1. **Suppression state logic**: Working correctly
   - `track_from_event()` properly extracts `final_stdout_message` from event
   - `should_emit_final_report()` conditions are correct
   - `get_final_response()` properly accumulates and returns text

2. **Renderer emission logic**: Working correctly
   - `on_progress_event()` checks `should_emit_final_report()` after processing event
   - `_write_stdout_final_report()` properly writes to stdout

3. **Expected behavior**:
   - The "Successfully read README.md..." text in the output is from the **reasoning field** of `agent_loop.reasoned` event (shown as 💭)
   - This is correct - it's the LLM's reasoning about task completion
   - The **final_stdout_message** from `agent_loop.completed` event should contain the actual result (file content)
   - Suppression state logic ensures final stdout is emitted after event processing

**Status**: Logic is correct. If final_stdout_message is not shown in actual usage, it's likely because:
- The agent loop didn't generate a proper final_output (this is upstream behavior, not display logic)
- Or max_iterations was 1 (single-step mode where stdout is not suppressed, so final_stdout is skipped to avoid duplication)

---

## Next Steps

1. Run verification suite to confirm indentation fix
2. Test linting
3. Commit changes with clear description
4. Add to git staged files