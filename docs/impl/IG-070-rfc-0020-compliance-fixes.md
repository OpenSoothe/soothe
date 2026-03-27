# IG-070: RFC-0020 Event Display Architecture Compliance Fixes

**Implementation Guide**: IG-070
**RFC**: RFC-0020 Event Display Architecture
**Created**: 2026-03-27
**Status**: In Progress
**Priority**: High

## Overview

This implementation guide addresses critical compliance gaps between RFC-0020 specification and the current CLI/TUI implementation for tools and subagents display. The review identified 6 major gaps with an overall compliance score of 60%.

## Problem Statement

The current implementation violates several core principles of RFC-0020:

1. **Verbosity Classification Error**: Tool events classified as `protocol` instead of `tool_activity`, causing them to be visible in normal mode when they should be filtered
2. **Missing Subagent Lifecycle Events**: No dispatch/completion events, steps appear disconnected
3. **Hardcoded CLI Display Logic**: CLI renderer doesn't use registry templates, violating extensibility principle
4. **Inconsistent Visual Patterns**: CLI doesn't use display helpers, diverging from TUI
5. **Flat Tool Result Display**: No two-level tree structure with duration tracking

## Success Criteria

After implementation:
- ✅ Tool events filtered correctly in verbose mode only
- ✅ Subagents show clear dispatch → steps → completion lifecycle
- ✅ New events display without modifying renderers
- ✅ Consistent visual patterns across CLI and TUI
- ✅ Tool results show as indented children with duration
- ✅ All 6 RFC-0020 success criteria met

## Implementation Plan

### Priority 1: Fix Verbosity Classification (Critical)

**Impact**: Tools visible in wrong mode, confusing users

#### Task 1.1: Update Display Policy Classification

**File**: `src/soothe/ux/core/display_policy.py:176-179`

**Current Code**:
```python
if domain == "tool":
    # Check if it's an internal research event
    if "internal" in event_type:
        return EventCategory.INTERNAL
    return EventCategory.PROTOCOL  # ❌ WRONG!
```

**Fix**:
```python
if domain == "tool":
    # Check if it's an internal research event
    if "internal" in event_type:
        return EventCategory.INTERNAL
    return EventCategory.TOOL_ACTIVITY  # ✅ Correct classification
```

**Testing**: Run `soothe run "list files"` in normal mode - tool events should NOT appear. Run with `--verbose` - tool events should appear.

#### Task 1.2: Add Verbosity to Tool Event Registrations

**Files**: All tool `events.py` files

**Example** (`src/soothe/tools/execution/events.py:115-123`):

**Current**:
```python
register_event(CommandStartedEvent, summary_template="Running: {command}")
register_event(CommandCompletedEvent, summary_template="Command completed (exit={exit_code})")
```

**Fix**:
```python
register_event(
    CommandStartedEvent,
    verbosity="tool_activity",
    summary_template="Running: {command}",
)
register_event(
    CommandCompletedEvent,
    verbosity="tool_activity",
    summary_template="Command completed (exit={exit_code})",
)
```

**Files to Update**:
- `src/soothe/tools/execution/events.py`
- `src/soothe/tools/file_ops/events.py`
- `src/soothe/tools/web_search/events.py`
- `src/soothe/tools/video/events.py`
- `src/soothe/tools/goals/events.py`
- `src/soothe/tools/datetime/events.py`
- `src/soothe/tools/code_edit/events.py`
- `src/soothe/tools/image/events.py`
- `src/soothe/tools/audio/events.py`
- `src/soothe/tools/data/events.py`

### Priority 2: Implement Subagent Dispatch Pattern (High)

**Impact**: Subagents don't show clear lifecycle, steps appear disconnected

#### Task 2.1: Add Dispatch/Completion Events to Subagents

**File**: `src/soothe/subagents/browser/events.py`

**Add Events**:
```python
class BrowserDispatchedEvent(SubagentEvent):
    """Browser subagent dispatched event."""

    type: Literal["soothe.subagent.browser.dispatched"] = "soothe.subagent.browser.dispatched"
    task: str = ""

    model_config = ConfigDict(extra="allow")


class BrowserCompletedEvent(SubagentEvent):
    """Browser subagent completed event."""

    type: Literal["soothe.subagent.browser.completed"] = "soothe.subagent.browser.completed"
    duration_ms: int = 0
    success: bool = True

    model_config = ConfigDict(extra="allow")


# Register events
register_event(
    BrowserDispatchedEvent,
    verbosity="subagent_progress",
    summary_template="Browser: {task}",
)
register_event(
    BrowserCompletedEvent,
    verbosity="subagent_progress",
    summary_template="Completed in {duration_ms}ms",
)
```

**Repeat for**: Claude, Research, Skillify, Weaver subagents

#### Task 2.2: Add Subagent Tracking to Processor State

**File**: `src/soothe/ux/core/processor_state.py`

**Add Field**:
```python
@dataclass
class ProcessorState:
    # ... existing fields ...

    # Track active subagents and their step events
    active_subagents: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
```

#### Task 2.3: Update Event Processor to Track Subagent Lifecycle

**File**: `src/soothe/ux/core/event_processor.py`

**Update `_handle_custom_event()`**:
```python
def _handle_custom_event(self, data: dict[str, Any], namespace: tuple[str, ...]) -> None:
    etype = data.get("type", "")

    # Track subagent dispatch
    if etype.endswith(".dispatched"):
        agent_name = etype.split(".")[2] if len(etype.split(".")) >= 3 else "unknown"
        subagent_id = f"{agent_name}:{data.get('task', '')[:30]}"
        self._state.active_subagents[subagent_id] = []

    # Track subagent steps
    if etype.endswith(".step") and self._state.active_subagents:
        # Find the most recent active subagent
        for subagent_id in reversed(self._state.active_subagents):
            self._state.active_subagents[subagent_id].append(data)
            break

    # Track subagent completion
    if etype.endswith(".completed") and self._state.active_subagents:
        # Find matching dispatch and remove
        for subagent_id in list(self._state.active_subagents.keys()):
            if subagent_id.split(":")[0] in etype:
                del self._state.active_subagents[subagent_id]
                break

    # ... rest of existing logic ...
```

### Priority 3: Migrate CLI to Registry Templates (High)

**Impact**: Adding events requires modifying CLI renderer, violates RFC

#### Task 3.1: Refactor CLI Progress Renderer

**File**: `src/soothe/ux/cli/progress.py`

**Current Approach**: Hardcoded `_build_summary()` with if/elif chains

**New Approach**: Use registry templates

```python
from soothe.core.event_catalog import REGISTRY

def render_progress_event(
    event_type: str,
    data: dict[str, Any],
    *,
    prefix: str | None = None,
    current_plan: Plan | None = None,
) -> None:
    """Render a soothe.* event using registry template.

    Args:
        event_type: Event type string.
        data: Event dict with 'type' key.
        prefix: Optional prefix for subagent namespace.
        current_plan: Current plan for status display.
    """
    if not event_type:
        event_type = data.get("type", "")
    if not event_type:
        return

    # Skip batch/step events (handled by renderer's plan update mechanism)
    if event_type in _SKIP_EVENTS:
        return

    # Try registry first
    meta = REGISTRY.get_meta(event_type)
    if meta and meta.summary_template:
        try:
            summary = meta.summary_template.format(**data)
            prefix_str = f"[{prefix}] " if prefix else ""
            label = _get_event_label(event_type)
            line = f"{prefix_str}[{label}] {summary}\n"
            sys.stderr.write(line)
            sys.stderr.flush()
            return
        except (KeyError, ValueError) as e:
            logger.debug("Failed to format template for %s: %s", event_type, e)

    # Fallback to special cases (plan, research, agentic)
    # Keep existing _build_summary logic for backward compatibility
    summary = _build_summary(event_type, data, current_plan)
    if not summary:
        return

    prefix_str = f"[{prefix}] " if prefix else ""
    label = _get_event_label(event_type)
    line = f"{prefix_str}[{label}] {summary}\n"

    sys.stderr.write(line)
    sys.stderr.flush()


def _get_event_label(event_type: str) -> str:
    """Get human-readable label for event type."""
    # Extract domain from event type
    segments = event_type.split(".")
    if len(segments) >= 2:
        domain = segments[1]
        if domain == "subagent" and len(segments) >= 3:
            return segments[2]  # e.g., "browser", "claude"
        return domain
    return "event"
```

### Priority 4: Add Display Helpers to CLI (Medium)

**Impact**: Inconsistent visual patterns between CLI and TUI

#### Task 4.1: Import and Use Display Helpers in CLI Renderer

**File**: `src/soothe/ux/cli/renderer.py`

**Add Imports**:
```python
from soothe.ux.tui.utils import DOT_COLORS, make_dot_line, make_tool_block
```

**Update `on_tool_call()`**:
```python
def on_tool_call(
    self,
    name: str,
    args: dict[str, Any],
    tool_call_id: str,
    *,
    is_main: bool,  # noqa: ARG002
) -> None:
    """Write tool call block to stderr in tree format.

    Args:
        name: Tool name.
        args: Parsed arguments.
        tool_call_id: Tool call identifier.
        is_main: True if from main agent.
    """
    if not should_show("protocol", self._verbosity):
        return

    self._ensure_newline()

    display_name = get_tool_display_name(name)
    args_str = format_tool_call_args(name, {"args": args})

    # Use display helper for consistency
    tool_block = make_tool_block(display_name, args_str, status="running")

    # Add double newline before tool for clear visual separation
    sys.stderr.write(f"\n\n{tool_block}\n")
    sys.stderr.flush()
    # Mark that stderr was just written
    self._state.stderr_just_written = True
```

### Priority 5: Implement Two-Level Tree for Tools (Medium)

**Impact**: Tool results don't show as children, flat display

#### Task 5.1: Track Tool Call Start Times

**File**: `src/soothe/ux/core/processor_state.py`

**Add Field**:
```python
@dataclass
class ProcessorState:
    # ... existing fields ...

    # Track tool call start times for duration calculation
    tool_call_start_times: dict[str, float] = field(default_factory=dict)
```

#### Task 5.2: Update Renderers to Track Duration

**File**: `src/soothe/ux/cli/renderer.py`

**Update `on_tool_call()`**:
```python
import time

def on_tool_call(self, name: str, args: dict[str, Any], tool_call_id: str, ...) -> None:
    # ... existing code ...

    # Track start time
    if tool_call_id:
        self._state.tool_call_start_times[tool_call_id] = time.time()
```

**Update `on_tool_result()`**:
```python
def on_tool_result(
    self,
    name: str,  # noqa: ARG002
    result: str,
    tool_call_id: str,
    *,
    is_error: bool,
    is_main: bool,  # noqa: ARG002
) -> None:
    """Write tool result to stderr in tree format."""
    if not should_show("protocol", self._verbosity):
        return

    self._ensure_newline()

    # Calculate duration
    duration_ms = 0
    if tool_call_id and tool_call_id in self._state.tool_call_start_times:
        start_time = self._state.tool_call_start_times.pop(tool_call_id)
        duration_ms = int((time.time() - start_time) * 1000)

    # Format as child line with duration
    icon = "✗" if is_error else "✓"
    result_line = f"  └ {icon} {result}"
    if duration_ms > 0:
        result_line += f" ({duration_ms}ms)"

    sys.stderr.write(result_line + "\n")
    sys.stderr.flush()
```

## Testing Plan

### Test 1: Verbosity Filtering
```bash
# Normal mode - should NOT show tool events
soothe run "list files in current directory"

# Verbose mode - should show tool events
soothe run --verbose "list files in current directory"
```

**Expected**:
- Normal: Only see assistant text, no tool call details
- Verbose: See tool calls with args and results

### Test 2: Subagent Display
```bash
soothe run "browse to example.com and extract the page title"
```

**Expected**:
```
⚙ Browser: browse to example.com
  └ ✓ Step 1: navigate | https://example.com
  └ ✓ Step 2: extract | title
  └ ✓ Completed in 12.3s
```

### Test 3: Tool Duration Display
```bash
soothe run --verbose "read the README file"
```

**Expected**:
```
⚙ read_file("README.md")
  └ ✓ File content (234ms)
```

### Test 4: Registry Extensibility
```python
# Add new event in plugin
from soothe.core.base_events import ToolEvent
from soothe.core.event_catalog import register_event

class MyCustomEvent(ToolEvent):
    type: Literal["soothe.tool.my.custom"] = "soothe.tool.my.custom"
    data: str = ""

register_event(
    MyCustomEvent,
    verbosity="tool_activity",
    summary_template="Custom: {data}",
)

# Emit event - should display automatically in both CLI and TUI
```

## Verification

Run the verification script after all changes:
```bash
./scripts/verify_finally.sh
```

This will:
- Check code formatting
- Run linting (zero errors required)
- Run all unit tests

## Rollback Plan

If issues arise:
1. Revert display_policy.py changes - tool events revert to visible in normal mode
2. Remove subagent tracking - steps appear disconnected but system still functions
3. Revert CLI registry changes - CLI falls back to hardcoded logic
4. Remove display helper imports - CLI reverts to string formatting
5. Remove duration tracking - tool results show without duration

## Dependencies

- RFC-0020 Event Display Architecture
- RFC-0019 Unified Event Processing
- IG-064 Unified Display Policy
- IG-066 Subagent Event Display Fix

## Timeline

- **Priority 1**: 1-2 hours (critical, affects all users)
- **Priority 2**: 2-3 hours (high, improves subagent UX)
- **Priority 3**: 2-3 hours (high, enables extensibility)
- **Priority 4**: 1 hour (medium, visual consistency)
- **Priority 5**: 1-2 hours (medium, better feedback)

**Total**: 7-11 hours

## Success Metrics

- ✅ All 6 RFC-0020 success criteria met
- ✅ 100% of tool events have correct verbosity
- ✅ All subagents have dispatch/completion events
- ✅ CLI uses registry for all event display
- ✅ Visual consistency between CLI and TUI
- ✅ Duration shown on all tool results
- ✅ All tests pass

---

*This implementation guide addresses the gaps identified in the RFC-0020 compliance review.*