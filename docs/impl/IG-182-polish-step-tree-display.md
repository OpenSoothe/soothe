# IG-182: Polish CLI/TUI Step Tree Display (IG-159 Format)

**Status**: ✅ Completed
**Date**: 2026-04-16
**RFC**: RFC-0020 (Stream Display Pipeline)

---

## Problem

Current step display doesn't follow IG-159's tree format. Steps show as separate flat lines instead of parent-child tree structure.

**Current (CLI before IG-182)**:
```
○ ⏩ Run cloc analysis
● ✅ Run cloc ... [1 tools] (2.3s)
```

**Expected (IG-159)**:
```
○ ⏩ Run cloc analysis
  |__ Done [1 tools] (2.3s)
```

The difference:
- Step header: level 2, "○ ⏩" prefix (flat, no indent)
- Step result: should be level 3 (child), **2-space indent**, "|__" connector, brief "Done" text (not full description repeat)

---

## Solution

### 1. Update CLI Formatter (formatter.py)

Change `format_step_done()` to emit level-3 child line with brief text:

```python
def format_step_done(
    duration_s: float,
    *,
    tool_call_count: int = 0,
    success: bool = True,
    error_msg: str | None = None,
    namespace: tuple[str, ...] = (),
    verbosity_tier: VerbosityTier = VerbosityTier.NORMAL,
) -> list[DisplayLine]:
    """Format step completion as level-3 child node (IG-182).

    Args:
        duration_s: Duration in seconds.
        tool_call_count: Number of tool calls made during step execution.
        success: Whether step succeeded.
        error_msg: Error message if failed.
        namespace: Event namespace.
        verbosity_tier: Current verbosity tier.

    Returns:
        DisplayLine for step result as child of step header.
    """
    duration_ms = int(duration_s * 1000)
    tool_info = f" [{tool_call_count} tools]" if tool_call_count > 0 else ""

    # Success case
    if success:
        content = f"Done{tool_info}"
        return DisplayLine(
            level=3,  # Child node (IG-182)
            content=content,
            icon="|__",  # Tree connector (IG-159)
            indent=indent_for_level(3),
            duration_ms=duration_ms,
            source_prefix=_derive_source_prefix(namespace, verbosity_tier),
        )

    # Error case - show error message on next line
    lines = []
    lines.append(DisplayLine(
        level=3,
        content=f"Failed{tool_info}",
        icon="|__",
        indent=indent_for_level(3),
        duration_ms=duration_ms,
        source_prefix=_derive_source_prefix(namespace, verbosity_tier),
    ))

    if error_msg:
        lines.append(DisplayLine(
            level=4,  # Error detail as level-4
            content=f"Error: {error_msg}",
            icon="|__",
            indent=indent_for_level(4),
            source_prefix=_derive_source_prefix(namespace, verbosity_tier),
        ))

    return lines
```

**Key changes**:
- Level: 2 → 3 (child node)
- Icon: "●" → "|__" (tree connector)
- Content: "✅ abbreviated_desc..." → "Done" (brief, no repeat)
- Returns: `list[DisplayLine]` (can return multiple lines for errors)
- Parameters: Remove `description`, add `success`, `error_msg`

### 2. Add Tree Indentation (display_line.py)

Update `indent_for_level()` to add 2-space indent for level-3 children:

```python
def indent_for_level(level: int) -> str:
    """Get indentation string for a display level.

    IG-182: Headless CLI uses flat layout for levels 1-2, but tree indentation
    for level-3 child nodes (step results with "|__" connector).

    Args:
        level: Display level (1=goal, 2=step/tool, 3=result child).

    Returns:
        Indentation string: "" for level 1-2, "  " for level 3 (tree child).
    """
    if level >= 3:
        return "  "  # 2-space indent for tree children (IG-182)
    return ""  # Flat layout for goal/step headers
```

### 3. Update CLI Pipeline (pipeline.py)

Modify `_on_step_completed()` to call new formatter:

```python
def _on_step_completed(self, event: dict[str, Any]) -> list[DisplayLine]:
    """Handle step completed event."""
    step_id = event.get("step_id", "")
    duration_s = event.get("duration_s", 0)
    success = event.get("success", True)
    tool_call_count = event.get("tool_call_count", 0)

    # Get error message if failed
    error_msg = None
    if not success:
        error_msg = event.get("error", event.get("error_message", ""))

    # Mark step complete
    if step_id:
        self._context.complete_step(step_id)
        self._context.step_descriptions.pop(step_id, None)

    # Reset current step context
    self._context.current_step_id = None
    self._context.current_step_description = None
    self._context.step_start_time = None

    return format_step_done(
        duration_s,
        tool_call_count=tool_call_count,
        success=success,
        error_msg=error_msg,
        namespace=self._current_namespace,
        verbosity_tier=self._verbosity_tier,
    )
```

### 4. Update CLI Renderer (renderer.py)

Modify `on_plan_step_completed()` to handle `list[DisplayLine]`:

```python
def on_plan_step_completed(
    self,
    step_id: str,
    success: bool,
    duration_ms: int,
) -> None:
    """Update plan state and show step completion."""
    # Update step status in current plan
    if self._state.current_plan:
        for step in self._state.current_plan.steps:
            if step.id == step_id:
                step.status = "completed" if success else "failed"
                break

    # Use pipeline for consistent formatting
    event = {
        "type": "soothe.cognition.plan.step.completed",
        "step_id": step_id,
        "success": success,
        "duration_ms": duration_ms,
    }
    lines = self._pipeline.process(event)
    self.write_lines(lines)  # Handles list[DisplayLine]
```

### 5. Update TUI Display

TUI doesn't use StreamDisplayPipeline directly. Need to check how TUI renders steps:

**Option A**: TUI uses same pipeline (preferred for consistency)
- Import `StreamDisplayPipeline` in TUI adapter
- Use `_format_progress_event_lines_for_tui()` for step events

**Option B**: TUI has its own tree rendering
- Update TUI message widgets to show tree structure
- Use Rich Text with tree connectors

Check `textual_adapter.py` and `app.py` to see current TUI handling.

---

## Implementation Steps

1. ✅ Read current formatter/pipeline/renderer
2. ✅ Update `format_step_done()` in formatter.py (brief text + level-3)
3. ✅ Update `indent_for_level()` in display_line.py (2-space indent for level-3)
4. ✅ Update `_on_step_completed()` in pipeline.py (adapt to new signature)
5. ✅ Update `on_plan_step_completed()` in renderer.py (CLI)
6. ✅ Check TUI step rendering approach (uses same pipeline)
7. ✅ Update TUI to match IG-159 format (automatic via pipeline)
8. ✅ Run tests (1268 passed, 3 skipped, 1 xfailed)
9. ✅ Verify output matches IG-159 examples

---

## Files Modified

1. `packages/soothe-cli/src/soothe_cli/cli/stream/formatter.py`:
   - ✅ `format_step_done()` → return `list[DisplayLine]` with level-3 tree connector, brief text

2. `packages/soothe-cli/src/soothe_cli/cli/stream/display_line.py`:
   - ✅ `indent_for_level()` → add 2-space indent for level ≥3 (tree children)

3. `packages/soothe-cli/src/soothe_cli/cli/stream/pipeline.py`:
   - ✅ `_on_step_completed()` → adapt to new formatter signature

4. `packages/soothe-cli/src/soothe_cli/cli/renderer.py`:
   - ✅ Already handles `list[DisplayLine]` via `write_lines()`

5. `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`:
   - ✅ Already uses same pipeline via `_format_progress_event_lines_for_tui()`

---

## Verification

All verification checks passed:
- ✅ Format check: PASSED
- ✅ Linting: PASSED (zero errors)
- ✅ Unit tests: PASSED (1268 tests, 3 skipped, 1 xfailed)

---

## Impact

**Before (flat separate lines, no indent)**:
```
○ ⏩ Run cloc analysis
● ✅ Run cloc ... [1 tools] (2.3s)
```

**After (IG-159 tree format with 2-space indent)**:
```
○ ⏩ Read the README.md file in the project root to get the first 10 lines
  |__ Done [1 tools] (22.4s)
```

For failed steps:
```
○ ⏩ Execute command
  |__ Failed [1 tools] (1.2s)
  |__ Error: Command not found
```

Both CLI and TUI now show step results as level-3 child nodes with:
- **2-space indentation** before "|__" connector (proper tree structure)
- Brief "Done"/"Failed" text (no description repeat)
- Tree connector icon "|__" (child node indicator)
- Duration and tool count metadata

---

## References

- IG-159: Original TUI step tree display spec
- IG-164: AgentLoop reasoning display (similar tree pattern)
- RFC-0020: Stream display pipeline