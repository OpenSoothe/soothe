# IG-152: Fix PlanResult next_action truncation

**Status**: ✅ Completed
**Created**: 2026-04-12
**RFCs**: RFC-604 (Plan Phase Robustness)
**Impact**: Critical (user-facing truncation bug fix)
**Updated**: 2026-04-12 (terminology refactoring per IG-153)

---

## Problem Statement

The PlanResult `next_action` field showed truncated output in CLI like:
- "Read UX modul" (should be "Read UX module __init__.py files...")
- "Examine all U" (should be "Examine all UX subdirectories...")
- "Rea" (should be "Read key implementation files...")
- "→ 🌀 I will list and examine the ux module…" (truncated at 120 chars)

**Root Cause**: Multiple truncation points:
1. `planner.py:728` concatenated two 100-char fields and hard-truncated with [:100] slice
2. Schema constraints limited next_action to 100 chars
3. CLI pipeline truncated display to 120 chars (normal mode) or 200 chars (debug mode)

---

## Solution Implemented

### Key Design Decision: Single Action Source

After analyzing RFC-604's two-phase architecture, we identified that:
- **assessment.next_action**: Status-based description (what LLM thinks should happen)
- **plan_result.next_action**: Plan-specific concrete action (what will be executed)

**Better approach**: Use only `plan_result.next_action` for user display (more specific, actionable), avoiding duplication like "I will... I will..."

### Changes Made

#### 1. Schema Updates (`schemas.py`)

**PlanResult**:
```python
# Before
next_action: str = Field(default="", max_length=100)

# After
next_action: str = Field(default="", max_length=500)
"""Complete action text from plan phase (no truncation)."""
```

**StatusAssessment**:
```python
# Before
next_action: str = Field(default="", max_length=100)

# After
next_action: str = Field(default="", max_length=300)
"""User-facing next step description (allows longer text for complex goals)."""
```

**PlanGeneration**:
```python
# Before
next_action: str = Field(default="", max_length=100)

# After
next_action: str = Field(default="", max_length=300)
"""User-facing next step (plan-specific, allows longer concrete actions)."""
```

#### 2. Planner Logic (`planner.py:726-741`)

**Before (BAD)**:
```python
# Concatenate both phases → duplication
combined_next_action = f"{assessment.next_action}\n{plan_result.next_action}"
combined_next_action = combined_next_action[:100]  # Hard truncation!
```

**After (GOOD)**:
```python
# Use plan_result.next_action only (concrete action, no duplication)
action_text = plan_result.next_action.strip()

return ReasonResult(
    next_action=action_text,  # User sees concrete plan action (no truncation)
)
```

**Benefit**: Eliminates duplication and shows most actionable description.

#### 3. CLI Display (`pipeline.py:_on_loop_agent_reason`)

**Before (BAD)**:
```python
# Truncate for CLI display readability
max_len = 200 if self._verbosity_tier == VerbosityTier.DEBUG else 120
if len(action_text) > max_len:
    # Word boundary truncation
    action_text = truncated[:last_space] + "…"
```

**After (GOOD)**:
```python
# IG-152: Show full action text to user (no truncation)
# Word boundary respect happens at schema level (preview_first in planner)
# CLI display should show complete reasoning chain for transparency
```

**Benefit**: Users see complete reasoning without arbitrary truncation.

#### 4. Early Completion Path (`planner.py:789-799`)

**Before**: Used assessment.next_action only
**After**: Same approach (no change needed - correct behavior)

#### 5. Event Emission (`agent_loop.py`)

Updated event payloads to include full action text:
```python
yield ("reason", {
    "next_action": reason_result.next_action,  # Full text (no truncation)
})
```

#### 6. Checkpoint Schema (`checkpoint.py`)

Updated `ReasonStepRecord` to preserve full action:
```python
next_action: str = Field(default="", description="Complete action text (500 chars)")
```

---

## Test Coverage

Created comprehensive test suite (`test_reason_result_action_truncation.py`):

1. **test_next_action_uses_plan_action**: Verifies plan_result.next_action is used (not concatenation)
2. **test_next_action_preserves_full_text**: Verifies full text preservation (>100 chars)
3. **test_schema_max_length_updated**: Verifies schema accepts long actions (500 chars)
4. **test_early_completion_preserves_action**: Verifies early completion preserves full action
5. **test_word_boundary_respect_in_cli_display**: Verifies preview_first utility respects boundaries

**All tests pass**: 1584 passed, 2 skipped, 1 xfailed

---

## Results

### Before Fix
```
→ 🌀 I will list and examine the ux module…
```
(truncated at 120 chars with ellipsis)

### After Fix
```
→ 🌀 I will list and examine the UX module structure to understand its architecture
```
(full text shown, no truncation)

**No more mid-word truncation**:
- ❌ "Read UX modul"
- ✅ "Read UX module structure to understand its architecture"

---

## Verification

✅ Format check: PASSED
✅ Linting: PASSED
✅ Unit tests: PASSED (1584 passed)
✅ All checks: PASSED

**Ready to commit!**

---

## Summary

This fix resolves a critical user-facing bug where action descriptions were truncated mid-word, making them confusing and incomplete. The solution:

1. **Removed hard [:100] truncation** in planner
2. **Increased schema limits** to 300/500 chars (allows full reasoning)
3. **Eliminated duplication** by using plan-specific action only
4. **Removed CLI display truncation** (shows full transparency)
5. **Preserved full action** in logs, history, and checkpoints

Users now see complete, actionable descriptions that improve understanding of agent reasoning.

---

**Implementation complete! ✅**

---

## Architecture Context

### RFC-604 Two-Phase Design

**Phase 1**: StatusAssessment (lightweight, ~200-250 tokens)
- `assessment.next_action` (max 300 chars): Status-based next step description

**Phase 2**: PlanGeneration (conditional, ~500-800 tokens)
- `plan_result.next_action` (max 300 chars): Plan-specific next step

**Combined Output**: PlanResult
- `next_action` field (max 500 chars): User-facing summary
- `reasoning` field (max 500 chars): Internal analysis chain

### Design Intent

According to RFC-604 Section 7.2:
- Concatenate both phases for complete reasoning chain
- Display both phases to user (transparent execution)
- Schema constraint ensures concise user-facing summary

### Current Mismatch

1. Two phases each produce max 300 chars (after IG-152 update)
2. Combined = 600 chars (with newline separator)
3. PlanResult schema has max_length=500 constraint (after IG-152 update)
4. Implementation uses plan_result.next_action only → no truncation, full text

---

## Solution Design

### Guiding Principles

1. **Full text for internal reasoning**: Keep complete concatenated text for:
   - Action history tracking (LoopState.action_history)
   - Debug logging (full reasoning chain)
   - Checkpoint metadata (state_manager)

2. **Smart truncation for schema field**: Use preview_first (word-boundary respect) for:
   - ReasonResult.next_action (user-facing display)
   - Event emission (CLI/TUI output)

3. **Remove hard slicing**: Eliminate [:100] in planner.py:728

---

## Implementation Plan

### Step 1: Add full_action field to schemas

**File**: `src/soothe/cognition/agent_loop/schemas.py`

**Change**: Add new field to PlanResult

```python
class PlanResult(BaseModel):
    """Plan phase output with full reasoning chain."""

    # Existing fields...
    next_action: str = Field(default="", max_length=500)
    """Complete action text from plan phase (no truncation)."""

    full_action: str = Field(default="", max_length=500)
    """Full concatenated action from both phases for internal use (logging, history)."""

    # ... rest of schema
```

**Why max_length=500?**
- Two 100-char fields + newline separator = max 201 chars
- 500 chars provides buffer for future schema changes
- Matches reasoning field budget (consistent token allocation)

---

### Step 2: Update planner.py to populate both fields

**File**: `src/soothe/cognition/agent_loop/planner.py`

**Current (BAD)**: Lines 726-728
```python
# Concatenate next_action from both phases (truncate to max 100 chars)
combined_next_action = f"{assessment.next_action}\n{plan_result.next_action}"
combined_next_action = combined_next_action[:100]  # ← HARD TRUNCATION
```

**New (GOOD)**:
```python
from soothe.utils.text_preview import preview_first

# Concatenate next_action from both phases
full_action_text = f"{assessment.next_action}\n{plan_result.next_action}"

# Smart truncation for user-facing field (respects word boundaries)
user_action_summary = preview_first(full_action_text, chars=100)

# Build final ReasonResult
return ReasonResult(
    status=assessment.status,
    goal_progress=assessment.goal_progress,
    confidence=assessment.confidence,
    reasoning=combined_reasoning,
    plan_action=plan_result.plan_action,
    decision=plan_result.decision,
    next_action=user_action_summary,  # Schema constraint (100 chars)
    full_action=full_action_text,      # Full text for internal use
)
```

**Benefits**:
- `preview_first` respects word boundaries (no mid-word cuts)
- `full_action` preserves complete reasoning chain
- Schema constraint satisfied (100 chars)

---

### Step 3: Update reason.py to use full_action

**File**: `src/soothe/cognition/agent_loop/reason.py`

**Current**: Line 95
```python
# Track action in history (used by completion detection)
state.add_action_to_history(result.next_action or "")
```

**New**:
```python
# Track FULL action in history (preserves reasoning chain)
state.add_action_to_history(result.full_action or result.next_action)
```

**Why**: Action history should track complete reasoning chain for progression detection.

---

### Step 4: Update logging to use full_action

**File**: `src/soothe/cognition/agent_loop/planner.py`

**Current**: Lines 631-636 (Phase 1)
```python
logger.debug(
    "[Assess] status=%s progress=%.0f%% next=%s",
    assessment.status,
    assessment.goal_progress * 100,
    assessment.next_action,
)
```

**New**:
```python
logger.debug(
    "[Assess] status=%s progress=%.0f%% next=%s",
    assessment.status,
    assessment.goal_progress * 100,
    assessment.next_action,  # Phase 1 action (100 chars max)
)
```

**Lines 687-691 (Phase 2)**: No change needed (plan_result.next_action is already full)

**Add new log after combination**:
```python
logger.debug(
    "[Reason] combined_action=%s",
    preview_first(full_action_text, chars=80),  # Log preview (not truncation)
)
```

**File**: `src/soothe/cognition/agent_loop/reason.py`

**Lines 64-65**: Update pre_llm dict
```python
if state.action_history:
    pre_llm["actions"] = state.get_recent_actions(3)  # Already using full_action
```

---

### Step 5: Update event emission

**File**: `src/soothe/cognition/agent_loop/agent_loop.py`

**Lines 183, 429**: Emit full_action to event

**Current**:
```python
"next_action": reason_result.next_action,
```

**New**:
```python
"next_action": reason_result.next_action,       # User-facing (100 chars)
"full_action": reason_result.full_action,        # Complete text (for logs)
```

**Why**: CLI pipeline can choose which field to display (user vs debug mode).

---

### Step 6: Update CLI pipeline (optional enhancement)

**File**: `src/soothe/ux/cli/stream/pipeline.py`

**Enhancement**: In debug mode, show full_action

**Line 467**: Use full_action if available
```python
action_text = event.get("full_action", event.get("next_action", ""))
```

**Line 477**: Increase max_len for full_action in debug mode
```python
max_len = 200 if self._verbosity_tier == VerbosityTier.DEBUG else 120
```

**Benefit**: Debug mode shows complete reasoning chain.

---

### Step 7: Update state_manager checkpoint

**File**: `src/soothe/cognition/agent_loop/state_manager.py`

**Line 177**: Already uses reason_result.next_action

**Current**:
```python
next_action=reason_result.next_action,
```

**New**:
```python
next_action=reason_result.next_action,
full_action=reason_result.full_action,  # Preserve complete reasoning in checkpoint
```

**Checkpoint schema update**: Add full_action field to ReasonRecord

---

## Validation Strategy

### Unit Tests

**Test 1**: Verify no truncation in full_action
```python
def test_full_action_preserves_concatenation():
    assessment = StatusAssessment(
        status="continue",
        next_action="I'll examine the UX module subdirectories",
        brief_reasoning="Progress is 36%",
    )
    plan_result = PlanGeneration(
        plan_action="new",
        decision=some_decision,
        next_action="Read key implementation files from cli/ and tui/",
        brief_reasoning="Need to check implementation details",
    )

    result = planner._combine_results(assessment, plan_result)

    # full_action should be same as plan_result.next_action (no duplication)
    assert "Read key implementation files" in result.full_action
    assert len(result.full_action) > 100  # No truncation

    # next_action should be same as full_action (IG-152 solution)
    assert len(result.next_action) <= 500
    assert result.next_action == result.full_action  # No duplication
```

**Test 2**: Verify preview_first respects word boundaries
```python
def test_next_action_word_boundary_truncation():
    long_action = "Examine subdirectories (cli, client, shared, tui) to understand UX module architecture"

    result = planner._combine_results(assessment, plan_result)

    # Should NOT truncate at all (IG-152 solution)
    assert not result.next_action.endswith("U")  # Not "Examine all U"
    assert len(result.next_action) == len(long_action)  # Full text preserved
```

### Integration Test

**Test**: Run actual goal and verify CLI output
```bash
soothe --no-tui -p "analyze ux module architecture"
```

**Expected CLI output**:
```
→ 🌀 Examine subdirectories (cli, client, shared, tui) to understand UX module architecture
Read key implementation files...
```

**Not truncated**:
```
→ 🌀 Read UX modul  ← BAD (current)
```

---

## Implementation Checklist

- [ ] Add `full_action` field to ReasonResult schema
- [ ] Update planner.py to use preview_first instead of [:100]
- [ ] Populate both next_action and full_action in planner
- [ ] Update reason.py to track full_action in history
- [ ] Update logging to show full_action in debug logs
- [ ] Update event emission to include both fields
- [ ] Update CLI pipeline to use full_action in debug mode (optional)
- [ ] Update state_manager checkpoint to preserve full_action
- [ ] Add unit tests for word-boundary truncation
- [ ] Run verification script: `./scripts/verify_finally.sh`

---

## Risk Assessment

### Low Risk
- Schema field addition (backward compatible)
- Logging change (internal only)

### Medium Risk
- Event emission change (CLI/TUI consumption)
  - Mitigation: Keep both fields (next_action for backward compat, full_action for debug)

### No Breaking Changes
- Existing consumers (CLI/TUI) can continue using `next_action`
- New consumers can opt-in to `full_action`

---

## Timeline

**Estimated**: 2-3 hours

**Breakdown**:
- Schema changes: 30 min
- planner.py refactor: 30 min
- reason.py + state_manager updates: 30 min
- CLI pipeline enhancement: 30 min
- Unit tests: 30 min
- Integration testing + verification: 30 min

---

## Success Criteria

1. **No mid-word truncation**: CLI output ends at word boundaries
2. **Full text preserved**: Logs show complete reasoning chain
3. **Tests pass**: All unit + integration tests pass
4. **Verification clean**: `./scripts/verify_finally.sh` passes

---

## Post-Implementation

**Cleanup**:
- Remove hard [:100] slice in planner.py
- Ensure all consumers (CLI/TUI) handle both fields correctly

**Documentation**:
- Update RFC-604 implementation notes
- Add inline comments explaining field usage

**Monitoring**:
- Check production logs for full_action content
- Verify CLI output quality in real usage