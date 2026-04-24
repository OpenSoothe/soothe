# IG-163: CLI Intermediate Text Regression Investigation

**Implementation Guide ID:** IG-163
**Date:** 2026-04-12
**Status:** 🔍 Investigation
**Priority:** High - Core UX regression

---

## Regression Report

**Command**: `soothe --no-tui -p "count soothe readme files"`

**Expected behavior** (per IG-143):
- Intermediate LLM text suppressed during multi-step execution
- Final aggregated report shown at completion
- Clean, concise output (≤ 20 lines for typical execution)

**Actual behavior**:
- ❌ Intermediate step result displayed: "Found **68 README files**... Would you like me to proceed with step 2?"
- ❌ Final report NOT shown
- Output shows step completion line: "○ ⏩ Search for README files... matching [1 tools] (27.3s)"

---

## Root Cause Analysis

### Event Type Rename (Commit f2a1e9b)

**Changes**:
- `soothe.agentic.loop.started` → `soothe.cognition.agent_loop.started`
- `soothe.agentic.loop.completed` → `soothe.cognition.agent_loop.completed`

**Files updated**:
- `src/soothe/ux/shared/suppression_state.py` ✅
- `src/soothe/ux/shared/event_processor.py` ✅
- `src/soothe/ux/cli/stream/pipeline.py` ✅
- `src/soothe/ux/tui/renderer.py` ✅
- Test files ✅

**Verification**: All tests pass (1589 passed)

---

### Suppression Logic Flow

**Expected flow**:
1. AgentLoop started with `max_iterations > 1` OR PLAN_CREATED with `len(steps) > 1`
2. `SuppressionState.track_from_event()` sets `multi_step_active=True` and `agentic_stdout_suppressed=True`
3. Intermediate `on_assistant_text()` calls check `should_suppress_output()` → returns `True` → text blocked
4. Text accumulated in `full_response` list
5. AgentLoop completed → `should_emit_final_report()` → `_write_stdout_final_report()` → final output

**What's happening** (based on regression):
- Step 1 or 2 NOT triggering suppression
- Step 3 NOT blocking text → intermediate output leaks
- Step 5 NOT emitting final report

---

## Hypothesis: Suppression Not Activated

**Possible causes**:

### Case A: max_iterations=1

**Code**:
```python
# suppression_state.py line 100-107
if event_type == "soothe.cognition.agent_loop.started":
    if data.get("max_iterations", 1) > 1:
        self.multi_step_active = True
        self.agentic_stdout_suppressed = True
    else:
        self.agentic_stdout_suppressed = False  # NOT ARMED!
```

**Impact**: If AgentLoop runs with `max_iterations=1`, no suppression happens.

**Test verification**: `test_max_iter_one_multi_step_plan_suppresses_stdout_after_turn_end` shows this case should be handled by PLAN_CREATED event.

---

### Case B: No PLAN_CREATED Event

**Code**:
```python
# event_processor.py line 677-678
if etype == PLAN_CREATED and len(data.get("steps", [])) > 1:
    self._state.multi_step_active = True

# renderer.py line 339
self._state.suppression.track_from_plan(len(plan.steps))
```

**Impact**: If no formal plan created, no multi-step tracking.

**Evidence**: User output shows "○ ⏩ Search for README files..." which suggests step execution, but might be via `soothe.agentic.step.*` events (AgentLoop executor) rather than plan events.

---

### Case C: Different Execution Path

**Possible paths**:
1. **AgentLoop** (agentic runner) → emits `agent_loop.*` events ✅
2. **GoalEngine → AgentLoop delegation** (autonomous runner) → emits `agent_loop.*` events ✅
3. **Legacy execution** (bypasses AgentLoop) → might not emit proper events ❌

**Check**: `_runner_agentic.py` and `_runner_autonomous.py` emit proper events.

---

## Investigation Steps

### Step 1: Verify Execution Mode

**Action**: Check which runner path is being used

```bash
# Add logging to trace execution
soothe --no-tui --debug -p "count soothe readme files" 2>&1 | grep -E "runner.*path|AgentLoop|max_iterations|PLAN_CREATED"
```

**Expected log**:
- "AgentLoop.run_with_progress(max_iterations=...)"
- Event: `soothe.cognition.agent_loop.started` with `max_iterations` field
- (Optional) Event: `soothe.cognition.plan.created` with `steps` array

---

### Step 2: Check Event Flow

**Action**: Trace events in real time

```python
# Add to event_processor.py _handle_custom_event() (line ~637)
import logging
logger = logging.getLogger("soothe.ux.trace")
logger.info(f"event={etype} multi_step={self._state.multi_step_active} renderer_multi={self._renderer._state.suppression.multi_step_active}")
```

**Expected output**:
- `soothe.cognition.agent_loop.started` → both processor and renderer `multi_step_active` set to `True` (if `max_iterations > 1`)
- `soothe.cognition.plan.created` → `multi_step_active=True` (if `len(steps) > 1`)

---

### Step 3: Verify Suppression Check

**Action**: Trace suppression in renderer

```python
# Add to renderer.py on_assistant_text() (line ~172)
import logging
logger = logging.getLogger("soothe.ux.trace")
logger.info(f"assistant_text chars={len(text)} suppress={self._state.suppression.should_suppress_output()} multi={self._state.suppression.multi_step_active} agentic={self._state.suppression.agentic_stdout_suppressed}")
```

**Expected output**:
- Before loop completion: `suppress=True multi=True agentic=True` → text blocked
- After loop completion: `suppress=False` → final report emitted

---

## Proposed Fix

### Option 1: Add Logging and Verify

**Changes**:
- Add debug logging to trace suppression state activation
- Run user's exact command with logging enabled
- Identify where suppression fails to activate

---

### Option 2: Strengthen Suppression Activation

**Problem**: AgentLoop with `max_iterations=1` doesn't arm suppression

**Fix**: Always arm suppression for AgentLoop execution (even single iteration)

```python
# suppression_state.py line 100-107
if event_type == "soothe.cognition.agent_loop.started":
    # Always suppress stdout for AgentLoop execution (avoid intermediate text leaks)
    self.multi_step_active = True  # CHANGED: Always set
    self.agentic_stdout_suppressed = True  # CHANGED: Always arm
    self.agentic_final_stdout_emitted = False
    # Note: max_iterations field still tracked for internal logic
```

**Risk**: Might over-suppress for legitimate single-step queries

**Test impact**: Would need to update tests for `max_iterations=1` case

---

### Option 3: Add Fallback Suppression Check

**Problem**: If no suppression flags set, intermediate text leaks

**Fix**: Add backup suppression check in `on_assistant_text()` for AgentLoop context

```python
# renderer.py on_assistant_text()
# After existing suppression check (line ~172)
if self._state.suppression.should_suppress_output():
    self._state.suppression.accumulate_text(text)
    return

# NEW: Fallback - check if we're in AgentLoop execution (even without plan)
if self._state.current_plan or self._presentation.has_active_loop():
    # AgentLoop active but suppression not armed - block anyway
    self._state.suppression.accumulate_text(text)
    logger.warning("Fallback suppression activated (suppression flags not set)")
    return
```

**Risk**: Requires tracking "active loop" state in PresentationEngine

---

## Next Steps

1. ✅ Verify event type rename applied correctly
2. ✅ Confirm tests pass
3. 🔍 **USER ACTION**: Run command with debug logging to identify root cause
4. ⏳ Apply appropriate fix based on findings
5. ⏳ Update tests if needed
6. ⏳ Verify regression fixed

---

## Test Plan

After fix:

```bash
# Test command from regression report
soothe --no-tui -p "count soothe readme files"

# Verify:
# 1. No intermediate LLM text (no "Found 68 README files..." until completion)
# 2. Step progress shown via stderr (○ ⏩ lines)
# 3. Final report shown at completion
# 4. Output clean and concise (≤ 20 lines)
```

---

**Report Generated**: 2026-04-12
**Status**: Investigation in progress - awaiting user verification