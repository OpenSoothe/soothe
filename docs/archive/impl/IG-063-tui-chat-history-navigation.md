# IG-063: TUI Chat History Navigation Enhancement

**Status**: ✅ Completed
**Created**: 2026-03-26
**RFC References**: N/A (UX improvement)

## Objective

Reverse the UP/DOWN arrow key navigation behavior in TUI chat history to match chat interface conventions (UP = newest message first) instead of bash-style history (UP = oldest message first).

## Background

The current `ChatInput` widget implements bash-style history navigation where UP shows older messages and DOWN shows newer messages. This is counterintuitive for a chat interface where users expect UP to show the most recent message first (similar to scrolling up in a chat log).

## Current Behavior

- UP arrow: Starts at the oldest message, navigates towards newest
- DOWN arrow: Starts at newest, navigates back to current input
- History array: `self._history[0]` = oldest, `self._history[-1]` = newest

## Desired Behavior

- UP arrow: Shows the newest message first, then older messages
- DOWN arrow: Shows older messages, then back to current input
- History array: Same storage, but reversed navigation logic

## Implementation Plan

### 1. Modify Navigation Logic in `ChatInput._on_key()`

**File**: `src/soothe/ux/tui/widgets.py`

**Changes**:
- UP arrow: Set `_history_index` to 0 (newest) on first press, increment to navigate older
- DOWN arrow: Decrement to navigate newer, reset to -1 when reaching current input
- Keep history array unchanged (oldest-first)

### 2. Update History Index Semantics

Current:
- `_history_index = -1`: Current input (no history)
- `_history_index = 0`: Oldest message
- `_history_index = len(_history) - 1`: Newest message

New:
- `_history_index = -1`: Current input (no history)
- `_history_index = 0`: Newest message
- `_history_index = len(_history) - 1`: Oldest message

### 3. Implementation Details

```python
# Up arrow - start at newest (index 0)
if event.key == "up" and self.cursor_location[0] == 0:
    event.prevent_default()
    if not self._history:
        return
    if self._history_index == -1:
        self._saved_input = self.text
        self._history_index = 0  # Start at newest
    elif self._history_index < len(self._history) - 1:
        self._history_index += 1  # Go older
    self.text = self._history[-(self._history_index + 1)]  # Reverse index
    self.cursor_location = (0, 0)
    return

# Down arrow - go newer
line_count = len(self.text.split("\n"))
if event.key == "down" and self.cursor_location[0] == line_count - 1:
    event.prevent_default()
    if self._history_index == -1:
        return
    if self._history_index > 0:
        self._history_index -= 1  # Go newer
        self.text = self._history[-(self._history_index + 1)]  # Reverse index
    else:
        self._history_index = -1
        self.text = self._saved_input
    self.cursor_location = (0, 0)
    return
```

## Testing

1. Manual testing in TUI mode:
   - Send multiple messages to build history
   - Test UP arrow shows newest message first
   - Test UP again shows older messages
   - Test DOWN arrow shows newer messages
   - Test DOWN at newest returns to current input
   - Test saved input is restored when navigating back

2. Verify existing tests still pass:
   ```bash
   ./scripts/verify_finally.sh
   ```

## Files Modified

- `src/soothe/ux/tui/widgets.py` - ChatInput navigation logic
- `docs/impl/IG-063-tui-chat-history-navigation.md` - This guide

## Acceptance Criteria

- [x] UP arrow shows newest message first
- [x] UP arrow navigates to older messages on subsequent presses
- [x] DOWN arrow navigates to newer messages
- [x] DOWN arrow at newest message returns to current input
- [x] Saved input is preserved and restored
- [x] All existing tests pass
- [x] Code formatted and linted (zero errors in modified files)