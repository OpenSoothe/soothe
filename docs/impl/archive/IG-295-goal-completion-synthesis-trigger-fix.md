# IG-295: Goal Completion Synthesis Trigger Fix

**Status**: In Progress
**Date**: 2026-04-28
**Issue**: Planner's `require_goal_completion=True` ignored by synthesis policy

---

## Problem Statement

The planner sets `require_goal_completion=True` when:
- Assistant response is too short (word count < 150)
- High evidence volume with moderate output
- Other heuristics indicate synthesis needed

However, `evidence_requires_final_synthesis()` in `synthesis.py` only considers step count:
- Returns `False` when steps < 2
- Doesn't check `plan_result.require_goal_completion`

**Result**: Goal completion synthesis is skipped despite planner recommendation.

**User Impact**: Explicit instruction "MUST perform goal completion" is ignored for single-step goals.

---

## Root Cause

**File**: `packages/soothe/src/soothe/cognition/agent_loop/analysis/synthesis.py:30-58`

```python
def evidence_requires_final_synthesis(state: LoopState, plan_result: PlanResult) -> bool:
    _ = plan_result  # ← plan_result ignored!
    if len(state.step_results) < _SYNTHESIS_MIN_STEPS:  # ← Only checks step count
        return False
    # ... other checks
```

**Decision Flow**:
1. Planner detects low word count → `require_goal_completion=True`
2. Synthesis policy checks step count → `False` (1 step < 2 threshold)
3. `should_return_goal_completion_directly()` sees synthesis not needed → returns short response
4. Goal completion enrichment skipped

---

## Solution

Update `evidence_requires_final_synthesis()` to honor planner's explicit request:

**Priority**:
1. First check `plan_result.require_goal_completion` (planner's explicit recommendation)
2. Then check evidence-based thresholds (step count, evidence length, etc.)

This ensures planner's heuristics (word count, evidence volume) are respected even for single-step goals.

---

## Implementation Plan

1. Edit `synthesis.py` to check `plan_result.require_goal_completion` first
2. Keep existing evidence thresholds as fallback when planner doesn't request synthesis
3. Run verification suite to ensure tests pass
4. Verify with log analysis that fix works

---

## Code Changes

**File**: `packages/soothe/src/soothe/cognition/agent_loop/analysis/synthesis.py`

**Change**: Update `evidence_requires_final_synthesis()` to prioritize planner recommendation:

```python
def evidence_requires_final_synthesis(state: LoopState, plan_result: PlanResult) -> bool:
    # Honor planner's explicit goal completion request (IG-295)
    if plan_result.require_goal_completion:
        return True

    # Evidence-based thresholds (RFC-603)
    if len(state.step_results) < _SYNTHESIS_MIN_STEPS:
        return False

    successful_steps = [r for r in state.step_results if r.success]
    if not successful_steps:
        return False
    success_rate = len(successful_steps) / len(state.step_results)
    if success_rate < _SYNTHESIS_MIN_SUCCESS_RATE:
        return False

    total_evidence_length = sum(len(r.to_evidence_string(truncate=False)) for r in successful_steps)
    if total_evidence_length < _SYNTHESIS_MIN_EVIDENCE_LENGTH:
        return False

    unique_step_ids = {r.step_id for r in successful_steps}
    return len(unique_step_ids) >= _SYNTHESIS_MIN_UNIQUE_STEPS
```

---

## Testing Strategy

1. Run existing unit tests to ensure backward compatibility
2. Verify fix with real execution:
   - Goal: "read 10 lines of project readme. MUST perform goal completion"
   - Expected: Synthesis should run despite single step
   - Check logs for `Goal completion: branch=synthesis`

---

## Success Criteria

- ✅ Planner `require_goal_completion=True` triggers synthesis
- ✅ Evidence-based thresholds still work for multi-step goals
- ✅ All existing tests pass
- ✅ Single-step goals with low word count get synthesis enrichment

---

## References

- RFC-603: Event Processing & Filtering (synthesis phase)
- IG-268: Response Length Policy
- IG-273: Structural Payload Fallbacks
- Code: `final_response_policy.py:164-168` (calls `evidence_requires_final_synthesis`)
- Planner: `planner.py:857-880` (sets `require_goal_completion`)