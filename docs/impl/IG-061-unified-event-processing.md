# IG-061: Unified Event Processing Implementation

| Field | Value |
|-------|-------|
| **RFC** | RFC-0019 |
| **Status** | Completed |
| **Created** | 2026-03-26 |

## Overview

Implementation guide for RFC-0019 Unified Event Processing Architecture. This guide covers the creation of the unified `EventProcessor` class with `RendererProtocol` callback interface, and refactoring of CLI/TUI to use the new architecture.

## Implementation Steps

### Step 1: Create RendererProtocol

**File:** `src/soothe/ux/core/renderer_protocol.py`

Abstract callback interface defining how CLI/TUI render events:
- Core callbacks: `on_assistant_text`, `on_tool_call`, `on_tool_result`, `on_status_change`, `on_error`, `on_progress_event`
- Optional hooks: `on_plan_created`, `on_plan_step_started`, `on_plan_step_completed`, `on_turn_end`

### Step 2: Create ProcessorState

**File:** `src/soothe/ux/core/processor_state.py`

Dataclass for internal processor state:
- `seen_message_ids: set[str]` - Message deduplication
- `pending_tool_calls: dict` - Streaming tool arg accumulation
- `name_map: dict[str, str]` - Subagent namespace display names
- `current_plan: Plan | None` - Active plan state
- `thread_id: str` - Current thread identifier
- `multi_step_active: bool` - Multi-step plan flag

### Step 3: Create EventProcessor

**File:** `src/soothe/ux/core/event_processor.py`

Unified event processing logic:
- Routes events to appropriate handlers based on type
- Manages state (deduplication, streaming accumulation)
- Applies verbosity filtering
- Calls renderer callbacks

Key methods:
- `process_event(event)` - Main entry point
- `_handle_status(event)` - Status changes
- `_handle_stream_event(event)` - Messages and custom events
- `_handle_messages(data, namespace)` - AI/Tool messages
- `_handle_custom_event(data, namespace)` - Protocol events

### Step 4: Update Core Package Exports

**File:** `src/soothe/ux/core/__init__.py`

Export new classes:
```python
from soothe.ux.core.event_processor import EventProcessor
from soothe.ux.core.processor_state import ProcessorState
from soothe.ux.core.renderer_protocol import RendererProtocol
```

### Step 5: Create CliRenderer

**File:** `src/soothe/ux/cli/cli_renderer.py`

CLI-specific rendering implementation:
- `on_assistant_text` → stdout (streaming)
- `on_tool_call` → stderr (tree format with ⚙ icon)
- `on_tool_result` → stderr (tree child with ✓/✗)
- `on_progress_event` → delegates to `render_progress_event`

### Step 6: Create TuiRenderer

**File:** `src/soothe/ux/tui/tui_renderer.py`

TUI-specific rendering implementation:
- `on_assistant_text` → Rich panel with live streaming updates
- `on_tool_call` → Panel block with status indicators
- `on_tool_result` → Panel block with result summary
- `on_plan_created/started/completed` → Refresh plan tree widget

### Step 7: Refactor daemon_runner.py

**File:** `src/soothe/ux/cli/execution/daemon_runner.py`

Replace inline event processing with:
```python
renderer = CliRenderer(verbosity=verbosity)
processor = EventProcessor(renderer, verbosity=verbosity)

# In event loop:
processor.process_event(event)
```

### Step 8: Refactor app.py

**File:** `src/soothe/ux/tui/app.py`

Replace `process_daemon_event` calls with:
```python
# In on_mount or _connect_and_listen (lazy init):
self._renderer = TuiRenderer(
    on_panel_write=self._on_panel_write,
    on_panel_update_last=self._on_panel_update_last,
    on_status_update=self._update_status,
    on_plan_refresh=self._refresh_plan,
)
self._processor = EventProcessor(self._renderer, verbosity=self._progress_verbosity)

# In event loop:
self._processor.process_event(event)
# Sync state from processor
self._state.thread_id = self._processor.thread_id
```

### Step 9: Delete Obsolete Files

Remove:
- `src/soothe/ux/tui/event_processors.py`
- `src/soothe/ux/tui/tui_event_renderer.py`
- `src/soothe/ux/cli/rendering/cli_event_renderer.py`

### Step 10: Create Unit Tests

**File:** `tests/unit/test_event_processor.py`

Test cases:
- ProcessorState initialization and methods
- Status event handling (thread_id updates, on_turn_end)
- Error event routing
- Plan event handling (creates Plan, sets multi_step_active)
- Message deduplication
- Verbosity filtering

## Verification

Run unit tests:
```bash
uv run pytest tests/unit/test_event_processor.py -v
uv run pytest tests/unit/ --ignore=tests/unit/subagents -q
```

Expected: All 937+ tests pass.

## Files Changed

### New Files
- `src/soothe/ux/core/renderer_protocol.py`
- `src/soothe/ux/core/processor_state.py`
- `src/soothe/ux/core/event_processor.py`
- `src/soothe/ux/cli/cli_renderer.py`
- `src/soothe/ux/tui/tui_renderer.py`
- `tests/unit/test_event_processor.py`

### Modified Files
- `src/soothe/ux/core/__init__.py`
- `src/soothe/ux/cli/execution/daemon_runner.py`
- `src/soothe/ux/tui/app.py`
- `src/soothe/ux/cli/rendering/progress_renderer.py`
- `src/soothe/ux/tui/renderers.py`
- `tests/unit/test_fixes.py`
- `tests/unit/test_progress_rendering.py`

### Deleted Files
- `src/soothe/ux/tui/event_processors.py`
- `src/soothe/ux/tui/tui_event_renderer.py`
- `src/soothe/ux/cli/rendering/cli_event_renderer.py`

## Metrics

| Metric | Before | After |
|--------|--------|-------|
| Event processing LOC | ~2090 | ~900 |
| Code duplication | ~60% | ~5% |
| Files for event handling | 4 | 3 |
