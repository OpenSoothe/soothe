# CLI Display Architecture Refactoring: Condensed Action Summary

**Date:** 2026-04-08
**Status:** Draft - Pending Review
**Scope:** UX layer refactoring for cleaner multi-step execution output

---

## Problem Statement

Current CLI output during multi-step agent execution shows noisy intermediate LLM responses, making it difficult for users to track progress and find the final answer.

**Symptoms observed in `full_case.log`:**

1. **Intermediate LLM text floods output** - Full markdown tables and analysis (50+ lines) appear during each iteration
2. **Repeated reasoning lines** - "→ Working toward the goal (80% sure)" appears 8+ times identically
3. **Duplicate step headers** - Same step description repeats throughout execution
4. **Final answer buried** - Result lost in repeated intermediate text, users must scroll/search

**User impact:**
- Cannot see clear progress narrative during long-running tasks
- Final answer obscured by noise
- Difficult to debug when output is cluttered
- Poor user experience compared to clean TUI panel display

---

## Design Goals

1. **Show meaningful action summaries** - Replace generic reasoning with specific action descriptions
2. **Suppress intermediate LLM text** - No markdown dumps during multi-step execution
3. **Eliminate duplicate headers** - Deduplicate repeated reasoning/step lines
4. **Highlight final answer** - Prominent display at completion
5. **Maintain transparency** - Users understand what AI is doing each iteration

---

## Architecture

### Component Stack

```
Daemon Event Stream
    ↓
EventProcessor (shared/event_processor.py)
    ↓ [routes events, manages multi_step_active state]
StreamDisplayPipeline (cli/stream/pipeline.py)
    ↓ [extracts soothe_next_action/user_summary, formats DisplayLine]
CliRenderer (cli/renderer.py)
    ↓ [suppresses intermediate text, writes stderr]
Terminal Output (clean action narrative)
```

### Data Flow

1. Daemon emits `loop_agent.reason` events with action metadata
2. EventProcessor routes to StreamDisplayPipeline (no text suppression in processor)
3. Pipeline extracts `soothe_next_action` or `user_summary`, deduplicates
4. Renderer hard-suppresses `on_assistant_text()` during multi-step
5. Final answer emitted from `loop.completed` event's `final_stdout_message`

---

## Component Changes

### 1. PresentationEngine (shared/presentation_engine.py)

**Add action deduplication method:**

```python
def should_emit_action(
    self,
    *,
    action_text: str,
    now_s: float | None = None,
) -> bool:
    """Deduplicate repeated action summaries within 5s window.

    Args:
        action_text: Action summary text (may include confidence).
        now_s: Optional timestamp (defaults to monotonic time).

    Returns:
        True if action should be emitted, False if duplicate.
    """
    normalized = self._normalize_action(action_text)
    now = now_s if now_s is not None else time.monotonic()

    # Dedup identical actions within 5s
    if normalized == self._state.last_action_text:
        if (now - self._state.last_action_time) < 5.0:
            return False

    # Update state
    self._state.last_action_text = normalized
    self._state.last_action_time = now
    return True

def _normalize_action(self, text: str) -> str:
    """Strip confidence and whitespace for comparison."""
    lowered = text.lower().strip()
    # Remove "(XX% confident)" suffix
    lowered = re.sub(r"\(\d+%\s+confident\)", "", lowered)
    return re.sub(r"\s+", " ", lowered)
```

**Update PresentationState dataclass:**

```python
@dataclass
class PresentationState:
    # Existing fields...
    last_reason_key: str = ""
    last_reason_at_s: float = 0.0
    last_reason_by_step: dict[str, float] | None = None
    final_answer_locked: bool = False

    # NEW: Action dedup tracking
    last_action_text: str = ""
    last_action_time: float = 0.0
```

---

### 2. StreamDisplayPipeline (cli/stream/pipeline.py)

**Modify `_on_loop_agent_reason()` to extract and format actions:**

```python
def _on_loop_agent_reason(self, event: dict[str, Any]) -> list[DisplayLine]:
    """Handle Layer 2 Reason progress with condensed action summary."""
    status = event.get("status", "")
    confidence = event.get("confidence", 0.0)

    # Extract action summary (priority order)
    action_text = (
        event.get("user_summary", "").strip() or
        event.get("soothe_next_action", "").strip() or
        self._derive_action_from_status(status)
    )

    if not action_text:
        return []

    # Format with confidence
    confidence_pct = confidence if confidence > 0 else 0.8
    formatted = f"{action_text} ({confidence_pct:.0%} sure)"

    # Deduplicate
    step_id = str(event.get("step_id", "") or event.get("iteration", "") or "")
    if not self._presentation.should_emit_action(action_text=formatted, now_s=time.time()):
        return []

    # Determine action type
    action = "complete" if status == "done" else "continue"

    return [
        format_judgement(
            formatted,
            action,
            namespace=self._current_namespace,
            verbosity_tier=self._verbosity_tier,
        )
    ]

def _derive_action_from_status(self, status: str) -> str:
    """Fallback action text when metadata missing.

    Args:
        status: Reason event status field.

    Returns:
        Human-readable action description.
    """
    if status == "done":
        return "Completing final analysis"
    if status == "replan":
        return "Trying alternative approach"
    if status == "working":
        return "Processing next step"
    return "Continuing work"
```

---

### 3. CliRenderer (cli/renderer.py)

**Strengthen `on_assistant_text()` suppression:**

```python
def on_assistant_text(
    self,
    text: str,
    *,
    is_main: bool,
    is_streaming: bool,
) -> None:
    """Write assistant text to stdout.

    HARD SUPPRESS during multi-step execution to prevent intermediate
    LLM response text from flooding output.

    Args:
        text: Text content to display.
        is_main: True if from main agent.
        is_streaming: True if partial chunk.
    """
    if not is_main:
        return  # Subagent text not shown in CLI headless mode

    # HARD BLOCK: No text during multi-step execution
    if self._state.multi_step_active:
        return
    if self._state.agentic_stdout_suppressed and not self._state.agentic_final_stdout_emitted:
        return

    # Emit only on final iteration (after flags cleared)
    self._state.full_response.append(text)

    if self._state.stderr_just_written:
        self._state.stderr_just_written = False

    sys.stdout.write(text)
    sys.stdout.flush()
    self._state.needs_stdout_newline = True
    self._state.stderr_blank_before_next_icon_block = True
```

**No changes needed to:**
- `on_progress_event()` - Already delegates to pipeline correctly
- `on_plan_created()`, `on_plan_step_started()`, `on_plan_step_completed()` - Existing behavior works well
- `on_tool_call()`, `on_tool_result()` - Existing behavior works well

---

### 4. EventProcessor (shared/event_processor.py)

**No changes needed - existing suppression already works:**

The processor already:
- Tracks `multi_step_active` state correctly
- Suppresses assistant text during multi-step (via `PresentationEngine.final_answer_locked`)
- Handles `loop.completed` event to emit `final_stdout_message`

The refactoring improves suppression by moving hard block to renderer level, ensuring no text leaks through regardless of message source.

---

## Error Handling

### Missing Action Metadata

**Scenario:** `loop_agent.reason` event lacks `soothe_next_action` or `user_summary`.

**Fallback chain:**
1. Try `user_summary` field
2. Try `soothe_next_action` field
3. Derive from `status` field using `_derive_action_from_status()`
4. If all missing: Return empty list (no display)

**Why:** Avoid generic "Working..." text; better to skip than emit noise.

### Missing Confidence Value

**Scenario:** Event has no `confidence` field or value is 0.

**Fallback:**
- Default to 80% (0.8) if missing or zero
- Always format as integer percentage: `"{action_text} (80% confident)"`

**Why:** Confidence percentage is optional; don't block display if missing.

### Event Order Anomalies

**Scenario:** `loop.completed` arrives before final `reason` event.

**Handling:**
- Emit `final_stdout_message` from `loop.completed` payload
- If no `final_stdout_message`, use existing fallback: accumulated response on `on_turn_end()`
- Reason events still processed but don't interfere with final answer

**Why:** Final answer always appears regardless of event ordering quirks.

---

## Testing Strategy

### Unit Tests

**File:** `tests/unit/test_cli_stream_display_pipeline.py`

**New tests:**
1. `test_on_loop_agent_reason_extracts_user_summary()` - Verify extraction priority
2. `test_on_loop_agent_reason_extracts_soothe_next_action()` - Verify fallback
3. `test_on_loop_agent_reason_derives_from_status()` - Verify status fallback logic
4. `test_on_loop_agent_reason_deduplicates_repeated_actions()` - Verify 5s window dedup
5. `test_on_loop_agent_reason_formats_confidence_percentage()` - Verify formatting
6. `test_on_loop_agent_reason_returns_empty_when_missing_all_fields()` - Verify graceful skip

**File:** `tests/unit/test_presentation_engine.py`

**New tests:**
1. `test_should_emit_action_deduplicates_identical_text()` - Verify dedup logic
2. `test_should_emit_action_normalizes_confidence_suffix()` - Verify stripping "(XX% confident)"
3. `test_should_emit_action_respects_5s_window()` - Verify time-based dedup
4. `test_normalize_action_removes_whitespace()` - Verify normalization

**File:** `tests/unit/test_cli_renderer.py`

**New tests:**
1. `test_on_assistant_text_hard_suppress_multi_step_active()` - Verify no text leaks
2. `test_on_assistant_text_emits_after_multi_step_clears()` - Verify final answer appears
3. `test_on_assistant_text_suppresses_agentic_stdout()` - Verify agentic loop suppression

### Integration Test

**File:** `tests/integration/test_multi_step_display_clean_output.py`

**Scenario:** Run agent with multi-step execution (similar to log case)

**Verify:**
- Output contains ONLY: step headers (○), step completions (●), action summaries (→), final answer
- NO intermediate markdown/analysis text appears
- NO duplicate reasoning lines
- NO duplicate step headers within 5s window
- Final answer appears prominently at completion
- Output line count ≤ 20 lines for 8-step execution (vs 100+ in current log)

**Test command:**
```bash
soothe --no-tui -p "analyze the project structure"
# Capture output, verify no intermediate text, count lines
```

---

## Implementation Sequence

**Phase 1: Core Logic (Priority: High)**

1. Add `should_emit_action()` to `PresentationEngine`
2. Update `PresentationState` dataclass with action tracking fields
3. Modify `_on_loop_agent_reason()` in `StreamDisplayPipeline`
4. Add `_derive_action_from_status()` helper method

**Phase 2: Suppression Enforcement (Priority: High)**

5. Strengthen `on_assistant_text()` in `CliRenderer` with hard block
6. Verify existing `EventProcessor` suppression works correctly

**Phase 3: Testing (Priority: High)**

7. Write unit tests for pipeline action extraction
8. Write unit tests for presentation engine dedup
9. Write unit tests for renderer suppression
10. Write integration test for clean output verification

**Phase 4: Validation (Priority: Medium)**

11. Run full verification suite: `./scripts/verify_finally.sh`
12. Manual testing with various multi-step scenarios
13. Compare output to current log case for improvement

---

## Migration Strategy

**No backward compatibility concerns:**

- All changes are internal to UX layer
- No API changes, no protocol changes
- Event schemas unchanged (just better utilization of existing fields)
- Existing CLI behavior preserved for single-step execution
- TUI renderer unaffected (already has good display)

**Deployment:**

- Merge as single PR after all tests pass
- Update implementation guide in `docs/impl/`
- No user-facing documentation changes needed (internal improvement)

---

## Expected Output Transformation

### Before (Current)

```
→ Working toward the goal (80% sure)
○ Use file and shell tools in the workspace to gather facts and deliver a direct result; context: analyze the project structure
**Project Structure Analysis: Soothe**

| Metric | Value |
|--------|-------|
| **Project** | Soothe v0.2.3 |
| **Type** | Python AI orchestration framework |
| **Python Files** |  336 source +  139 test files |
| **License** | MIT |

**Key Directories:**
- `src/soothe/` - Main source with  17 modules:
   - `core/` - Agent factory & runner
   ...[50+ lines of markdown]...

● Use file and shell tools in the workspace... [9 tools] (33.2s)
→ Working toward the goal (80% sure)
○ Use file and shell tools...
[Duplicate markdown dump]
● Use file and shell tools... (14.6s)
[Repeats 8+ times with flooding]
```

### After (Approach B)

```
● analyze the project structure
○ Gathering files and analyzing structure (80% sure)
⚙ ls, glob, grep running...
✓ Tool results received (33.2s)
● Gathering files and analyzing structure [9 tools] (33.2s)
○ Counting Python files and categorizing (85% sure)
⚙ find, wc running...
✓ Tool results received (14.6s)
● Counting Python files and categorizing (14.6s)
○ Building summary table and directory map (90% sure)
⚙ file operations running...
✓ Tool results received (17.8s)
● Building summary table and directory map [3 tools] (17.8s)
○ Refining architecture details (90% sure)
● Refining architecture details (15.3s)
○ Preparing final comprehensive report (95% sure)
✓ Complete: Soothe v0.2.3 is a Python AI orchestration framework with 475 total files (336 source, 139 tests), organized into 17 core modules with protocol-driven architecture
●  (complete, 8 steps)
```

**Improvement metrics:**
- Output lines: 100+ → ~15-20 lines (80% reduction)
- Duplicate reasoning: 8+ occurrences → 0 duplicates
- Intermediate text: Full markdown floods → Complete suppression
- Action transparency: Generic "working" → Specific per-iteration actions
- Final answer prominence: Buried → Last line, clearly marked

---

## Open Questions (Resolved)

**Q1: Should we show tool call details during multi-step?**

**Decision:** Yes, existing behavior is good. Keep tool calls (⚙) and results (✓) visible - they provide concrete progress indicators without flooding output.

**Q2: How to handle missing `soothe_next_action` in all iterations?**

**Decision:** Fallback to status-derived action. If status also missing, skip emission (don't emit generic "Working..."). Better to have gaps than noise.

**Q3: Should TUI also use this approach?**

**Decision:** No, TUI already has good display with panel separation. This refactoring is CLI-only. TUI renderer unchanged.

**Q4: Confidence percentage - required or optional?**

**Decision:** Optional. Default to 80% if missing. Don't block display if confidence absent.

---

## Success Criteria

1. **No intermediate LLM text** during multi-step execution
2. **No duplicate reasoning lines** within 5s window
3. **Action summaries present** for ≥ 80% of iterations (fallback handling)
4. **Final answer prominent** at completion
5. **Output line count ≤ 20** for typical 8-step execution
6. **All existing tests pass** after changes
7. **Integration test confirms** clean output transformation

---

## References

- Current log case: `full_case.log` (attached)
- Architecture: RFC-000, RFC-001
- Event catalog: `src/soothe/core/event_catalog.py`
- Loop agent events: `src/soothe/cognition/agent_loop/events.py`
- Verbosity tiers: RFC-0020 (implied)

---

## Next Steps

1. **User review** - Approve this design draft
2. **Implementation** - Follow sequence in Section "Implementation Sequence"
3. **RFC generation** - If formal specification needed (optional for internal refactor)
4. **Implementation guide** - Create IG-XXX tracking document

---

**End of Design Draft**