# IG-158: Optimize TUI Output to Match CLI Brevity

## Problem

TUI output is verbose compared to CLI headless mode:
- Detailed progress events with full event summaries
- Multi-line tree structure with colored dots
- Iteration/goal tracking shown explicitly
- Each step completion shown separately

CLI output is brief:
- Flat single-line tool blocks
- Minimal progress tracking
- Essential output only

## Analysis

From screenshot comparison:

**CLI (brief)**:
```
⚙ ls(path='.')
✓ 3 items found (150ms)
```

**TUI (verbose)**:
```
● Step 1: analyze requirements (completed)
  └ ✓ success (450ms)
● Iteration 2: planning phase
● Goal: create implementation
⚙ Tool: ls(path='.')
  └ ✓ success (150ms)
```

Root causes:
1. **TUI uses `make_dot_line()` with full event summaries** - Shows all event details
2. **CLI uses `StreamDisplayPipeline` with concise format** - Shows minimal output
3. **TUI shows all progress events** - EventProcessor doesn't filter aggressively
4. **CLI filters most intermediate events** - Only shows tool calls/results

## Solution

Make TUI renderer use CLI-style formatting:

### Change 1: Simplify Tool Call/Result Formatting

Current TUI tool call:
```python
# Multi-line tree structure
⚙ ToolName(args_summary)
  └ result line
```

Change to CLI-style flat format:
```python
# Single line
⚙ ToolName(args_summary)
✓ result summary (duration_ms)
```

Implementation:
- Use `make_tool_block()` with `status="running"` → single line
- Use flat result line like CLI's `format_tool_result()`
- Remove tree connector `└`

### Change 2: Suppress Progress Events

Current TUI shows all progress events via `on_progress_event()`:
- Iteration tracking
- Goal updates
- Step completions

Change: Skip most progress events, only show:
- Plan creation (brief goal line)
- Multi-step plan execution summary
- Final completion

Implementation:
- Check `VerbosityTier` before rendering
- Skip `iteration`, `progress`, `goal` events in TUI
- Only show `plan_created`, `step_completed` milestones

### Change 3: Reduce Event Summary Verbosity

Current TUI builds full summaries via `_build_event_summary()`:
```
"Step 1: analyze requirements (completed in 450ms)"
```

Change to CLI-style brief summaries:
```
"● analyze requirements ✓"
```

Implementation:
- Use same summary extraction as CLI's `StreamDisplayPipeline`
- Truncate to 60 chars max
- Show status inline, not separate line

### Change 4: Match CLI Verbosity Policy

CLI uses `VerbosityTier.NORMAL` to filter aggressively:
- Only show tool calls/results
- Suppress intermediate reasoning

TUI should match:
- Apply same tier visibility checks
- Use `VerbosityTier.NORMAL` as default
- Suppress `VerbosityTier.DETAILED` events

## Files to Modify

1. `src/soothe/ux/tui/renderer.py`:
   - `on_tool_call()` → Use flat single-line format
   - `on_tool_result()` → Match CLI's format_tool_result()
   - `on_progress_event()` → Add tier visibility check, suppress most events

2. `src/soothe/ux/tui/utils.py`:
   - `make_tool_block()` → Add `compact=True` option for single-line format

3. `src/soothe/ux/shared/event_processor.py`:
   - Add tier visibility check before calling `on_progress_event()`

## Implementation Details

### Tool Call Format (TUI)

Change from:
```python
# Multi-line
tool_block = make_tool_block(display_name, args_str, status="running")
self._on_panel_write(tool_block)
```

To:
```python
# Single line (CLI-style)
line = Text()
line.append("⚙ ", style=DOT_COLORS["tool_running"])
line.append(f"{display_name}({args_str})")
self._on_panel_write(line)
```

### Tool Result Format (TUI)

Change from:
```python
# Tree structure
result_line = Text()
result_line.append("  └ ", style="dim")
result_line.append(icon + " ", style=color)
result_line.append(brief)
```

To:
```python
# Flat line (CLI-style)
result_line = Text()
result_line.append(icon, style=color)
result_line.append(f" {brief}")
if duration_ms > 0:
    result_line.append(f" ({duration_ms}ms)", style="dim")
self._on_panel_write(result_line)
```

### Progress Event Filtering

Add tier check:
```python
def on_progress_event(self, event_type, data, namespace):
    # Skip verbose events
    tier = classify_event_to_tier(event_type, namespace)
    if not self._presentation.tier_visible(tier, self._verbosity):
        return

    # Only show essential events
    if event_type in {"soothe.cognition.plan.created",
                      "soothe.agentic.loop.completed"}:
        # Show brief summary
        pass
```

### Event Summary Truncation

Change from:
```python
summary = self._build_event_summary(event_type, payload)
# Full sentence: "Step 1: analyze requirements (completed)"
```

To:
```python
# Brief format
goal = payload.get("goal", "")[:60]
if event_type == "soothe.cognition.plan.created":
    summary = f"📋 {goal}"
elif event_type == "soothe.agentic.loop.completed":
    status = payload.get("status", "done")
    summary = f"✅ {status}"
```

## Success Criteria

After optimization:
- TUI tool output matches CLI's flat single-line format
- Progress events reduced to essential milestones only
- Output concise and readable like CLI
- No tree structure for tool results
- Same brevity level as headless mode

## Testing

1. Start TUI: `soothe`
2. Run same query as CLI: `soothe "list files"`
3. Compare output:
   - TUI should show same concise format
   - No extra progress lines
   - Same information density

## References

- RFC-0020: Stream display pipeline
- RFC-0019: Event processing architecture
- IG-143: Multi-step suppression
- CLI renderer: `src/soothe/ux/cli/renderer.py`