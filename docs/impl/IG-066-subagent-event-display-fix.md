# IG-066: Subagent Event Display Fix

**Status**: ✅ Completed
**Created**: 2026-03-26
**RFC References**: RFC-0015 (Authentication and Security), RFC-0019 (Unified Event Processing)

## Objective

Fix browser and Claude subagent event display to match the tool event two-level tree pattern, using registered event templates from the event catalog.

## Problem

Browser and Claude subagent events are not displaying correctly in the CLI TUI:
- `ClaudeToolUseEvent` is invisible due to missing verbosity setting
- Renderer manually builds event summaries instead of using registered templates
- Subagent events don't follow the tool event two-level tree display pattern
- Claude events have no display handler in the renderer

## Solution

1. Add `verbosity="subagent_progress"` to `ClaudeToolUseEvent` registration
2. Refactor renderer to use event registry templates via `REGISTRY.get_meta()`
3. Add `_format_event_details()` helper for two-level tree display
4. Update `on_progress_event()` to use `make_dot_line()` with body parameter

## Implementation

### Step 1: Fix Claude Event Verbosity

**File**: `src/soothe/subagents/claude/events.py`

- Add `verbosity="subagent_progress"` to `ClaudeToolUseEvent` registration (line 52)
- Makes event visible at normal verbosity level

### Step 2: Refactor Renderer to Use Registry Templates

**File**: `src/soothe/ux/tui/renderer.py`

- Import `REGISTRY` from `soothe.core.event_catalog`
- Replace `_build_event_summary()` manual string building with registry template lookup
- Use `meta.summary_template.format(**data)` for template formatting
- Remove manual browser/agentic event handling (now handled by registry)

### Step 3: Add Two-Level Tree Display

**File**: `src/soothe/ux/tui/renderer.py`

- Add `_format_event_details()` helper method
- Extract details for second-level display:
  - Browser step: action + url
  - Browser CDP: cdp_url
  - Claude text: text preview
  - Agentic: preserve existing logic
- Update `on_progress_event()` to use `make_dot_line(color, summary, details)`

## Expected Output

```
● Step 1
  └ Navigate to page | https://example.com

● Tool: read_file

● Text: Analyzing the code...
  └ This file implements the main...

● Done ($0.0023, 1234ms)
```

## Files Modified

1. `src/soothe/subagents/claude/events.py` - 1 line
2. `src/soothe/ux/tui/renderer.py` - ~60 lines

## Verification

- Run `./scripts/verify_finally.sh`
- Test browser subagent with TUI
- Test claude subagent with TUI
- Verify two-level tree display

## Benefits

- Consistent display pattern across tools and subagents
- Registry-driven event summaries (extensible, maintainable)
- Complete visibility of subagent activity
- No duplicate logic between event registration and display