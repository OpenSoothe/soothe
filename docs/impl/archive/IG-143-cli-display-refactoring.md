# IG-143: CLI Display Architecture Refactoring - Condensed Action Summary

**Implementation Guide ID:** IG-143
**Date:** 2026-04-08
**Status:** ✅ Completed
**Design Reference:** `docs/drafts/2026-04-08-cli-display-refactoring-design.md`
**Priority:** High - Improves core UX for multi-step execution

---

## Overview

Refactor CLI output during multi-step agent execution to show clean, meaningful action summaries instead of flooding with intermediate LLM responses.

**Goals:**
- Suppress intermediate LLM markdown/analysis text
- Show specific action descriptions per iteration
- Deduplicate repeated reasoning/step headers
- Highlight final answer prominently

**Scope:** UX layer only (CLI renderer, stream pipeline, presentation engine)

---

## Success Criteria

1. ✅ No intermediate LLM text during multi-step execution
2. ✅ No duplicate reasoning lines within 5s window
3. ✅ Action summaries present for ≥ 80% of iterations
4. ✅ Final answer prominent at completion
5. ✅ Output line count ≤ 20 for typical 8-step execution (vs 100+ currently)
6. ✅ All existing tests pass
7. ✅ Integration test confirms clean output

---

## Implementation Steps

### Phase 1: Core Logic (PresentationEngine + Pipeline)

#### Step 1.1: Add Action Deduplication to PresentationEngine

**File:** `src/soothe/ux/shared/presentation_engine.py`

**Changes:**
1. Add tracking fields to `PresentationState`:
   ```python
   last_action_text: str = ""
   last_action_time: float = 0.0
   ```

2. Add `should_emit_action()` method (see design draft for implementation)

3. Add `_normalize_action()` helper method (see design draft)

**Testing:** Run existing tests to verify no regression, then add new unit tests in Phase 3.

---

#### Step 1.2: Modify StreamDisplayPipeline to Extract Actions

**File:** `src/soothe/ux/cli/stream/pipeline.py`

**Changes:**
1. Modify `_on_loop_agent_reason()`:
   - Extract action text: `user_summary` → `soothe_next_action` → status fallback
   - Format with confidence percentage
   - Call `should_emit_action()` for deduplication
   - Return formatted `DisplayLine` via `format_judgement()`

2. Add `_derive_action_from_status()` helper:
   - Map status values to action descriptions
   - Handle missing/unknown status gracefully

**Testing:** Verify action extraction with various event payloads.

---

### Phase 2: Suppression Enforcement (Renderer)

#### Step 2.1: Strengthen Assistant Text Suppression in CliRenderer

**File:** `src/soothe/ux/cli/renderer.py`

**Changes:**
Modify `on_assistant_text()` method:
- Hard suppress when `multi_step_active=True` (no conditional, just return)
- Hard suppress when `agentic_stdout_suppressed=True` (until final flag clears)
- Remove existing partial suppression logic

**Rationale:** Ensures no intermediate text leaks regardless of message source.

**Testing:** Verify no text appears during multi-step execution.

---

### Phase 3: Unit Testing

#### Step 3.1: PresentationEngine Tests

**File:** `tests/unit/test_presentation_engine.py`

**Add tests:**
```python
def test_should_emit_action_deduplicates_identical_text():
    """Verify dedup of same action within 5s."""

def test_should_emit_action_normalizes_confidence():
    """Verify stripping '(XX% sure)' suffix."""

def test_should_emit_action_respects_5s_window():
    """Verify time-based deduplication."""

def test_normalize_action_removes_whitespace():
    """Verify text normalization."""
```

---

#### Step 3.2: StreamDisplayPipeline Tests

**File:** `tests/unit/test_cli_stream_display_pipeline.py`

**Add tests:**
```python
def test_on_loop_agent_reason_extracts_user_summary():
    """Verify user_summary extraction priority."""

def test_on_loop_agent_reason_extracts_soothe_next_action():
    """Verify soothe_next_action fallback."""

def test_on_loop_agent_reason_derives_from_status():
    """Verify status → action fallback logic."""

def test_on_loop_agent_reason_deduplicates_repeated():
    """Verify 5s dedup window."""

def test_on_loop_agent_reason_formats_confidence():
    """Verify percentage formatting."""

def test_on_loop_agent_reason_returns_empty_when_missing():
    """Verify graceful skip when all fields absent."""
```

---

#### Step 3.3: CliRenderer Tests

**File:** `tests/unit/test_cli_renderer.py`

**Add tests:**
```python
def test_on_assistant_text_hard_suppress_multi_step():
    """Verify no text leaks during multi_step_active."""

def test_on_assistant_text_emits_after_clear():
    """Verify text appears after multi_step clears."""

def test_on_assistant_text_suppresses_agentic_loop():
    """Verify agentic_stdout_suppressed blocking."""
```

---

### Phase 4: Integration Testing

#### Step 4.1: Manual Testing

**Commands to run:**
```bash
# Multi-step execution
soothe --no-tui -p "analyze the project structure"

# Long-running multi-step
soothe --no-tui -p "write a comprehensive test suite for the authentication module"

# Single-step (should work as before)
soothe --no-tui -p "what is the version number?"
```

**Verify:**
- Output clean and concise (≤ 20 lines for 8-step)
- Action summaries meaningful and specific
- No duplicate reasoning lines
- No intermediate markdown text
- Final answer prominent

---

#### Step 4.2: Integration Test File

**File:** `tests/integration/test_multi_step_display_clean_output.py`

**Test scenario:**
```python
def test_multi_step_execution_shows_clean_output():
    """Verify condensed action summary display."""
    # Run agent with multi-step task
    # Capture CLI output
    # Verify:
    # - No intermediate markdown text
    # - No duplicate headers
    # - Action summaries present
    # - Final answer visible
    # - Line count reasonable
```

---

### Phase 5: Validation

#### Step 5.1: Run Full Verification Suite

**Command:**
```bash
./scripts/verify_finally.sh
```

**Requirements:**
- Format check passes
- Lint check passes (zero errors)
- All unit tests pass (900+ tests)
- Integration tests pass

---

#### Step 5.2: Compare with Original Log Case

**Verification:**
- Run same command as `full_case.log`: `soothe --no-tui -p "analyze the project structure"`
- Capture new output
- Compare line counts: original 100+ vs target ≤20
- Verify no intermediate text
- Verify clean action narrative

---

## Code Changes Summary

| Component | File | Changes | Lines Modified |
|-----------|------|---------|----------------|
| PresentationEngine | `ux/shared/presentation_engine.py` | Add dedup method + state fields | ~30 lines |
| StreamDisplayPipeline | `ux/cli/stream/pipeline.py` | Modify reason handler, add fallback | ~40 lines |
| CliRenderer | `ux/cli/renderer.py` | Strengthen suppression | ~10 lines |
| **Total Implementation** | | | **~80 lines** |

---

## Testing Summary

| Test Type | File | Tests Added | Purpose |
|-----------|------|-------------|---------|
| Unit | `test_presentation_engine.py` | 4 | Dedup logic validation |
| Unit | `test_cli_stream_display_pipeline.py` | 6 | Action extraction validation |
| Unit | `test_cli_renderer.py` | 3 | Suppression validation |
| Integration | `test_multi_step_display_clean_output.py` | 1 | End-to-end validation |
| **Total Tests** | | **14** | |

---

## Implementation Checklist

### Phase 1: Core Logic
- [x] Add action tracking to `PresentationState`
- [x] Implement `should_emit_action()` in `PresentationEngine`
- [x] Implement `_normalize_action()` helper
- [x] Modify `_on_loop_agent_reason()` in `StreamDisplayPipeline`
- [x] Implement `_derive_action_from_status()` helper

### Phase 2: Suppression
- [x] Strengthen `on_assistant_text()` in `CliRenderer`
- [x] Verify suppression logic with manual test

### Phase 3: Unit Tests
- [x] Add PresentationEngine dedup tests (5 tests) ✅
- [x] Add Pipeline action extraction tests (9 tests) ✅
- [x] Add Renderer suppression tests (7 tests) ✅
- [x] Run unit tests to verify all pass ✅

### Phase 4: Integration
- [x] Manual testing with multi-step scenarios
- [x] Compare with original log case
- [x] Verify clean output transformation

### Phase 5: Validation
- [x] Run `./scripts/verify_finally.sh` ✅
- [x] Verify format/lint/tests all pass ✅
- [x] Document improvement metrics (line count reduction)

---

## Notes

**No backward compatibility concerns:**
- All changes internal to UX layer
- No protocol changes, no API changes
- Single-step execution unaffected
- TUI renderer unchanged

**Implementation time estimate:**
- Phase 1-2 (Core + Suppression): 2-3 hours
- Phase 3 (Unit tests): 2 hours
- Phase 4-5 (Integration + Validation): 1-2 hours
- **Total: ~6-7 hours**

**Dependencies:**
- No external dependencies
- Uses existing event fields (`user_summary`, `soothe_next_action`, `confidence`)
- Compatible with current daemon event stream

---

## Completion Criteria

Mark IG-143 as **Completed** when:
1. All checklist items checked ✅
2. All tests pass (unit + integration) ✅
3. Manual testing confirms clean output ✅
4. Verification script passes ✅
5. Improvement metrics documented ✅

**Update status:** Change IG-143 header from "Ready for Implementation" → "✅ Completed"

---

## References

- Design Draft: `docs/drafts/2026-04-08-cli-display-refactoring-design.md`
- RFC-0020: CLI Stream Display Pipeline (implied)
- Event Catalog: `src/soothe/core/event_catalog.py`
- Loop Agent Events: `src/soothe/cognition/agent_loop/events.py`

---

**Implementation Guide Complete - Ready to Execute**