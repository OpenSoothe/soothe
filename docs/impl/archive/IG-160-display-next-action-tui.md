# IG-160: Display next_action in TUI Plan Phase (Like CLI)

## User Request

Display soothe `next_action` in plan phase, matching CLI format.

## CLI Behavior

When `soothe.cognition.agent_loop.reason` event is emitted:
- CLI extracts `next_action` field
- Displays as: "→ 🌀 {next_action}" (for continue) or "✓ 🌀 {next_action}" (for complete)
- Uses `format_judgement()` formatter

Example CLI output:
```
→ 🌀 Running cloc analysis
✓ 🌀 Completing final report
```

## TUI Current Behavior

TUI handles `soothe.cognition.agent_loop.reason` in `on_progress_event()`:
- Included in essential_events list (so it's shown)
- Uses brief summary format
- Color determined by status (done → green, replan → yellow)

Current TUI output:
```
● Reason: done (status-based color)
```

Missing:
- No "next_action" field extraction
- No "🌀" prefix
- No "→" or "✓" icon
- No prominence matching CLI

## Implementation

Add special handler in `on_progress_event()` for `agent_loop.reason`:

```python
if event_type == "soothe.cognition.agent_loop.reason":
    # Extract next_action
    next_action = str(payload.get("next_action", "")).strip()
    if not next_action:
        # Fallback to status-based message
        status = str(payload.get("status", ""))
        if status == "done":
            next_action = "Completing final analysis"
        elif status == "replan":
            next_action = "Trying alternative approach"
        else:
            next_action = "Processing next step"
    
    # Capitalize first letter
    if next_action and next_action[0].islower():
        next_action = next_action[0].upper() + next_action[1:]
    
    # Determine icon based on status
    status = str(payload.get("status", ""))
    icon = "✓" if status == "done" else "→"
    color = DOT_COLORS["plan_step_done"] if status == "done" else DOT_COLORS["iteration"]
    
    # Format like CLI: "🌀 {next_action}"
    summary = f"🌀 {next_action}"
    
    # Create line with icon prefix
    action_line = Text()
    action_line.append(icon + " ", style=color)
    action_line.append(summary)
    self._on_panel_write(action_line)
    return
```

## Changes Required

1. **src/soothe/ux/tui/renderer.py**:
   - Add special case for `soothe.cognition.agent_loop.reason` in `on_progress_event()`
   - Extract `next_action` field
   - Format with "🌀" prefix and proper icon ("→" or "✓")
   - Use same capitalization logic as CLI

2. **Testing**:
   - Run multi-step plan in TUI
   - Verify next_action appears with "🌀" prefix
   - Verify icon changes based on status

## Example TUI Output After Fix

```
○ ⏩ Run cloc analysis
  |__ Done [1 tools] (5.3s)
→ 🌀 Processing test coverage report
○ ⏩ Generate coverage report
  |__ Done [0 tools] (0.5s)
✓ 🌀 Completing final analysis
```

Matches CLI's format and provides reasoning transparency during plan execution.

## References

- IG-152: CLI next_action display
- RFC-0019: Event processing
- src/soothe/ux/cli/stream/pipeline.py:466 (action_text extraction)
- src/soothe/ux/cli/stream/formatter.py:format_judgement