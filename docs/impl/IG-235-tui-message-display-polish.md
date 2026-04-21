# IG-235 TUI Message Display Polish for Human and AI Messages

> **Status**: ✅ Completed
> **Date**: 2026-04-21
> **Scope**: TUI message widgets, visual styling
> **Related**: RFC-000 (System Conceptual Design)

---

## Problem Statement

TUI Human (UserMessage) and AI (AssistantMessage) messages lacked visual polish and role distinction in normal verbosity modes:

1. **No role indicators**: Messages had no clear "Human" or "AI" labels
2. **Minimal styling**: Basic borders without visual hierarchy
3. **Poor separation**: No background tints to distinguish message types
4. **Suboptimal spacing**: Inadequate margins between messages

---

## Solution Design

### UserMessage Enhancements

**Visual Changes**:
- Added "Human" role header with icon (glyphs.user or ">" in ASCII mode)
- Enhanced border styling: primary color with mode-specific variants (shell/command)
- Added background tint: `$surface` for visual separation
- Improved spacing: `margin: 1 0` (1 line before and after)
- Added hover effect: `$surface-darken-1`

**Header Format**:
```
<User Icon> Human  <mode glyph or separator>  <message content>
```

Example with shell mode:
```
👤 Human  $ analyze the logs
```

Example with normal mode:
```
👤 Human  │ write a function
```

### AssistantMessage Enhancements

**Visual Changes**:
- Added "AI" role header with icon (glyphs.assistant or "◆" in ASCII mode)
- Added left border: secondary color for visual distinction from user
- Added background tint: `$background-darken-1` (subtle, different from user)
- Improved spacing: `margin: 1 0`
- Added hover effect: `$background-darken-2`
- Added header widget in compose() method

**Header Format**:
```
<AI Icon> AI
<markdown content>
```

Example:
```
◆ AI
Here's the function you requested...
```

---

## Implementation Details

### Files Modified

**`packages/soothe-cli/src/soothe_cli/tui/widgets/messages.py`**:

#### UserMessage (lines 166-250)
- Enhanced `DEFAULT_CSS` with background, hover effect, mode-specific borders
- Updated `render()` to add role header with icon
- Added separator (`│`) for non-mode messages
- Used `get_glyphs()` for theme-aware icons

#### AssistantMessage (lines 573-623)
- Enhanced `DEFAULT_CSS` with background, border, hover effect
- Added `compose()` method with header widget
- Role header uses `Static` with styled `Content`
- Background tint: `$background-darken-1`

### Key Design Decisions

1. **Role Headers**: Separate visual indicators for clarity
2. **Distinct Borders**: Primary (user) vs Secondary (AI) for quick identification
3. **Background Tints**: Subtle but effective separation
4. **Hover Effects**: Interactive feedback for better UX
5. **Mode Support**: Shell/command modes get specialized styling
6. **ASCII Compatibility**: Fallback icons for ASCII mode

---

## Validation Results

All verification checks passed ✅:
- Code formatting check
- Linting (zero errors)
- Unit tests (1286 passed, 3 skipped, 1 xfailed)

---

## Visual Impact

### Before
```
> user message text
assistant markdown content
```

### After
```
👤 Human  │ user message text
  (with background tint and primary border)

◆ AI
  assistant markdown content
  (with background tint and secondary border)
```

---

## Future Considerations

### Potential Enhancements
1. **Animated role icons**: Subtle pulse during streaming
2. **Timestamp badges**: Optional timestamp in header
3. **Compact mode**: Toggle for reduced spacing
4. **Custom themes**: User-selectable role colors

---

## Documentation Updates

- Updated `docs/impl/IG-235-tui-message-display-polish.md`
- Enhanced widget docstrings with styling details
- Documented role header format and design rationale

---

## Conclusion

TUI now displays Human and AI messages with clear visual distinction through:
- Role indicators with icons
- Enhanced borders and background tints
- Improved spacing and hover effects
- Theme-aware styling supporting both Unicode and ASCII modes

All changes verified with passing tests. Messages are now clearly identifiable and visually polished in normal verbosity modes.