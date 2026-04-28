# IG-298: Goal Completion Hybrid Policy Implementation

**Status**: Completed
**Date**: 2026-04-28
**RFC**: RFC-615
**Issue**: Planner overrides LLM decision with word-count heuristics; duplicate decision logic across modules

---

## Objective

Implement unified hybrid decision policy for goal completion synthesis:
- LLM primary decision (StatusAssessment.require_goal_completion)
- Heuristic fallback based on execution complexity (not word count)
- Single decision authority in dedicated policy module
- Remove duplicate heuristics from synthesis_policy

---

## Design Principles

### Hybrid Logic (LLM Primary, Heuristic Fallback)

**Priority**:
1. If LLM requests synthesis → True (honored)
2. If LLM returns False → check execution heuristics
3. Only skip synthesis if both agree (LLM=False, heuristic=False)

### Simplified Execution-Focused Heuristics

**Remove**: Word count, evidence vs output ratio (output metrics)
**Keep**: Execution complexity, wave patterns, step diversity (process metrics)

**Heuristic Categories**:
1. **Wave Execution**: Parallel multi-step, subagent cap
2. **Multi-Wave**: ≥2 execution waves
3. **Step Complexity**: ≥3 steps, DAG dependencies
4. **Completion Quality**: Failed steps with low success rate
5. **Step Diversity**: Multiple execution types (tool/subagent)

---

## Implementation Plan

### Step 1: Create Policy Module

**File**: `packages/soothe/src/soothe/cognition/agent_loop/policies/goal_completion_policy.py`

**Contents**:
- `determine_goal_completion_needs()` - hybrid decision function
- `_heuristic_requires_goal_completion()` - execution complexity checks
- Decision modes: llm_only, heuristic_only, hybrid
- Threshold constants for execution complexity

### Step 2: Update Planner

**File**: `packages/soothe/src/soothe/cognition/agent_loop/core/planner.py`

**Changes**:
- Remove `_should_require_goal_completion()` method (lines 832-880)
- Import `determine_goal_completion_needs()` from policy module
- Replace heuristic override with hybrid decision call (line 969)
- Trust LLM decision when status="done"

### Step 3: Simplify Synthesis Policy

**File**: `packages/soothe/src/soothe/cognition/agent_loop/policies/synthesis_policy.py`

**Changes**:
- Remove evidence thresholds from `evidence_requires_final_synthesis()` (lines 69-84)
- Simplify to: return `plan_result.require_goal_completion`
- Keep IG-295 comment for historical reference

### Step 4: Update Completion Strategies

**File**: `packages/soothe/src/soothe/cognition/agent_loop/completion/completion_strategies.py`

**Changes**:
- Update comments to reference hybrid decision from planner
- No code changes (already trusts plan_result)

### Step 5: Add Unit Tests

**File**: `packages/soothe/tests/unit/cognition/agent_loop/policies/test_goal_completion_policy.py`

**Tests**:
- LLM primary decision (llm_decision=True → True)
- Heuristic fallback (LLM=False + parallel_multi_step → True)
- Multi-wave execution (iteration ≥ 2 → True)
- Step complexity (step_count ≥ 3 → True)
- Failed steps handling (success_rate < 0.7 → True)
- Step diversity (multiple outcome types → True)

### Step 6: Verification

```bash
./scripts/verify_finally.sh
```

---

## Threshold Constants

```python
_COMPLEX_WAVE_THRESHOLD = 2      # ≥2 waves → multi-stage task
_COMPLEX_STEPS_THRESHOLD = 3     # ≥3 steps → non-trivial task
_DAG_DEPENDENCY_THRESHOLD = 2    # ≥2 dependencies → complex orchestration
_LOW_SUCCESS_RATE_THRESHOLD = 0.7  # <70% success → needs explanation
```

---

## Decision Flow

```
1. LLM → StatusAssessment.require_goal_completion
2. Planner calls determine_goal_completion_needs(llm_decision, state, mode="hybrid")
3. Policy module:
   - If LLM=True → return True (honored)
   - If LLM=False → check execution heuristics
   - Return heuristic result as fallback
4. Planner sets PlanResult.require_goal_completion (final decision)
5. Completion module trusts PlanResult (no re-checking)
6. Synthesis policy trusts PlanResult (no duplicate heuristics)
```

---

## Success Criteria

- ✅ LLM decision honored as primary source
- ✅ Execution heuristics applied as fallback
- ✅ Single decision authority in policy module
- ✅ No duplicate heuristics across modules
- ✅ Word count metrics removed
- ✅ All existing tests pass
- ✅ New policy module unit-testable

---

## References

- RFC-615: Goal Completion Module Architecture
- IG-295: Planner recommendation honored
- IG-296: Synthesis policy module refactoring
- IG-297: Goal completion module implementation