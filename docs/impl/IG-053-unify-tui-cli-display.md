# Implementation Guide: Unify TUI and CLI Event Display

**Status**: ✅ Completed
**Date**: 2026-03-28
**Effort**: ~7 hours

## Summary

Unified TUI and CLI event display to ensure consistent user experience across both modes. Added support for initial prompt in TUI mode (`-p` flag).

## Changes

### Phase 0: ChatInput History Property
- Added public `history` property to `ChatInput` widget for test compatibility
- UP/DOWN arrow navigation was already fully implemented
- **Files**: `src/soothe/ux/tui/widgets.py`

### Phase 1: Shared Event Filter
- Created `ux/core/event_filter.py` with shared skip logic
- Both CLI and TUI now skip same events (policy events, plan step events)
- **Files**: `src/soothe/ux/core/event_filter.py` (new), `src/soothe/ux/cli/progress.py`, `src/soothe/ux/tui/renderer.py`

### Phase 2: Removed TUI Detail Extraction
- Removed `_format_event_details()` method from TUI renderer
- TUI now shows same event depth as CLI (simpler, more consistent)
- **Files**: `src/soothe/ux/tui/renderer.py`

### Phase 3: Shared Event Formatter
- Created `ux/core/event_formatter.py` with shared summary building logic
- Both modes use same registry template formatting
- **Files**: `src/soothe/ux/core/event_formatter.py` (new), `src/soothe/ux/cli/progress.py`, `src/soothe/ux/tui/renderer.py`

### Phase 4: Skipped (Optional)
- Tool block preparation sharing - not needed as modes have different rendering (plain text vs Rich)

### Phase 5: Tests
- All tests passed with unified behavior
- Tests confirmed policy events should be skipped in both modes

### Phase 6: Initial Prompt Support
- Added `initial_prompt` parameter to `SootheApp` and `run_textual_tui`
- Added `submit_chat_input_with_text()` helper method
- Users can now run `soothe -p "who are you"` to start TUI with initial prompt
- **Files**: `src/soothe/ux/tui/app.py`, `src/soothe/ux/cli/commands/run_cmd.py`, `src/soothe/ux/cli/execution/launcher.py`

## Verification

All checks passed:
- ✓ Format check: PASSED
- ✓ Linting: PASSED (zero errors)
- ✓ Unit tests: PASSED (935 passed, 2 skipped, 1 xfailed)

## Key Achievements

1. **Consistency**: TUI and CLI now display events identically (excluding Rich styling)
2. **Simplicity**: Removed TUI's extra detail extraction for cleaner display
3. **Code Reuse**: Shared modules in `ux.core` reduce duplication by ~50%
4. **UX Enhancement**: `-p` flag now works with TUI mode for convenient quick-start
5. **Test Compatibility**: ChatInput now has public `history` property

## Usage Examples

```bash
# Start TUI with initial prompt
soothe -p "who are you"

# Normal interactive TUI
soothe

# Headless mode (unchanged)
soothe -p "search weather" --no-tui
```

## Architecture Impact

**New Modules:**
- `ux/core/event_filter.py` - Centralized event filtering
- `ux/core/event_formatter.py` - Shared event formatting

**Pattern**: Shared preparation, mode-specific rendering
- Both modes use same data/logic from `ux.core`
- CLI renders as plain text, TUI renders as Rich Text
- Future changes automatically apply to both

## References

- Plan: `/Users/chenxm/.claude/plans/adaptive-stirring-rabin.md`
- RFC-0019: Unified Event Processing
- RFC-0020: Registry-Driven Display