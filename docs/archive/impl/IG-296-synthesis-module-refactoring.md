# IG-296: Synthesis Module Refactoring

**Status**: Completed
**Date**: 2026-04-28
**Issue**: Mixed decision/execution logic in synthesis.py violates separation of concerns

---

## Problem Statement

**Current Structure**:
- `analysis/synthesis.py` contains BOTH:
  - Decision logic: `evidence_requires_final_synthesis()` ❌ (misplaced)
  - Execution logic: `SynthesisPhase` class (LLM calls, goal classification) ✅

- `policies/final_response_policy.py` contains:
  - Other synthesis decisions: `should_return_goal_completion_directly()`, `needs_final_thread_synthesis()`
  - Imports `evidence_requires_final_synthesis()` from synthesis.py

**Issue**: `synthesis.py` mixes **decision** with **execution** - violates clean architecture.

---

## Solution: Rename + Refactor (Not Merge)

**Refactoring**:

1. **Rename module**: `final_response_policy.py` → `synthesis_policy.py`
   - Better semantics: "synthesis policy" vs "final response policy"
   - Aligns with purpose: ALL synthesis decision logic

2. **Move decision logic**: `evidence_requires_final_synthesis()` → `synthesis_policy.py`
   - Consolidate ALL synthesis decisions in one module
   - Keep execution logic (`SynthesisPhase`) in `analysis/synthesis.py`

3. **Clear separation**:
   - `policies/synthesis_policy.py` = Decision logic ("should we synthesize?")
   - `analysis/synthesis.py` = Execution logic ("how to synthesize?")

---

## Implementation Plan

1. Create `synthesis_policy.py` (rename from `final_response_policy.py`)
2. Move `evidence_requires_final_synthesis()` + thresholds from `synthesis.py` to `synthesis_policy.py`
3. Update imports across codebase:
   - `agent_loop.py`: Import from `synthesis_policy`
   - `synthesis.py`: Import from `synthesis_policy` for `SynthesisPhase.should_synthesize()`
4. Update tests to import from `synthesis_policy`
5. Run verification suite

---

## Module Semantics After Refactoring

**`policies/synthesis_policy.py`** (Decisions):
- `evidence_requires_final_synthesis()` - Evidence threshold checks + planner recommendation
- `should_return_goal_completion_directly()` - Direct return policy
- `needs_final_thread_synthesis()` - Synthesis need policy
- Threshold constants: `_SYNTHESIS_MIN_STEPS`, `_SYNTHESIS_MIN_SUCCESS_RATE`, etc.

**`analysis/synthesis.py`** (Execution):
- `SynthesisPhase` class - LLM synthesis generation
- `_classify_goal_type()` - Goal classification
- `synthesize()` - Execution logic
- Imports `evidence_requires_final_synthesis()` from policy for `should_synthesize()`

**Clear Architecture**:
- ✅ Policy module = pure decision functions (no LLM calls)
- ✅ Analysis module = execution logic (LLM calls, template building)
- ✅ Module names reflect purpose
- ✅ Separation of concerns

---

## Code Changes

### 1. Create synthesis_policy.py

**Rename**: `policies/final_response_policy.py` → `policies/synthesis_policy.py`

**Add**: Move evidence thresholds and decision function from synthesis.py:

```python
# Moved from synthesis.py (IG-296)
_SYNTHESIS_MIN_STEPS = 2
_SYNTHESIS_MIN_SUCCESS_RATE = 0.6
_SYNTHESIS_MIN_EVIDENCE_LENGTH = 500
_SYNTHESIS_MIN_UNIQUE_STEPS = 2

def evidence_requires_final_synthesis(state: LoopState, plan_result: PlanResult) -> bool:
    """Return True when synthesis is needed based on planner recommendation or evidence thresholds.

    Priority:
    1. Planner's explicit request (require_goal_completion=True)
    2. Evidence-based thresholds (step count, evidence length, success rate)
    """
    # Honor planner's explicit goal completion request (IG-295)
    if plan_result.require_goal_completion:
        return True

    # Evidence-based thresholds (RFC-603)
    if len(state.step_results) < _SYNTHESIS_MIN_STEPS:
        return False
    # ... rest of logic
```

### 2. Update synthesis.py

**Remove**: Decision logic (moved to synthesis_policy.py)
**Keep**: Execution logic (`SynthesisPhase` class)
**Import**: `evidence_requires_final_synthesis()` from policy

```python
from soothe.cognition.agent_loop.policies.synthesis_policy import evidence_requires_final_synthesis

class SynthesisPhase:
    def should_synthesize(self, _goal: str, state: LoopState, plan_result: PlanResult) -> bool:
        """Determine if synthesis should run."""
        return evidence_requires_final_synthesis(state, plan_result)
```

### 3. Update imports

**Files to update**:
- `agent_loop.py`: Import from `synthesis_policy`
- Tests: `test_final_response_policy.py` → `test_synthesis_policy.py`
- Rename test class: `TestFinalResponsePolicy` → `TestSynthesisPolicy`

---

## Testing Strategy

1. Run existing synthesis tests (should pass with updated imports)
2. Run full verification suite
3. Check that IG-295 fix still works (planner recommendation honored)

---

## Success Criteria

- ✅ Decision logic consolidated in `synthesis_policy.py`
- ✅ Execution logic stays in `synthesis.py`
- ✅ Clear module semantics (policy vs execution)
- ✅ All tests pass
- ✅ IG-295 fix preserved

---

## References

- IG-295: Goal completion synthesis trigger fix
- RFC-603: Event Processing & Filtering (synthesis phase)
- Clean Architecture: Separation of concerns (decision vs execution)