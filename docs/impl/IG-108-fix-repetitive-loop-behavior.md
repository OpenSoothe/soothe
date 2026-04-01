# IG-108: Fix Repetitive Loop Behavior in Layer 2

## Problem

The LoopAgent repeats the same steps (e.g., "list workspace", "read README") across iterations because:

1. `_build_plan_context()` never passes `completed_steps` to the planner
2. `state.completed_step_ids.clear()` clears tracking on replan
3. Planner has no memory of what was already executed

## Root Cause Analysis

### Evidence Chain

```
Iteration 1: Execute "list directory", "read README"
Judge: "replan" (progress=0.2, goal not achieved)
Loop: state.completed_step_ids.clear() + state.current_decision = None
Planner: Called with empty PlanContext.completed_steps
Planner: Creates similar steps again
Iteration 2: Execute "list directory", "read README" (REPEAT!)
```

### Code Locations

- `loop_agent.py:306-323` - `_build_plan_context()` missing `completed_steps`
- `loop_agent.py:266-267` - Clears `completed_step_ids` on replan
- `simple.py:412-420` - Prompt includes judgment but NOT executed steps
- `schemas.py:162-213` - `LoopState.step_results` preserves results but not used

## Solution

### 1. Pass Completed Steps to Planner

Modify `_build_plan_context()` to accept `state` and populate `completed_steps`:

```python
def _build_plan_context(self, state: LoopState) -> PlanContext:
    # Convert LoopState.step_results to planner's StepResult format
    completed = [
        StepResult(
            step_id=r.step_id,
            output=r.output or r.error or "",
            success=r.success,
            duration_ms=r.duration_ms,
        )
        for r in state.step_results
    ]

    return PlanContext(
        available_capabilities=available_tools + available_subagents,
        recent_messages=[],
        completed_steps=completed,  # NOW PLANNER KNOWS WHAT WAS DONE
    )
```

### 2. Preserve Evidence Across Replan

Keep `step_results` accumulated across iterations (don't clear).
Only clear `completed_step_ids` (step tracking for current decision).

### 3. Update Planner Prompts

The `_build_step_decision_prompt` already has logic to include `completed_steps`
but it was never populated. Now it will show executed steps.

## Implementation Steps

1. Edit `loop_agent.py:_build_plan_context()` - add `state` parameter
2. Edit `loop_agent.py:run_with_progress()` - pass `state` to `_build_plan_context()`
3. Verify planner prompts include completed steps information

## Verification

Run `./scripts/verify_finally.sh` after changes.