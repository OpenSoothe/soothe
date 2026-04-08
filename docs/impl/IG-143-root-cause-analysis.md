# IG-143 Root Cause Analysis - State Synchronization Bug

**Date**: 2026-04-08
**Bug ID**: IG-143-STATE-SYNC
**Severity**: Critical (breaks core functionality)
**Status**: Root cause identified

---

## Executive Summary

IG-143 implementation has a **critical state synchronization bug** causing 100% of intermediate LLM text to leak through suppression logic. The bug stems from dual state objects (ProcessorState and CliRendererState) that are not synchronized because `EventProcessor._handle_custom_event()` returns early before calling `renderer.on_progress_event()`.

---

## Root Cause: Early Return Blocks State Synchronization

### Bug Location

**File**: `src/soothe/ux/shared/event_processor.py`
**Lines**: 681-684

```python
# Agentic loop started: track multi-iteration but suppress the goal echo
# (the goal just duplicates the user's input shown above)
if etype == "soothe.agentic.loop.started":
    if data.get("max_iterations", 1) > 1:
        self._state.multi_step_active = True
    return  # <-- BUG: Early return prevents renderer from receiving event!
```

### Impact Chain

```
EventProcessor._handle_custom_event()
  ├─> Line 683: Sets processor._state.multi_step_active = True
  ├─> Line 684: Returns early ⚠️
  └─> NEVER reaches line 697: renderer.on_progress_event()

CliRenderer.on_progress_event() (line 314-321 in renderer.py)
  ├─> Should set renderer._state.multi_step_active = True
  ├─> Should set renderer._state.agentic_stdout_suppressed = True
  └─> BUT NEVER CALLED ⚠️

CliRenderer.on_assistant_text() (line 177-180)
  ├─> Checks renderer._state.multi_step_active (False) ⚠️
  ├─> Checks renderer._state.agentic_stdout_suppressed (False) ⚠️
  └─> Does NOT suppress text (allows 800+ lines to flow through) ⚠️
```

---

## Evidence: Dual State Objects Not Synchronized

### State Object Separation

```python
# Two independent state objects:
EventProcessor._state → ProcessorState (processor_state.py)
CliRenderer._state → CliRendererState (renderer.py)

# They are NOT shared:
assert renderer._state is not processor._state  # True - different objects!
```

### State After `soothe.agentic.loop.started` Event

| State Variable | Processor | Renderer | Match? |
|----------------|-----------|----------|--------|
| `multi_step_active` | `True` ✅ | `False` ❌ | **NO** |
| `agentic_stdout_suppressed` | N/A | `False` ❌ | **NO** |

**Result**: Renderer's suppression checks fail, allowing all intermediate text.

---

## Verification Test

### Test 1: Direct Renderer Call (Works)

```python
renderer.on_progress_event('soothe.agentic.loop.started', {'max_iterations': 10})

# Result:
renderer._state.multi_step_active = True ✅
renderer._state.agentic_stdout_suppressed = True ✅
```

**Conclusion**: Renderer logic is correct when event is received.

---

### Test 2: Via EventProcessor (Fails)

```python
processor.process_event({
    'type': 'event',
    'mode': 'custom',
    'data': {
        'type': 'soothe.agentic.loop.started',
        'max_iterations': 10
    }
})

# Result:
processor._state.multi_step_active = True ✅
renderer._state.multi_step_active = False ❌  <-- NOT SET!
renderer._state.agentic_stdout_suppressed = False ❌  <-- NOT SET!
```

**Conclusion**: EventProcessor's early return blocks renderer state update.

---

## Code Flow Analysis

### EventProcessor._handle_custom_event() (Lines 636-697)

```python
def _handle_custom_event(self, data, namespace):
    etype = data.get("type", "")

    # ... other handlers ...

    # Line 681-684: CRITICAL BUG
    if etype == "soothe.agentic.loop.started":
        if data.get("max_iterations", 1) > 1:
            self._state.multi_step_active = True  # Sets processor state
        return  # ⚠️ BUG: Returns before calling renderer!

    # Line 686-692: Plan events (would continue flow)
    # Line 693-697: Would call renderer.on_progress_event()
    elif self._presentation.tier_visible(category, self._verbosity):
        self._renderer.on_progress_event(etype, data, namespace=namespace)
        # ⚠️ BUT NEVER REACHED due to early return above!
```

---

### CliRenderer.on_progress_event() (Lines 314-321)

```python
def on_progress_event(self, event_type, data, namespace=()):
    # Track multi-step state from agentic loop start
    if event_type == "soothe.agentic.loop.started":
        if data.get("max_iterations", 1) > 1:
            self._state.multi_step_active = True  # ⚠️ SHOULD SET THIS
            self._state.agentic_stdout_suppressed = True  # ⚠️ SHOULD SET THIS
        else:
            self._state.agentic_stdout_suppressed = False
            self._state.agentic_final_stdout_emitted = False

    # ... pipeline processing ...
```

**Problem**: This code exists but never runs due to EventProcessor early return.

---

### CliRenderer.on_assistant_text() (Lines 177-180)

```python
def on_assistant_text(self, text, *, is_main, is_streaming):
    if not is_main:
        return

    # HARD BLOCK: No text during multi-step execution
    if self._state.multi_step_active:  # ⚠️ CHECKS FALSE (should be True)
        return
    if self._state.agentic_stdout_suppressed:  # ⚠️ CHECKS FALSE (should be True)
        return

    # ⚠️ FLOWS THROUGH - 800+ lines of intermediate text leak!
    self._state.full_response.append(text)
    sys.stdout.write(text)
    sys.stdout.flush()
```

**Result**: All checks fail → no suppression → text floods output.

---

## Additional Bug: `soothe.cognition.loop_agent.reason` Not Handled

### Renderer Backup Logic (Lines 324-330)

```python
# Backup if loop.started was filtered on the wire:
# suppress after iteration 1+.
if event_type == "soothe.cognition.loop_agent.reason":
    try:
        it = int(data.get("iteration", 0))
    except (TypeError, ValueError):
        it = 0
    if it >= 1 and not self._state.agentic_final_stdout_emitted:
        self._state.agentic_stdout_suppressed = True  # ⚠️ Sets renderer state
```

**Problem**: This sets `agentic_stdout_suppressed` on iteration 1+, but:
1. Never called for iteration 0 (initial event)
2. `multi_step_active` still False
3. First iteration text leaks before backup kicks in

---

## Why Tests Pass But Real Usage Fails

### Unit Tests Test Isolated Components

**PresentationEngine tests**: Test deduplication logic in isolation ✅

**StreamDisplayPipeline tests**: Test action extraction in isolation ✅

**CliRenderer tests**: Test suppression logic in isolation ✅

**Integration tests**: Mock event flow, don't test real EventProcessor → Renderer wiring ❌

### Real Usage Tests Integration

**Real event flow**: EventProcessor → (early return ⚠️) → Renderer never receives event

**Result**: Each component works alone, but integration fails due to early return breaking state sync.

---

## Fix Strategy

### Option 1: Remove Early Return (Recommended)

**Change**:
```python
if etype == "soothe.agentic.loop.started":
    if data.get("max_iterations", 1) > 1:
        self._state.multi_step_active = True
    # return  <-- REMOVE THIS
```

**Impact**: Event continues to line 697 → renderer.on_progress_event() → renderer state set

**Pros**:
- Minimal change (remove 1 line)
- Fixes root cause directly
- Renderer receives all events (can manage own state)

**Cons**:
- Goal echo may appear (but renderer suppresses it anyway)
- Renderer state may duplicate processor state

---

### Option 2: Delegate State to Renderer (Alternative)

**Change**:
```python
if etype == "soothe.agentic.loop.started":
    # Don't set processor state, let renderer handle it
    # self._state.multi_step_active = True  <-- REMOVE
    # return  <-- REMOVE
    # Continue to renderer.on_progress_event()
```

**Impact**: Renderer exclusively manages its own state

**Pros**:
- Clear ownership (renderer owns renderer state)
- No dual state confusion
- Renderer can read processor state via property if needed

**Cons**:
- Processor state unused for multi_step_active
- May need to verify renderer reads correct state

---

### Option 3: Share State Objects (Major Refactor)

**Change**: Use single state object shared between Processor and Renderer

**Impact**: Both read/write same state → always synchronized

**Pros**:
- Eliminates dual state bugs
- Architecturally cleaner

**Cons**:
- Major refactor (changes ProcessorState/CliRendererState)
- Higher risk
- Breaking change for existing code

---

## Recommended Fix: Option 1 (Remove Early Return)

### Rationale

1. **Minimal change**: Remove 1 line (line 684)
2. **Low risk**: Doesn't change state ownership model
3. **Immediate fix**: Renderer receives event → sets own state → suppression works
4. **Tested pattern**: Other events (PLAN_CREATED, etc.) continue to renderer

### Implementation

**File**: `src/soothe/ux/shared/event_processor.py`

**Before**:
```python
if etype == "soothe.agentic.loop.started":
    if data.get("max_iterations", 1) > 1:
        self._state.multi_step_active = True
    return  # ⚠️ REMOVE THIS LINE
```

**After**:
```python
if etype == "soothe.agentic.loop.started":
    if data.get("max_iterations", 1) > 1:
        self._state.multi_step_active = True
    # Continue to renderer.on_progress_event()
```

### Verification

After fix, run test:

```python
processor.process_event({
    'type': 'event',
    'mode': 'custom',
    'data': {
        'type': 'soothe.agentic.loop.started',
        'max_iterations': 10
    }
})

# Expected result:
processor._state.multi_step_active = True ✅
renderer._state.multi_step_active = True ✅  <-- NOW SET!
renderer._state.agentic_stdout_suppressed = True ✅  <-- NOW SET!
```

---

## Secondary Issues

### Issue: Duplicate State Management

**Problem**: Both Processor and Renderer track `multi_step_active`

**Impact**:
- Confusion (which state is authoritative?)
- Risk of future sync bugs

**Long-term fix**: Clarify ownership or share state

---

### Issue: No Clear Multi-Step End

**Problem**: When does `multi_step_active` clear?

**Current**: Only in `ProcessorState.reset_turn()` (line 76) on status idle/stopped

**Renderer**: Never clears its own `multi_step_active` ⚠️

**Fix**: Ensure renderer clears state on `loop.completed` (line 340-346)

---

## Conclusion

**Root Cause**: EventProcessor early return (line 684) blocks renderer from receiving `soothe.agentic.loop.started` event, preventing renderer state synchronization.

**Fix**: Remove early return, let event flow to renderer.on_progress_event().

**Impact**: Renderer sets its own state → suppression checks pass → intermediate text blocked → IG-143 success criteria met.

**Priority**: Critical - fixes 800+ line output explosion, restores core UX functionality.

---

## Test Plan After Fix

1. Run same command: `soothe --no-tui -p "analyze this project arch"`
2. Verify:
   - Line count ≤20 ✅
   - No intermediate file contents ✅
   - Action deduplication working ✅
   - Final answer prominent ✅
3. Run unit tests: All pass ✅
4. Run integration tests: All pass ✅
5. Update IG-143 status: ✅ Completed (verified in real usage)

---

**Report Generated**: 2026-04-08
**Bug ID**: IG-143-STATE-SYNC
**Fix Priority**: P0 (Critical)