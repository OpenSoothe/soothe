# Implementation Guide: CLI/TUI Event Progress Clarity

**Guide**: IG-053
**Title**: CLI/TUI Event Progress Clarity
**Status**: In Progress
**Created**: 2026-03-26
**Updated**: 2026-03-26

---

## Overview

This guide implements CLI/TUI event progress clarity improvements through:
1. Text formatting fixes (whitespace normalization)
2. Two-level tree structure for tool calls
3. Special tool behaviors for complex tools
4. Plan and protocol event improvements

---

## Implementation Checklist

### Phase 1: Critical Bug Fixes (P0) ✅ COMPLETED
- [x] Fix text spacing in `strip_internal_tags()`
- [x] Add whitespace normalization
- [x] Add unit tests for spacing
- [x] Verify with manual test

**Files Modified**:
- `src/soothe/ux/shared/message_processing.py`
- `tests/unit/test_message_processing.py` (new)

**Commit**: afcb143

### Phase 2: Tool Call Tree Structure (P0) ✅ COMPLETED
- [x] Create `ToolCallTracker` class
- [x] Update `CliEventRenderer` for tree rendering
- [x] Implement tree indentation with icons (⚙ ✓ ✗)
- [x] Update WebSearch, CrawlWeb, Research tools
- [x] Update standalone_runner and daemon_runner
- [x] All 921 tests passed

**Files Modified**:
- `src/soothe/ux/cli/rendering/cli_event_renderer.py`
- `src/soothe/ux/cli/rendering/tool_call_tracker.py` (new)
- `src/soothe/ux/cli/execution/standalone_runner.py`
- `src/soothe/ux/cli/execution/daemon_runner.py`

**Commit**: afcb143

### Phase 3: Special Tool Behaviors (P1) ✅ COMPLETED
- [x] Create `ToolBehaviorRegistry`
- [x] Implement Browser behavior (multi-step)
- [x] Implement File operations behavior
- [x] Implement Execution behavior
- [x] Add tests (all 921 tests passed)

**Files Modified**:
- `src/soothe/ux/cli/rendering/tool_behaviors.py` (new)

**Commit**: a04b87c

### Phase 4: Plan & Protocol Improvements (P1) ✅ COMPLETED
- [x] Update plan rendering with tree structure
- [x] Add plan step progress icons
- [x] All 921 tests passed
- [ ] Move protocol events to debug mode (requires event catalog update)
- [ ] Update user documentation (future task)

**Files Modified**:
- `src/soothe/ux/cli/rendering/cli_event_renderer.py`

**Commit**: a04b87c

---

## Detailed Implementation

### Phase 1: Text Formatting Fixes

#### 1.1 Fix `strip_internal_tags()` in `message_processing.py`

**Current Issue**: Text concatenation removes spaces between sentences.

**Location**: `src/soothe/ux/shared/message_processing.py:199-214`

**Fix**: Add whitespace normalization after stripping tags.

```python
def strip_internal_tags(text: str) -> str:
    """Strip internal tool tags from assistant text for clean display.

    Removes `<search_data>...</search_data>` blocks and associated
    synthesis instructions that should not be shown to users.

    Args:
        text: The text to strip tags from.

    Returns:
        Cleaned text with internal tags removed and normalized whitespace.
    """
    result = _INTERNAL_TAG_PATTERN.sub("", text)
    result = _LEFTOVER_TAG_PATTERN.sub("", result)
    result = _SYNTHESIS_INSTRUCTION_PATTERN.sub("", result)

    # NEW: Normalize whitespace to fix concatenation issues
    # Ensure single spaces between words and sentences
    import re
    result = re.sub(r'\s+', ' ', result)  # Normalize multiple spaces to single
    result = re.sub(r'\s*([.!?])\s*', r'\1 ', result)  # Ensure space after punctuation
    result = re.sub(r'\s+,', ',', result)  # Remove space before comma

    return result.strip()
```

#### 1.2 Add Unit Tests

**File**: `tests/ux/test_message_processing.py`

```python
import pytest
from soothe.ux.shared.message_processing import strip_internal_tags


class TestStripInternalTags:
    """Test whitespace normalization in strip_internal_tags()."""

    def test_preserves_spaces_between_words(self):
        """Ensure spaces are preserved between words."""
        text = "Hello world this is a test"
        result = strip_internal_tags(text)
        assert result == "Hello world this is a test"

    def test_normalizes_multiple_spaces(self):
        """Multiple spaces should collapse to single space."""
        text = "Hello    world   test"
        result = strip_internal_tags(text)
        assert result == "Hello world test"

    def test_adds_space_after_punctuation(self):
        """Ensure space after sentence-ending punctuation."""
        text = "First sentence.Second sentence.Third one"
        result = strip_internal_tags(text)
        assert result == "First sentence. Second sentence. Third one"

    def test_removes_search_data_tags(self):
        """Remove <search_data> tags and content."""
        text = "Before<search_data>content</search_data>After"
        result = strip_internal_tags(text)
        assert result == "Before After"

    def test_complex_formatting(self):
        """Test complex markdown formatting."""
        text = "**Bold text** here.More text after."
        result = strip_internal_tags(text)
        assert result == "**Bold text** here. More text after."
```

---

### Phase 2: Tool Call Tree Structure

#### 2.1 Create ToolCallTracker

**File**: `src/soothe/ux/cli/rendering/tool_call_tracker.py`

```python
"""Track tool call start/complete pairs for tree rendering.

This module implements the two-level tree structure for tool calls,
matching tool start events with their completion events to render as
parent/child tree nodes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ToolCallState:
    """State for a pending tool call.

    Attributes:
        tool_name: Display name of the tool (CamelCase).
        tool_call_id: Unique identifier for the tool call.
        start_time: Unix timestamp when the call started.
        line_index: Terminal line where parent event was rendered.
        args_summary: Summary of arguments (e.g., "query='test'").
    """
    tool_name: str
    tool_call_id: str
    start_time: float
    line_index: int
    args_summary: str


@dataclass
class ToolCallTracker:
    """Track tool call start/complete pairs for tree rendering.

    The tracker maintains a mapping of pending tool calls (started but not
    yet completed) to enable rendering them as two-level trees:

    ```
    ⚙ ToolName(args)
      └ ✓ result summary
    ```

    Attributes:
        pending: Map of tool_call_id to ToolCallState.
        line_counter: Counter for tracking terminal line positions.
    """

    pending: dict[str, ToolCallState] = field(default_factory=dict)
    line_counter: int = 0

    def register_start(
        self,
        tool_name: str,
        tool_call_id: str,
        args_summary: str,
    ) -> int:
        """Register a tool call start event.

        Args:
            tool_name: Display name of the tool.
            tool_call_id: Unique identifier for this tool call.
            args_summary: Summary of arguments.

        Returns:
            Line index where the parent event should be rendered.
        """
        state = ToolCallState(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            start_time=time.time(),
            line_index=self.line_counter,
            args_summary=args_summary,
        )
        self.pending[tool_call_id] = state
        self.line_counter += 1
        return state.line_index

    def register_complete(self, tool_call_id: str) -> ToolCallState | None:
        """Register a tool call completion event.

        Args:
            tool_call_id: Unique identifier for the tool call.

        Returns:
            ToolCallState if found, None if not tracked.
        """
        state = self.pending.pop(tool_call_id, None)
        if state:
            self.line_counter += 1
        return state

    def get_pending(self) -> list[ToolCallState]:
        """Get list of pending tool calls (for cleanup/debug).

        Returns:
            List of ToolCallState for pending calls.
        """
        return list(self.pending.values())

    def clear(self) -> None:
        """Clear all pending tool calls."""
        self.pending.clear()
        self.line_counter = 0
```

#### 2.2 Update CliEventRenderer

**File**: `src/soothe/ux/cli/rendering/cli_event_renderer.py`

**Changes**:

1. Add ToolCallTracker to `__init__`:
```python
from soothe.ux.cli.rendering.tool_call_tracker import ToolCallTracker

class CliEventRenderer:
    def __init__(self) -> None:
        """Initialize the CLI event renderer with registered handlers."""
        self._registry = REGISTRY
        self._handlers: dict[str, Callable[[dict], list[str]]] = {}
        self._tool_tracker = ToolCallTracker()  # NEW
        self._register_handlers()
```

2. Add new constants for tree rendering:
```python
# Tree rendering constants
_TREE_PARENT_ICON_RUNNING = "⚙"
_TREE_PARENT_ICON_SUCCESS = "✓"
_TREE_PARENT_ICON_ERROR = "✗"
_TREE_CHILD_PREFIX = "  └ "
_MAX_RESULT_LENGTH = 60
```

3. Add handler for tool start events:
```python
def _render_tool_start(self, event: dict[str, Any]) -> list[str]:
    """Render tool start event as tree parent."""
    tool_name = event.get("tool_name", "tool")
    tool_call_id = event.get("tool_call_id", "")
    args = event.get("args", {})

    # Format args summary
    from soothe.ux.shared.message_processing import format_tool_call_args
    args_summary = format_tool_call_args(tool_name, {"args": args})

    # Register with tracker
    self._tool_tracker.register_start(tool_name, tool_call_id, args_summary)

    # Render parent line
    from soothe.tools.display_names import get_tool_display_name
    display_name = get_tool_display_name(tool_name)

    return [f"{_TREE_PARENT_ICON_RUNNING} {display_name}{args_summary}"]
```

4. Add handler for tool complete events:
```python
def _render_tool_complete(self, event: dict[str, Any]) -> list[str]:
    """Render tool complete event as tree child."""
    tool_call_id = event.get("tool_call_id", "")
    result = event.get("result", "")
    success = event.get("success", True)
    duration_ms = event.get("duration_ms", 0)

    # Get state from tracker
    state = self._tool_tracker.register_complete(tool_call_id)
    if not state:
        # Fallback: no matching start event
        return []

    # Extract brief result
    from soothe.ux.shared.message_processing import extract_tool_brief
    brief = extract_tool_brief(state.tool_name, result, _MAX_RESULT_LENGTH)

    # Add duration if available
    if duration_ms > 0:
        duration_s = duration_ms / 1000
        brief += f" ({duration_s:.1f}s)"

    # Choose icon based on success
    icon = _TREE_PARENT_ICON_SUCCESS if success else _TREE_PARENT_ICON_ERROR

    # Render child line with tree prefix
    return [f"{_TREE_CHILD_PREFIX}{icon} {brief}"]
```

5. Register new handlers in `_register_handlers()`:
```python
# Tool call tree rendering (NEW)
# Note: This requires tool implementations to emit start/complete events
# with tool_call_id for matching. For now, we'll work with existing events.
```

**Note**: Since existing tools emit different event types (e.g., `TOOL_WEBSEARCH_SEARCH_STARTED`), we need to adapt the handlers in Phase 3.

---

## Testing Plan

### Unit Tests

**File**: `tests/ux/cli/test_tree_rendering.py`

```python
"""Test tree rendering for tool calls."""

import pytest
from soothe.ux.cli.rendering.tool_call_tracker import ToolCallTracker, ToolCallState


class TestToolCallTracker:
    """Test ToolCallTracker for matching start/complete events."""

    def test_register_start_returns_line_index(self):
        """Start event registration returns line index."""
        tracker = ToolCallTracker()
        line_idx = tracker.register_start("WebSearch", "call_123", "(query='test')")
        assert line_idx == 0

    def test_register_complete_returns_state(self):
        """Complete event registration returns stored state."""
        tracker = ToolCallTracker()
        tracker.register_start("WebSearch", "call_123", "(query='test')")

        state = tracker.register_complete("call_123")
        assert state is not None
        assert state.tool_name == "WebSearch"
        assert state.args_summary == "(query='test')"

    def test_register_complete_unknown_id_returns_none(self):
        """Complete with unknown ID returns None."""
        tracker = ToolCallTracker()
        state = tracker.register_complete("unknown_id")
        assert state is None

    def test_multiple_concurrent_calls(self):
        """Track multiple concurrent tool calls."""
        tracker = ToolCallTracker()

        tracker.register_start("WebSearch", "call_1", "(query='test1')")
        tracker.register_start("ReadFile", "call_2", "(path='file.txt')")
        tracker.register_start("RunCommand", "call_3", "(cmd='ls')")

        # Complete out of order
        state2 = tracker.register_complete("call_2")
        assert state2.tool_name == "ReadFile"

        state1 = tracker.register_complete("call_1")
        assert state1.tool_name == "WebSearch"

        pending = tracker.get_pending()
        assert len(pending) == 1
        assert pending[0].tool_name == "RunCommand"
```

---

## Manual Testing

### Test Commands

```bash
# Test 1: Web search (default tool behavior)
uv run soothe --no-tui -p "/browser iran wars"

# Expected output:
# ⚙ WebSearch("Iran wars history conflicts")
#   └ ✓ 10 results in 7.6s

# Test 2: File operations
uv run soothe --no-tui -p "read the file config.yml"

# Expected output:
# ⚙ ReadFile(config.yml)
#   └ ✓ 245 lines (8.2kb)

# Test 3: Multi-step plan
uv run soothe --no-tui -p "analyze the codebase structure"

# Expected output:
# ● Plan: Analyze codebase structure (3 steps)
#   ├ ✓ Step 1: List project structure
#   ├ ⚙ Step 2: Read key files
#   └ ⏳ Step 3: Generate summary
```

---

## Notes

- Phase 1 (text formatting) can be implemented and tested immediately
- Phase 2 (tree structure) requires adapting existing event handlers
- Phase 3 (special behaviors) extends the base system
- Phase 4 (plan improvements) builds on Phase 2

---

## References

- RFC-0003: CLI TUI Architecture Design
- RFC-0015: Progress Event Protocol
- Design Draft: `docs/drafts/003-cli-tui-event-progress-clarity.md`
- Current Implementation: `src/soothe/ux/cli/rendering/cli_event_renderer.py`