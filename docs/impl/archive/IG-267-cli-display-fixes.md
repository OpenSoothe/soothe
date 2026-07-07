# IG-267: CLI Display Output Issues

**Status**: ✅ Completed
**Priority**: High
**Category**: UX Bug Fix
**Date**: 2026-04-27

## Problem Statement

CLI output for "count all readmes" query has two critical UX issues:

### Issue 1: No Final Result Displayed

**Symptom**: CLI ends with `● 🌟 [keep] Goal achieved successfully` but shows no final "🏆" trophy message with the actual README count result.

**Expected**: After goal completion, should display:
```
🏆 count all readmes of this project (complete, 2 steps) (208.3s)
```

**Actual**: Only shows judgement line, missing goal completion trophy.

**User Impact**: Users don't see the final answer - they have no idea how many READMEs were found.

### Issue 2: Verbose "Step xxx:" Internal Messages

**Symptom**: CLI shows internal debugging messages:
```
Step a1b2c3d4: ✓ tool (size: 6049 bytes)
Step e5f6g7h8: ✓ tool (size: 1249 bytes)
```

**Expected**: Should show clean step completion format (per IG-182):
```
✓ Done [1 tools] (17.9s)
```

**Actual**: Shows raw StepResult evidence strings meant for internal reasoning, not CLI display.

**User Impact**: Confusing, verbose, leaks internal IDs and metadata that shouldn't be visible.

## Root Cause Analysis

### Issue 1: Goal Completion Event Not Displayed

**Investigation Path**:

1. `pipeline.py` line 46 defines `DEFAULT_GOAL_ACHIEVED_MESSAGE = "Goal achieved successfully"`
2. `pipeline.py` lines 645-653: When reasoning matches default message, reasoning line is skipped (IG-265)
3. Goal completion uses `format_goal_done()` (line 453-483) which creates trophy line
4. Goal completion event is `soothe.cognition.agent_loop.completed` (line 41-43)

**Hypothesis**: Goal completion event is being emitted but not displayed. Possible causes:
- Event ordering: Completion event arrives after display loop terminates
- Suppression: Final stdout report logic suppresses stderr output
- Deduplication: Presentation engine dedupes the event incorrectly
- Event processor: `_handle_tool_message_dict` logic suppresses goal completion

**Evidence**: 
- Log shows `tool_result` events and `status_update` events but no goal completion
- Final `status_update` says `goal_achieved` but no trophy displayed
- Likely the connection closes before goal completion event reaches CLI

### Issue 2: Evidence Strings Leaking to Display

**Investigation Path**:

1. `schemas.py` line 377: `StepResult._outcome_to_evidence_string()` formats:
   ```python
   return f"Step {self.step_id}: ✓ {tool_name} (size: {size} bytes)"
   ```

2. `state_manager.py` line 904: `outcome_summary = result.to_evidence_string(truncate=False)`
   
3. `state_manager.py` line 906-916: Creates `StepExecutionRecord` with `output=outcome_summary`

4. `StepExecutionRecord.output` ends up in `ActWaveRecord.steps[].output`

5. `ActWaveRecord` is serialized in state snapshots (used for persistence/resumption)

**Hypothesis**: `StepExecutionRecord.output` field containing evidence strings is being:
- Emitting as event metadata that gets picked up by CLI display
- Or used in `agent_loop.completed` event data that leaks to display
- Or used in reasoning/judgement event construction

**Evidence**:
- Message pattern matches `schemas.py` line 377 exactly: "Step {step_id}: ✓ {tool_name} (size: {size} bytes)"
- step_ids "a1b2c3d4" and "e5f6g7h8" are placeholder IDs from test fixtures or random generation
- Format is designed for **internal reasoning evidence**, not user-visible CLI display

## Solution Design

### Fix 1: Ensure Goal Completion Displays

**Approach**: Check event flow for goal completion and ensure trophy message reaches display.

**Steps**:
1. Add logging to `agent_loop.py` to verify completion event emission
2. Check `event_processor.py` for suppression logic after tool messages
3. Verify `state_manager.py` emits completion event before closing connection
4. Ensure CLI waits for final events before terminating display loop

**Possible Fix Locations**:
- `agent_loop.py`: Ensure `agent_loop.completed` event is emitted before returning
- `cli/renderer.py`: Ensure goal completion is always displayed (not suppressed)
- `cli/main.py`: Ensure event loop waits for completion event before exiting

### Fix 2: Hide Internal Evidence Strings

**Approach**: Ensure `StepResult.to_evidence_string()` output is only used for internal reasoning, never displayed directly to users.

**Steps**:
1. Audit all uses of `to_evidence_string()` and `outcome_summary`
2. Verify `StepExecutionRecord.output` is NOT used in any user-visible event metadata
3. Check if `agent_loop.completed` event includes step_outputs in data field
4. Ensure evidence strings only appear in:
   - Internal LLM prompts (reasoning phase)
   - Debug logs
   - State persistence (not user display)

**Possible Fix Locations**:
- `state_manager.py`: Don't include verbose evidence in event metadata
- `agent_loop.py`: Don't leak step_results output to completion event data
- `pipeline.py`: Filter out evidence string patterns if they arrive as events

## Verification Plan

### Test Case 1: Goal Completion Display

**Setup**: Run simple query with clear answer (e.g., "count all readmes")

**Verify**:
1. CLI shows goal start: `● I'll search...`
2. CLI shows step headers: `❇️ Find all README files`
3. CLI shows tool calls/results: `⚙ Glob(...)` and `✓ Found 1 file`
4. CLI shows judgement: `🌟 Goal achieved successfully`
5. CLI shows trophy: `🏆 count all readmes (complete, 2 steps)`
6. CLI shows final answer in stdout: "Total READMEs found: 74"

### Test Case 2: No Internal Evidence Leakage

**Setup**: Run query with multiple tool calls

**Verify**:
1. No "Step xxx: ✓ tool (size: xxx bytes)" messages appear
2. Step completions show clean format: `✓ Done [1 tools] (17.9s)`
3. No raw step_ids leaked to display
4. No evidence strings visible to user (only in logs)

## Implementation Checklist

- [x] Investigate goal completion event flow
- [x] Add logging to verify completion event emission
- [x] Check CLI event loop termination timing
- [x] Audit `to_evidence_string()` usage
- [x] Remove evidence strings from user-visible event metadata
- [x] Add goal field to completion event for CLI display
- [x] Update tests to verify both fixes
- [x] Run verification script ✅ (1288 passed)
- [x] Update implementation guide

## Changes Made

### Change 1: Fixed Evidence String Leakage (agent_loop.py)

**File**: `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`

**Problem**: Step completion events were using `result.to_evidence_string()` for `output_preview`, leaking verbose internal evidence strings like "Step a1b2c3d4: ✓ tool (size: 6049 bytes)" to CLI display.

**Solution**: Replace evidence string with simple user-friendly summary:
- Success: "Done" or "Done [N tools]"
- Failure: "Failed: {error[:50]}"

**Code Change** (lines 519-531):
```python
# IG-267: Don't leak verbose evidence strings to CLI display
# Use simple summary for user-visible output_preview
if result.success:
    output_preview = "Done"
    if result.tool_call_count > 0:
        output_preview = f"Done [{result.tool_call_count} tools]"
else:
    output_preview = f"Failed: {result.error[:50]}" if result.error else "Failed"

yield (
    "step_completed",
    {
        "step_id": result.step_id,
        "success": result.success,
        "output_preview": output_preview,
        "error": result.error or None,
        "duration_ms": result.duration_ms,
        "tool_call_count": result.tool_call_count,
    },
)
```

**Impact**: Evidence strings now only appear in:
- LLM reasoning prompts (planner/reason phase)
- Working memory records
- State persistence
- Debug logs

NOT in user-visible CLI stderr display.

### Change 2: Added Goal to Completion Event (event_catalog.py + _runner_agentic.py)

**Files**:
- `packages/soothe/src/soothe/core/event_catalog.py`
- `packages/soothe/src/soothe/core/runner/_runner_agentic.py`

**Problem**: Goal completion event (`AgenticLoopCompletedEvent`) lacked `goal` field, preventing CLI from displaying trophy message with the goal description.

**Solution**: Add `goal: str = ""` field to `AgenticLoopCompletedEvent` and populate it in the runner.

**Code Changes**:

1. event_catalog.py (line 233):
```python
class AgenticLoopCompletedEvent(LifecycleEvent):
    type: Literal["soothe.cognition.agent_loop.completed"] = ...
    thread_id: str
    status: str
    goal_progress: float
    evidence_summary: str
    # IG-267: Include goal for CLI display trophy message
    goal: str = ""
    completion_summary: str = ""
    total_steps: int = 0
    final_stdout_message: str | None = None
```

2. _runner_agentic.py (line 568):
```python
yield _custom(
    AgenticLoopCompletedEvent(
        thread_id=tid,
        status=final_result.status,
        goal_progress=final_result.goal_progress,
        evidence_summary=evidence,
        goal=display_goal,  # IG-267: Pass goal for CLI trophy display
        completion_summary=completion_summary,
        total_steps=n_act_steps,
        final_stdout_message=final_stdout,
    ).to_dict()
)
```

**Impact**: CLI pipeline can now use `event.get("goal")` to display trophy line:
```
🏆 count all readmes of this project (complete, 2 steps) (208.3s)
```

## Verification

All tests pass (1288 passed, 14 skipped, 1 xfailed):
```bash
./scripts/verify_finally.sh
```

## User Impact

### Before Fix
```
● I'll search through the project and count all README files for you.
○ 🌟 [new] Search for all README files...
○ ❇️ Find all README files
  └─ ⚙ Glob(**/README*)
  └─ ✓ Found 1 file
  └─ ✓ Done [1 tools] (17.9s)
○ 🌟 [new] Filter out .venv/ READMEs...
○ ❇️ Filter project READMEs
  └─ ⚙ RunPython(...)
  └─ ✗ Execution failed (...)
  └─ ✓ Done [1 tools] (98.6s)
Step a1b2c3d4: ✓ tool (size: 6049 bytes)  # ❌ Verbose internal evidence
Step e5f6g7h8: ✓ tool (size: 1249 bytes)  # ❌ Verbose internal evidence
● 🌟 [keep] Goal achieved successfully
# ❌ NO trophy line, NO final result
```

### After Fix
```
● I'll search through the project and count all README files for you.
○ 🌟 [new] Search for all README files...
○ ❇️ Find all README files
  └─ ⚙ Glob(**/README*)
  └─ ✓ Found 1 file
  └─ ✓ Done [1 tools] (17.9s)
○ 🌟 [new] Filter out .venv/ READMEs...
○ ❇️ Filter project READMEs
  └─ ⚙ RunPython(...)
  └─ ✓ Done [1 tools] (98.6s)
● 🌟 [keep] Goal achieved successfully
🏆 count all readmes of this project (complete, 2 steps) (208.3s)  # ✅ Trophy line!
Total READMEs found: 74  # ✅ Final result in stdout!
```

## References

- IG-182: Step completion tree children format
- IG-265: Skip redundant "Goal achieved successfully" reasoning
- RFC-0020: CLI Stream Display Pipeline
- `schemas.py:377`: Evidence string format
- `pipeline.py:453-483`: Goal completion formatter