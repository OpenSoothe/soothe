# IG-054: Event Constants Self-Containment and Consolidation

**Implementation Guide**
**Created**: 2026-03-25
**Status**: Completed
**Related**: RFC-600, IG-052

## Summary

This guide documents two refactorings that completed the self-containment principle:
1. Moved tool and subagent event type string constants from `core/events.py` to their respective module `events.py` files
2. Consolidated all core event definitions into `core/event_catalog.py` by merging and deleting `core/events.py`

## Motivation

### Problem

After IG-052, event **classes** were properly located in their respective modules with self-registration. However, event **string constants** were still defined centrally in `core/events.py`, creating coupling between core and tool/subagent modules.

**Violations of Self-Contained Principle**:
1. Adding a new tool required modifying `core/events.py` to add constants
2. Developers had to look in TWO places to understand a tool's events (module for classes, core for constants)
3. Third-party plugins couldn't be fully self-contained without modifying core files
4. Contradicted RFC-600's goal of zero-coupling extensibility

### Solution

Move all tool and subagent event type string constants from `core/events.py` to their respective module `events.py` files, alongside the event class definitions.

## Changes Made

### Phase 1: Added Constants to Module Event Files

Each tool/subagent with events now exports both event classes and constants:

**Example: `tools/web_search/events.py`**
```python
# Event classes (already present)
class WebsearchSearchStartedEvent(ToolEvent):
    type: Literal["soothe.tool.websearch.search_started"] = "soothe.tool.websearch.search_started"
    # ...

# Event type constants (NEW)
TOOL_WEBSEARCH_SEARCH_STARTED = "soothe.tool.websearch.search_started"
TOOL_WEBSEARCH_SEARCH_COMPLETED = "soothe.tool.websearch.search_completed"
TOOL_WEBSEARCH_SEARCH_FAILED = "soothe.tool.websearch.search_failed"
TOOL_WEBSEARCH_CRAWL_STARTED = "soothe.tool.websearch.crawl_started"
TOOL_WEBSEARCH_CRAWL_COMPLETED = "soothe.tool.websearch.crawl_completed"
TOOL_WEBSEARCH_CRAWL_FAILED = "soothe.tool.websearch.crawl_failed"

__all__ = [
    # Constants first (alphabetically)
    "TOOL_WEBSEARCH_CRAWL_COMPLETED",
    "TOOL_WEBSEARCH_CRAWL_FAILED",
    "TOOL_WEBSEARCH_CRAWL_STARTED",
    "TOOL_WEBSEARCH_SEARCH_COMPLETED",
    "TOOL_WEBSEARCH_SEARCH_FAILED",
    "TOOL_WEBSEARCH_SEARCH_STARTED",
    # Event classes (alphabetically)
    "WebsearchCrawlCompletedEvent",
    "WebsearchCrawlFailedEvent",
    "WebsearchCrawlStartedEvent",
    "WebsearchSearchCompletedEvent",
    "WebsearchSearchFailedEvent",
    "WebsearchSearchStartedEvent",
]
```

**Files Modified**:
- `tools/web_search/events.py` - Added 6 constants
- `tools/research/events.py` - Added 10 constants
- `subagents/browser/events.py` - Added 2 constants
- `subagents/claude/events.py` - Added 3 constants
- `subagents/skillify/events.py` - Added 8 constants
- `subagents/weaver/events.py` - Added 14 constants

### Phase 2: Updated Imports in Consumer Files

Changed imports from `core.events` to module-specific `events.py`:

**Before**:
```python
from soothe.core.events import (
    TOOL_WEBSEARCH_SEARCH_STARTED,
    TOOL_WEBSEARCH_SEARCH_COMPLETED,
    TOOL_WEBSEARCH_SEARCH_FAILED,
)
```

**After**:
```python
from soothe.tools.web_search.events import (
    TOOL_WEBSEARCH_SEARCH_STARTED,
    TOOL_WEBSEARCH_SEARCH_COMPLETED,
    TOOL_WEBSEARCH_SEARCH_FAILED,
)
```

**Files Updated**:
- `tools/_internal/wizsearch/search.py`
- `tools/_internal/wizsearch/crawl.py`
- `ux/tui/tui_event_renderer.py`
- `ux/tui/renderers.py`
- `ux/cli/rendering/cli_event_renderer.py`

### Phase 3: Removed Constants from Core

**Removed from `core/events.py`**:
- Lines 82-103: Websearch tool constants (6)
- Lines 94-103: Research tool constants (10)
- Lines 106-146: Subagent constants (27 total)
- **Total**: 43 tool/subagent constants removed

**Kept in `core/events.py`**:
- Lifecycle events (THREAD_CREATED, ITERATION_STARTED, etc.)
- Protocol events (CONTEXT_PROJECTED, PLAN_STEP_STARTED, etc.)
- Output events (CHITCHAT_RESPONSE, FINAL_REPORT)
- Error events (ERROR)
- Plugin events (PLUGIN_LOADED, PLUGIN_FAILED, etc.)

These are truly core events that belong in the core module.

### Phase 4: Consolidated Core Event Files

**Merged `core/events.py` into `core/event_catalog.py`**:

The separate `events.py` file was redundant after Phase 3. All core event constants and classes are now consolidated in a single location.

**Added to `event_catalog.py`**:
- Event type string constants (lifecycle, protocol, output, error, plugin)
- Type aliases: `StreamChunk`, `STREAM_CHUNK_LEN`, `MSG_PAIR_LEN`
- Helper function: `custom_event()`

**Updated imports across codebase** (10 files):
- `daemon/_handlers.py`
- `ux/cli/execution/daemon_runner.py`
- `ux/cli/execution/standalone_runner.py`
- `ux/cli/rendering/cli_event_renderer.py`
- `ux/tui/tui_event_renderer.py`
- `ux/tui/event_processors.py`
- `ux/shared/message_processing.py`
- `utils/error_format.py`
- `tests/unit/test_fixes.py`
- Documentation files (IG-054.md, RFC-600-plugin-extension-system.md)

**Deleted**:
- `src/soothe/core/events.py` - No longer needed

**Result**:
- Single source of truth for core events: `soothe.core.event_catalog`
- Cleaner module structure
- No more confusion between `events.py` and `event_catalog.py`

## Pattern for Third-Party Plugins

Third-party plugins should follow this self-contained pattern:

### Step 1: Define Event Classes

Create `events.py` in your plugin module:

```python
# my_plugin/events.py
from __future__ import annotations

from typing import Literal
from pydantic import ConfigDict
from soothe.core.base_events import SootheEvent

class MyCustomEvent(SootheEvent):
    """My plugin custom event."""

    type: Literal["soothe.plugin.my_plugin.custom"] = "soothe.plugin.my_plugin.custom"
    data: str = ""

    model_config = ConfigDict(extra="allow")
```

### Step 2: Register Events

```python
# my_plugin/events.py (continued)
from soothe.core.event_catalog import register_event  # noqa: E402

register_event(
    MyCustomEvent,
    summary_template="Custom: {data}",
)
```

### Step 3: Export Constants

```python
# my_plugin/events.py (continued)
# Event type constants for convenient imports
MY_PLUGIN_CUSTOM_EVENT = "soothe.plugin.my_plugin.custom"

__all__ = [
    "MY_PLUGIN_CUSTOM_EVENT",
    "MyCustomEvent",
]
```

### Step 4: Use in Implementation

```python
# my_plugin/implementation.py
from my_plugin.events import MY_PLUGIN_CUSTOM_EVENT, MyCustomEvent
from soothe.utils.progress import emit_progress

# Type-safe emission
yield emit_progress(MyCustomEvent(data="test").to_dict())

# Or use constant for comparisons
if event_type == MY_PLUGIN_CUSTOM_EVENT:
    # Handle event
    pass
```

## Benefits

1. **True Self-Containment**: Each module owns ALL aspects of its events (classes + constants)
2. **Zero Coupling**: Adding new tools/subagents requires ZERO changes to core files
3. **Plugin Extensibility**: Third-party plugins can be fully self-contained
4. **Developer Clarity**: Developers look in ONE place for a module's events
5. **RFC-600 Compliance**: Fully aligned with the self-contained principle

## Verification

All changes verified with:
```bash
./scripts/verify_finally.sh
```

**Results**:
- ✅ Code formatting check passed
- ✅ Linting passed (zero errors)
- ✅ All 900+ unit tests passed
- ✅ Event emission still works correctly
- ✅ TUI/CLI rendering unchanged

## Before vs After

### Before (Coupled)

```
core/events.py
├── TOOL_WEBSEARCH_SEARCH_STARTED = "..."
├── TOOL_RESEARCH_ANALYZE = "..."
├── SUBAGENT_BROWSER_STEP = "..."
└── ... (43 tool/subagent constants)

tools/web_search/events.py
├── class WebsearchSearchStartedEvent(ToolEvent)
└── ... (6 event classes)

# Adding a new tool requires:
# 1. Create tools/my_tool/events.py with event classes
# 2. EDIT core/events.py to add constants
# 3. Update imports in consumers
```

### After (Self-Contained)

```
core/events.py
├── THREAD_CREATED = "..."
├── CONTEXT_PROJECTED = "..."
└── ... (core events only)

tools/web_search/events.py
├── TOOL_WEBSEARCH_SEARCH_STARTED = "..."
├── TOOL_WEBSEARCH_SEARCH_COMPLETED = "..."
└── ... (ALL 6 constants + 6 event classes)

# Adding a new tool requires:
# 1. Create tools/my_tool/events.py with event classes + constants
# 2. Register events with register_event()
# 3. Import from my_tool.events in consumers
# NO core modifications needed!
```

## Related Documentation

- [RFC-600: Plugin Extension Specification](../specs/RFC-600-plugin-extension-system.md)
- [IG-052: Event System Optimization](052-rfc0018-event-system-optimization.md)
- [CLAUDE.md](../../CLAUDE.md) - Updated with event constant location guidelines

## Lessons Learned

1. **Self-containment requires diligence**: Even after moving event classes, constants can still create coupling
2. **Grep is your friend**: Use `grep` to find all consumers before refactoring
3. **Incremental refactoring**: IG-052 moved classes, IG-054 moved constants - staged approach reduces risk
4. **Test early and often**: Run verification script after each major change
5. **Document patterns**: Implementation guides help future developers follow best practices

## Conclusion

This refactoring completes the self-containment principle for Soothe's event system. All tool and subagent modules now fully own their events without any coupling to the core module. Third-party plugins can follow the same pattern to create fully self-contained extensions.

The zero-coupling architecture ensures that the plugin ecosystem can grow without requiring modifications to core framework files, fully realizing RFC-600's extensibility goals.