# IG-164: AgentLoop Plan Stage Reasoning Display

**Status**: ✅ Completed
**Date**: 2026-04-13
**RFC**: RFC-604 (Reason Phase Robustness), RFC-603 (Reasoning Quality)

---

## Summary

Added display of the AgentLoop plan stage `reasoning` field in both CLI and TUI outputs, providing transparency into the internal technical analysis during agentic execution. Also fixed critical event type mismatch bug that prevented `next_action` from being displayed.

---

## Problems

### Problem 1: Missing reasoning field display

The `PlanResult.reasoning` field (max 500 chars) contains internal technical analysis from the plan phase, but was not being shown to users in CLI or TUI. This limited transparency during agentic execution, especially for complex multi-step goals.

**Example from RFC-604**:
```json
{
  "reasoning": "Need to understand project structure first before analyzing architecture. Start with root exploration, then configuration files, then source code organization."
}
```

### Problem 2: Event type mismatch (CRITICAL BUG)

In `agent_loop.py`, the event was yielded with type `"plan"` (line 181), but `_runner_agentic.py` expected event type `"reason"` (line 294) to create `LoopAgentReasonEvent`. This caused the entire event to be dropped, preventing both `next_action` AND `reasoning` from being displayed in CLI/TUI.

**Root cause**: IG-153 renamed "Reason" → "Plan" in most places, but missed updating the event handler mapping in `_runner_agentic.py`.

---

## Solutions

### Solution 1: Add reasoning to event data

Updated the "plan" event emission to include the reasoning field:

```python
yield (
    "plan",
    {
        "iteration": state.iteration,
        "status": plan_result.status,
        "progress": plan_result.goal_progress,
        "confidence": plan_result.confidence,
        "next_action": plan_result.next_action,
        "reasoning": plan_result.reasoning,  # NEW
        "plan_action": plan_result.plan_action,
    },
)
```

### Solution 2: Fix event type mismatch (CRITICAL)

Fixed the handler in `_runner_agentic.py` to match the correct event type:

```python
# BEFORE (WRONG - event was dropped)
elif event_type == "reason":  # ❌ No such event from AgentLoop
    yield _custom(LoopAgentReasonEvent(...))

# AFTER (CORRECT)
elif event_type == "plan":  # ✅ Matches agent_loop.py yield
    yield _custom(LoopAgentReasonEvent(...))
```

This fix ensures the event reaches the UI layer and both `next_action` and `reasoning` are displayed.

### 2. Update event schema (events.py)

Added reasoning field to `LoopAgentReasonEvent`:

```python
class LoopAgentReasonEvent(ProtocolEvent):
    reasoning: str  # Internal technical analysis (max 500 chars)
```

### 3. Add CLI formatting (formatter.py)

New `format_reasoning()` function displays reasoning with "💭 Reasoning:" prefix:

```python
def format_reasoning(reasoning: str, ...) -> DisplayLine:
    content = f"💭 Reasoning: {reasoning}"
    return DisplayLine(
        level=3,  # Subordinate to next_action
        content=content,
        icon="•",
        indent=indent_for_level(3),
    )
```

### 4. Update CLI pipeline (pipeline.py)

Modified `_on_loop_agent_reason()` to emit reasoning line after next_action:

```python
lines = [format_judgement(action_text, action)]

# Add reasoning if present
reasoning = event.get("reasoning", "").strip()
if reasoning:
    lines.append(format_reasoning(reasoning))

return lines
```

### 5. Update TUI renderer (renderer.py)

Added reasoning display after next_action line:

```python
# Show next_action
action_line = Text()
action_line.append(icon + " ", style=color)
action_line.append(f"🌀 {next_action}")
self._on_panel_write(action_line)

# Show reasoning if present
reasoning = str(payload.get("reasoning", "")).strip()
if reasoning:
    reasoning_line = Text()
    reasoning_line.append("  • ", style="dim")
    reasoning_line.append("💭 Reasoning: ", style="dim italic")
    reasoning_line.append(reasoning, style="dim")
    self._on_panel_write(reasoning_line)
```

---

## Implementation

**Files Modified**:
- `src/soothe/cognition/agent_loop/agent_loop.py` (event emission)
- `src/soothe/cognition/agent_loop/events.py` (schema)
- `src/soothe/core/runner/_runner_agentic.py` (event handler - CRITICAL FIX)
- `src/soothe/ux/cli/stream/formatter.py` (formatting)
- `src/soothe/ux/cli/stream/pipeline.py` (CLI handler)
- `src/soothe/ux/tui/renderer.py` (TUI handler)

**Changes**:
- Added `reasoning` field to event data and schema
- **CRITICAL**: Fixed event type mismatch ("plan" vs "reason")
- Created `format_reasoning()` formatter for CLI
- Updated both CLI and TUI to display reasoning after next_action
- Used dim styling to subordinate reasoning to next_action

---

## Verification

All checks passed:
- ✅ Format check: PASSED
- ✅ Linting: PASSED
- ✅ Unit tests: PASSED (1592 tests)

---

## Design Decisions

### 1. Styling hierarchy

Reasoning is displayed with:
- Level 3 indentation (vs level 2 for next_action)
- Dim/italic styling (less prominent than next_action)
- "💭 Reasoning:" prefix for clarity

This maintains focus on next_action while providing optional transparency.

### 2. Conditional display

Reasoning is only shown if:
- Field is present in event
- Field is non-empty after stripping

This avoids cluttering simple goals with empty reasoning.

### 3. Max 500 chars

Reasoning is capped at 500 chars in schema for token efficiency. No truncation needed at display level.

---

## Impact

**Before (BUG - event dropped)**:
```
🚩 analyze this project arch design
○ ⏩ Explore project root structure
  |__ Done (2.1s)
```
**next_action was NOT shown** due to event type mismatch bug!

**After (FIXED - both next_action and reasoning shown)**:
```
🚩 analyze this project arch design
→ 🌀 Explore project root structure to identify key directories
  • 💭 Reasoning: Need to understand project structure first before analyzing architecture. Start with root exploration, then configuration files.
○ ⏩ Explore project root structure
  |__ Done (2.1s)
```

Both `next_action` and `reasoning` now display correctly in CLI and TUI.

**Before** (agentic execution):
```
🚩 analyze this project arch design
→ 🌀 Explore project root structure to identify key directories
○ ⏩ Explore project root structure
  |__ Done (2.1s)
```

**After** (with reasoning):
```
🚩 analyze this project arch design
→ 🌀 Explore project root structure to identify key directories
  • 💭 Reasoning: Need to understand project structure first before analyzing architecture. Start with root exploration, then configuration files.
○ ⏩ Explore project root structure
  |__ Done (2.1s)
```

---

## Related

- RFC-604: Reason Phase Robustness
- IG-152: Fix next_action truncation
- IG-160: Display next_action in TUI
- IG-153: ReAct to Plan-Execute renaming

---

## Future Work

- Consider showing reasoning only in verbose/detailed modes
- Add reasoning to plan tree widget (if applicable)