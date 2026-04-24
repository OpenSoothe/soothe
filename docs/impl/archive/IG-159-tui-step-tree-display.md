# IG-159: Optimize TUI Step Tree Display

## User Request

Show plan steps in tree mode with matched content and results:

**Example format**:
```
○ ⏩ Run cloc on src/ and tests/ directories to calculate Soothe's source and test code metrics
  |__ Done [1 tools] (13.1s)
  |__ Error: failed reason
```

**For running steps**: Show consumed time dynamically:
```
○ ⏩ Running analysis...
  |__ Running [1 tools] (13.1s)
```

## Current Behavior

Plan steps are only shown in the plan tree widget:
- `on_plan_step_started()` → refreshes plan tree widget
- `on_plan_step_completed()` → refreshes plan tree widget
- No conversation panel output for step execution

## New Behavior

Show step execution in conversation panel with tree structure:

### Step Started
```python
# Show step description
step_line = Text()
step_line.append("○ ⏩ ", style="cyan")
step_line.append(description)
self._on_panel_write(step_line)

# Track start time for dynamic updates
self._step_start_times[step_id] = time.time()
```

### Step Running (with dynamic time)
```python
# Show running status with current duration
duration = int((time.time() - start_time) * 1000)
running_line = Text()
running_line.append("  |__ Running ", style="yellow")
running_line.append(f"[{tool_count} tools]", style="dim")
running_line.append(f" ({duration/1000:.1f}s)", style="dim")
self._on_panel_update_last(running_line)
```

### Step Completed
```python
# Show completion result directly after step
duration = int((time.time() - start_time) * 1000)
result_line = Text()
result_line.append("  |__ ", style="dim")
result_line.append("Done ", style="green" if success else "red")
result_line.append(f"[{tool_count} tools]", style="dim")
result_line.append(f" ({duration/1000:.1f}s)", style="dim")
self._on_panel_write(result_line)

# If error, show error message on next line
if not success:
    error_line = Text()
    error_line.append("  |__ Error: ", style="red")
    error_line.append(error_msg, style="dim")
    self._on_panel_write(error_line)
```

## Implementation Details

### Change 1: Add Step State Tracking

Add to `TuiRendererState`:
```python
# Track step execution for tree display (IG-159)
step_start_times: dict[str, float] = field(default_factory=dict)
step_tool_counts: dict[str, int] = field(default_factory=dict)
step_errors: dict[str, str] = field(default_factory=dict)
```

### Change 2: Implement `on_plan_step_started()`

```python
def on_plan_step_started(self, step_id: str, description: str) -> None:
    """Show step description in conversation panel."""
    # Track start time
    self._state.step_start_times[step_id] = time.time()
    self._state.step_tool_counts[step_id] = 0
    self._state.step_errors[step_id] = ""

    # Show step line
    step_line = Text()
    step_line.append("○ ⏩ ", style="cyan")
    step_line.append(description)
    if self._on_panel_write:
        self._on_panel_write(step_line)

    # Refresh plan tree widget
    if self._on_plan_refresh:
        self._on_plan_refresh()
```

### Change 3: Track Tool Calls per Step

In `on_tool_call()`, increment tool count for current step:
```python
# Track tool calls for current step
if self._state.suppression.multi_step_active:
    # Find current running step
    current_step = self._get_current_running_step()
    if current_step and current_step in self._state.step_tool_counts:
        self._state.step_tool_counts[current_step] += 1
```

### Change 4: Implement `on_plan_step_completed()`

```python
def on_plan_step_completed(self, step_id, success, duration_ms) -> None:
    """Show step result directly after description."""
    if not self._on_panel_write:
        return

    # Calculate duration
    start_time = self._state.step_start_times.get(step_id, 0)
    if start_time:
        duration_ms = int((time.time() - start_time) * 1000)

    tool_count = self._state.step_tool_counts.get(step_id, 0)

    # Show result line
    result_line = Text()
    result_line.append("  |__ ", style="dim")
    result_line.append("Done" if success else "Failed", style="green" if success else "red")
    if tool_count > 0:
        result_line.append(f" [{tool_count} tools]", style="dim")
    result_line.append(f" ({duration_ms/1000:.1f}s)", style="dim")
    self._on_panel_write(result_line)

    # Show error message if failed
    if not success:
        error_msg = self._state.step_errors.get(step_id, "Unknown error")
        error_line = Text()
        error_line.append("  |__ Error: ", style="red")
        error_line.append(error_msg, style="dim")
        self._on_panel_write(error_line)

    # Cleanup step state
    self._state.step_start_times.pop(step_id, None)
    self._state.step_tool_counts.pop(step_id, None)
    self._state.step_errors.pop(step_id, None)

    # Refresh plan tree widget
    if self._on_plan_refresh:
        self._on_plan_refresh()
```

### Change 5: Track Errors per Step

Add method to track step errors:
```python
def track_step_error(self, step_id: str, error: str) -> None:
    """Track error message for a step."""
    self._state.step_errors[step_id] = error
```

### Change 6: Dynamic Running Time Display (Optional Enhancement)

For long-running steps (>5s), add periodic time updates:
```python
# In _periodic_update_task() (similar to typing indicator)
for step_id, start_time in self._state.step_start_times.items():
    duration = int((time.time() - start_time) * 1000)
    if duration > 5000:  # Only show for >5s
        # Update running line with current duration
        ...
```

Note: This requires adding a periodic update mechanism, which is more complex.

## Success Criteria

- Step descriptions shown in conversation panel with "○ ⏩" prefix
- Results shown directly after with "|__" tree connector
- Tool count and duration shown for completed steps
- Error messages shown for failed steps
- Clean tree structure matching user's example format

## Files to Modify

1. `src/soothe/ux/tui/renderer.py`:
   - Add step state tracking to `TuiRendererState`
   - Implement `on_plan_step_started()` with conversation panel output
   - Implement `on_plan_step_completed()` with result display
   - Track tool calls per step in `on_tool_call()`

2. `src/soothe/ux/shared/event_processor.py` (optional):
   - Add error tracking for step failures

## Testing

Run multi-step plan in TUI:
```
soothe "analyze codebase metrics"
```

Verify output shows:
```
○ ⏩ Run cloc analysis
  |__ Done [1 tools] (2.3s)
○ ⏩ Generate report
  |__ Done [0 tools] (0.5s)
```

For failed step:
```
○ ⏩ Execute command
  |__ Failed [1 tools] (1.2s)
  |__ Error: Command not found
```

## References

- IG-143: Multi-step suppression
- RFC-0019: Event processing
- Plan tree widget: `src/soothe/ux/tui/widgets.py`