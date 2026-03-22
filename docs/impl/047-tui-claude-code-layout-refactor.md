# IG-047: TUI Claude Code CLI Layout Refactor

**Status:** Draft
**Created:** 2026-03-22
**RFC References:** RFC-0003 (CLI TUI Architecture Design)

## Overview

Refactor the Soothe TUI to match Claude Code CLI's simpler, cleaner layout with a full-viewport scrollable conversation area, no visible borders, and a compact footer stack containing plan/activity info and input.

## Problem Statement

The current TUI layout uses a three-row structure with visible borders that creates visual clutter and limits the usable screen space. The conversation panel is constrained with a border, and the plan/activity panel occupies a separate row in the middle of the screen, pushing the input box further down.

Claude Code CLI uses a cleaner approach:
- Full-viewport conversation with native terminal scrolling (no borders)
- Plan/activity info stuck just above the input box
- Minimal visual separation between elements
- More screen space for content

## Goals

1. Remove visual clutter (borders) from the conversation panel
2. Move plan/activity panel into a footer stack stuck to the input box
3. Enable native terminal scrolling for the conversation area
4. Simplify the overall layout structure
5. Preserve all existing functionality and keybindings

## Non-Goals

- Changing the conversation rendering logic (keep RichLog-based scrolling)
- Modifying the daemon communication protocol
- Changing the content of plan/activity displays
- Modifying event processing or state management

## Current Architecture

### Layout Structure

```
┌─ Header ─────────────────────────────────────────┐
│ [So Pat                                         ]│
├──────────────────────────────────────────────────┤
│ ┌─ Conversation Panel ────────────────────────┐ │
│ │                                              │ │
│ │  [Messages with markdown rendering]         │ │
│ │                                              │ │
│ │  (border: solid $primary, height: 4fr)      │ │
│ └──────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────┤
│ [Plan Tree] (max-height: 20, separate row)      │
│ - Plan steps with status markers                │
│ - Merged activity info                          │
├──────────────────────────────────────────────────┤
│ > [ChatInput TextArea]                          │
│ ──────────────────────────────────────────────── │
│ Thread: xxx  Events: 123  Status               │
└──────────────────────────────────────────────────┘
```

### Widget Composition

**File:** `src/soothe/ux/tui/app.py`

```python
def compose(self) -> ComposeResult:
    """Build the widget tree: 3-row layout."""
    yield Header()
    with Container(id="main-layout"):
        # Row 1: Conversation panel (largest height)
        with Container(id="conversation-row"):
            yield ConversationPanel(id="conversation", ...)
        # Row 2: Plan tree (merged with activity info)
        with Container(id="info-row"):
            yield PlanTree(id="plan-tree", ...)
    # Chat input with prompt character (outside main-layout, docked at bottom)
    with Container(id="chat-input-container"):
        with Container(id="chat-input-row"):
            yield Static(">", id="chat-prompt")
            yield ChatInput(id="chat-input")
        with Container(id="info-bar-wrapper"):
            yield InfoBar(..., id="info-bar")
```

### CSS Structure

```css
#main-layout {
    layout: vertical;
    height: 1fr;
}
#conversation-row {
    height: 4fr;
    margin-bottom: 1;
}
#conversation {
    border: solid $primary;  /* Visible border */
    height: 100%;
}
#info-row {
    layout: vertical;
    height: auto;
    margin-bottom: 1;
}
#plan-tree {
    height: auto;
    max-height: 20;
    padding: 0 1;
    border: none;
    overflow: hidden;
}
#chat-input-container {
    dock: bottom;
    layout: vertical;
    height: auto;
    background: $surface;
    padding: 1 2 0 2;
    border-top: solid $primary;
}
#chat-input-row {
    layout: horizontal;
    height: auto;
    min-height: 3;
    max-height: 8;
    margin-bottom: 1;
}
#info-bar-wrapper {
    height: auto;
    margin-top: 0;
    padding: 1 0;
    border-top: solid $primary;
}
#info-bar {
    height: 1;
    background: transparent;
    color: $text-muted;
    padding: 0;
}
```

### Key Components

| Component | Type | Purpose | Current Behavior |
|-----------|------|---------|------------------|
| `Header` | `textual.widgets.Header` | App title bar | Occupies top row, shows app title |
| `ConversationPanel` | `RichLog` | Scrollable chat history | Has border, constrained height (4fr) |
| `PlanTree` | `Static` | Plan and activity display | Separate row, max 20 lines |
| `ChatInput` | `TextArea` | User input | Auto-expands 1-6 lines, docked bottom |
| `InfoBar` | `Static` | Status line | Shows thread ID, event count, status |

## Target Architecture

### Layout Structure

```
┌──────────────────────────────────────────────────┐
│ Conversation Output                              │
│ (full height, no border, native scroll)         │
│                                                  │
│ [Messages with markdown rendering]              │
│                                                  │
│                                                  │
│                                                  │
│                                                  │
├──────────────────────────────────────────────────┤
│ [Plan/Activity Panel] (auto height, max 15)     │
│ - Plan steps with status markers                │
│ - Merged activity info                          │
│ (hidden when empty)                             │
├──────────────────────────────────────────────────┤
│ Thread: xxx  Events: 123  Status               │
├──────────────────────────────────────────────────┤
│ > [ChatInput TextArea] (auto height, max 6)     │
└──────────────────────────────────────────────────┘
```

### Widget Composition

**File:** `src/soothe/ux/tui/app.py`

```python
def compose(self) -> ComposeResult:
    """Build the widget tree: simplified layout."""
    yield ConversationPanel(id="conversation", ...)

    with Container(id="footer-stack"):
        yield PlanTree(id="plan-tree", ...)
        yield InfoBar(..., id="info-bar")
        with Container(id="chat-input-row"):
            yield Static(">", id="chat-prompt")
            yield ChatInput(id="chat-input")
```

### CSS Structure

```css
#conversation {
    height: 1fr;
    border: none;           /* No border */
    padding: 0 1;           /* Minimal padding */
    background: transparent;
}

#footer-stack {
    dock: bottom;
    layout: vertical;
    height: auto;
    background: $surface;
    border-top: solid $primary;  /* Single separator at top */
}

#plan-tree {
    height: auto;
    max-height: 15;         /* More compact */
    padding: 0 1;
    border: none;
    display: none;          /* Hidden when empty */
}
#plan-tree.visible {
    display: block;
}

#info-bar {
    height: 1;
    padding: 0 1;
    background: $surface-darken-1;
    color: $text-muted;
}

#chat-input-row {
    layout: horizontal;
    height: auto;
    min-height: 1;
    max-height: 6;
    padding: 0 1;
}

#chat-prompt {
    color: $accent;
    text-style: bold;
    width: auto;
    content-align: left middle;
    padding-right: 1;
}

#chat-input {
    height: auto;
    min-height: 1;
    max-height: 6;
    padding: 0;
    color: $foreground;
    background: transparent;
    border: none;
    width: 1fr;
}
#chat-input:focus {
    border: none;
}
#chat-input .text-area--cursor-line {
    background: transparent;
}
```

### Key Changes

| Aspect | Current | Target |
|--------|---------|--------|
| Header | Visible at top | Removed (more screen space) |
| Conversation border | `border: solid $primary` | `border: none` |
| Conversation height | `height: 4fr` in conversation-row | `height: 1fr` (full viewport) |
| Plan tree position | Separate `info-row` container | Inside `footer-stack` |
| Plan tree max-height | 20 lines | 15 lines (more compact) |
| Input container | Separate `chat-input-container` | Inside `footer-stack` |
| Info bar position | Inside `chat-input-container` | Inside `footer-stack` above input |
| Layout nesting | 3-level deep containers | 2-level deep containers |

## Implementation Steps

### Step 1: Update CSS Structure

**File:** `src/soothe/ux/tui/app.py`

Remove the old CSS and replace with the new structure:

```python
CSS = """
#conversation {
    height: 1fr;
    border: none;
    padding: 0 1;
    background: transparent;
}

#footer-stack {
    dock: bottom;
    layout: vertical;
    height: auto;
    background: $surface;
    border-top: solid $primary;
}

#plan-tree {
    height: auto;
    max-height: 15;
    padding: 0 1;
    border: none;
    display: none;
}
#plan-tree.visible {
    display: block;
}

#info-bar {
    height: 1;
    padding: 0 1;
    background: $surface-darken-1;
    color: $text-muted;
}

#chat-input-row {
    layout: horizontal;
    height: auto;
    min-height: 1;
    max-height: 6;
    padding: 0 1;
}

#chat-prompt {
    color: $accent;
    text-style: bold;
    width: auto;
    content-align: left middle;
    padding-right: 1;
}

#chat-input {
    height: auto;
    min-height: 1;
    max-height: 6;
    padding: 0;
    color: $foreground;
    background: transparent;
    border: none;
    width: 1fr;
}
#chat-input:focus {
    border: none;
}
#chat-input .text-area--cursor-line {
    background: transparent;
}
"""
```

### Step 2: Refactor Widget Composition

**File:** `src/soothe/ux/tui/app.py`

Update the `compose()` method:

```python
def compose(self) -> ComposeResult:
    """Build the widget tree: simplified layout with footer stack."""
    yield ConversationPanel(
        id="conversation",
        highlight=True,
        markup=True,
        wrap=True,
    )

    with Container(id="footer-stack"):
        yield PlanTree(
            id="plan-tree",
            classes="visible" if self._state.plan_visible else ""
        )
        yield InfoBar("Thread: -  Events: 0  Idle", id="info-bar")
        with Container(id="chat-input-row"):
            from textual.widgets import Static
            yield Static(">", id="chat-prompt")
            yield ChatInput(id="chat-input")
```

**Changes:**
- Remove `Header()` widget
- Remove `main-layout` container
- Remove `conversation-row` container
- Remove `info-row` container
- Remove `chat-input-container` and `info-bar-wrapper` containers
- Create `footer-stack` container docked at bottom
- Place `PlanTree`, `InfoBar`, and `chat-input-row` inside `footer-stack`

### Step 3: Update ConversationPanel Widget

**File:** `src/soothe/ux/tui/widgets.py`

No changes needed to the Python class definition. The border removal is handled by CSS.

**Current:**
```python
class ConversationPanel(RichLog):
    """Scrollable conversation panel with markdown rendering."""

    pass
```

**No changes required** - the `RichLog` base class already provides native scrolling.

### Step 4: Update PlanTree Visibility Toggle

**File:** `src/soothe/ux/tui/app.py`

Update the `action_toggle_plan()` method to use the new `visible` class:

```python
def action_toggle_plan(self) -> None:
    """Toggle plan panel visibility."""
    self._state.plan_visible = not self._state.plan_visible
    plan_tree = self.query_one("#plan-tree", PlanTree)
    if self._state.plan_visible:
        plan_tree.add_class("visible")
    else:
        plan_tree.remove_class("visible")
```

### Step 5: Update Plan Tree Rendering

**File:** `src/soothe/ux/tui/app.py`

No changes needed to `_refresh_plan()` method. The height constraint is now handled by CSS (`max-height: 15`).

### Step 6: Verify All Keybindings

**File:** `src/soothe/ux/tui/app.py`

Ensure all existing keybindings still work:

```python
BINDINGS: ClassVar[list[Binding]] = [
    Binding("ctrl+d", "detach", "Detach"),
    Binding("ctrl+q", "quit_app", "Quit"),
    Binding("ctrl+c", "cancel_job", "Cancel Job"),
    Binding("ctrl+e", "focus_input", "Focus Input"),
    Binding("ctrl+y", "copy_last", "Copy Last Message"),
    Binding("ctrl+t", "toggle_plan", "Toggle Plan"),
]
```

All bindings should work without modification.

## Testing and Verification

### Manual Testing Checklist

1. **Basic Layout**
   - [ ] Run `soothe tui`
   - [ ] Verify conversation fills full viewport height
   - [ ] Verify no visible border around conversation
   - [ ] Verify footer stack is docked at bottom
   - [ ] Verify plan tree is inside footer stack (when present)

2. **Native Scrolling**
   - [ ] Generate a long conversation (multiple messages)
   - [ ] Use terminal scroll (mouse wheel, Shift+PageUp/Down)
   - [ ] Verify conversation scrolls smoothly without artificial boundaries
   - [ ] Verify footer stack stays fixed at bottom

3. **Plan/Activity Panel**
   - [ ] Trigger a plan (complex task)
   - [ ] Verify plan appears in footer stack above info bar
   - [ ] Verify plan height is limited to max 15 lines
   - [ ] Press `Ctrl+T` to toggle plan visibility
   - [ ] Verify plan shows/hides correctly
   - [ ] Verify input box stays at bottom when plan is visible

4. **Input Box**
   - [ ] Verify input box is at the very bottom
   - [ ] Type a multi-line message (Shift+Enter)
   - [ ] Verify input expands to max 6 lines
   - [ ] Press Enter to submit
   - [ ] Verify input clears and resets to 1 line

5. **Info Bar**
   - [ ] Verify info bar shows correct thread ID
   - [ ] Verify event count updates
   - [ ] Verify status changes (Idle, Running, etc.)
   - [ ] Verify info bar is between plan and input

6. **Keybindings**
   - [ ] `Ctrl+T`: Toggle plan visibility
   - [ ] `Ctrl+D`: Detach from daemon
   - [ ] `Ctrl+Q`: Quit app
   - [ ] `Ctrl+E`: Focus input
   - [ ] `Ctrl+Y`: Copy last message
   - [ ] `Ctrl+C`: Cancel current job
   - [ ] Up/Down arrows in input: Navigate history

7. **Visual Consistency**
   - [ ] Verify no visual artifacts or layout breaks
   - [ ] Verify text wraps correctly in conversation
   - [ ] Verify markdown renders correctly (headings, code, etc.)
   - [ ] Verify colors and themes apply correctly

### Edge Cases

1. **Empty Plan**
   - [ ] Start TUI with no plan
   - [ ] Verify plan tree is hidden (`display: none`)
   - [ ] Verify footer stack shows only info bar and input

2. **Very Long Plan**
   - [ ] Create a plan with many steps (>15)
   - [ ] Verify plan height is capped at 15 lines
   - [ ] Verify internal scrolling within plan tree

3. **Long Conversation**
   - [ ] Generate 100+ messages
   - [ ] Verify terminal performance is acceptable
   - [ ] Verify scrolling remains smooth
   - [ ] Verify no memory leaks or slowdowns

4. **Rapid Updates**
   - [ ] Trigger rapid event stream (e.g., file processing)
   - [ ] Verify UI updates don't block or stutter
   - [ ] Verify plan tree updates correctly
   - [ ] Verify activity lines appear correctly

## Migration Notes

### Breaking Changes

None. All user-facing functionality is preserved.

### Configuration Changes

None. No changes to `SootheConfig` or daemon configuration.

### Compatibility

- **Textual version**: Tested with Textual >= 0.40.0
- **Python version**: Requires Python >= 3.11 (no change)
- **Terminal**: Works with any terminal supporting ANSI escape codes

## Performance Considerations

### Improvements

1. **Fewer containers**: Reduced DOM depth from 3 to 2 levels
2. **Removed Header**: Less rendering overhead
3. **Simplified CSS**: Fewer style rules to compute
4. **Native scrolling**: Terminal handles scroll buffer efficiently

### Potential Issues

- **Large conversation history**: Terminal scroll buffer may consume more memory
- **Very long plans**: Plan tree internal scrolling may be slower than before

### Mitigation

- Keep `RichLog` for conversation (handles large histories well)
- Keep `max-height: 15` constraint on plan tree
- Consider adding conversation compaction for very long sessions (future enhancement)

## Documentation Updates

After successful implementation:

1. Update `CLAUDE.md`:
   - Update "CLI TUI Architecture" section
   - Update module map for TUI changes

2. Update `docs/specs/RFC-0003.md`:
   - Document new layout structure
   - Update CSS examples
   - Add rationale for borderless design

3. Update user-facing documentation:
   - `docs/user_guide.md` - Update TUI screenshots
   - Add note about native terminal scrolling

## Success Criteria

- [ ] All manual testing checklist items pass
- [ ] No visual regressions compared to previous TUI
- [ ] Performance is equal or better than before
- [ ] All keybindings work correctly
- [ ] Plan toggle works correctly
- [ ] Long conversations scroll smoothly
- [ ] Footer stack stays fixed at bottom
- [ ] Code passes `make lint` with no errors
- [ ] Documentation is updated

## Future Enhancements

Potential follow-up improvements:

1. **Configurable plan height**: Allow users to set `max-height` via config
2. **Conversation compaction**: Auto-truncate old messages when history is large
3. **Custom themes**: Support user-defined color schemes
4. **Split view mode**: Optional side-by-side conversation and plan (like original RFC-0003 design)
5. **Activity filtering**: Allow users to filter activity lines by type/verbosity

## References

- **RFC-0003**: CLI TUI Architecture Design
- **IG-010**: TUI Layout History Refresh
- **Textual Documentation**: https://textual.textualize.io/
- **Claude Code CLI**: Reference implementation for layout inspiration

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-03-22 | Claude | Initial draft |