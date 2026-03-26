# RFC-0019: Unified Event Processing Architecture

| Field | Value |
|-------|-------|
| **Status** | Implemented |
| **Created** | 2026-03-26 |
| **Author** | Soothe Team |
| **Supersedes** | - |
| **Related** | RFC-0003 (TUI), RFC-0015 (Event Rendering) |

## Summary

Unify CLI and TUI event processing with a single `EventProcessor` class that handles all event routing, state management, and filtering. Mode-specific display is delegated to `RendererProtocol` implementations (`CliRenderer`, `TuiRenderer`).

## Motivation

Prior to this RFC, CLI and TUI modes had separate event processing implementations:
- `daemon_runner.py` (~355 lines) for CLI headless mode
- `event_processors.py` (~600 lines) for TUI mode
- `cli_event_renderer.py` (~535 lines) for CLI rendering
- `tui_event_renderer.py` (~600 lines) for TUI rendering

This resulted in:
- ~60% code duplication across modes
- Inconsistent behavior between CLI and TUI
- Difficult maintenance when adding new event types
- Bug fixes needed in multiple places

## Design

### Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    EventProcessor                        │
│  - Unified event routing                                │
│  - State management (deduplication, streaming)          │
│  - Verbosity filtering                                  │
│  - Plan state tracking                                  │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                 RendererProtocol                         │
│  Abstract callback interface:                           │
│  - on_assistant_text()                                  │
│  - on_tool_call() / on_tool_result()                   │
│  - on_status_change()                                   │
│  - on_error()                                           │
│  - on_progress_event()                                  │
│  - on_plan_created/started/completed()                  │
│  - on_turn_end()                                        │
└─────────────────────┬───────────────────────────────────┘
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│   CliRenderer   │     │   TuiRenderer   │
│  - stdout text  │     │  - Rich panels  │
│  - stderr tools │     │  - Streaming    │
│  - Tree format  │     │  - Plan tree    │
└─────────────────┘     └─────────────────┘
```

### Key Design Decisions

1. **Callback Hooks Pattern**: Processor calls abstract methods; renderers implement display logic
2. **Hybrid Callback Granularity**: ~8 core required callbacks + optional fine-grained hooks
3. **Split State Ownership**: Processor owns processing state; renderers own display state
4. **Clean Cut Migration**: No backward compatibility shims

### State Management

**ProcessorState** (owned by EventProcessor):
- `seen_message_ids: set[str]` - Message deduplication
- `pending_tool_calls: dict` - Streaming tool arg accumulation (IG-053)
- `name_map: dict[str, str]` - Subagent namespace display names
- `current_plan: Plan | None` - Active plan state
- `thread_id: str` - Current thread identifier
- `multi_step_active: bool` - Suppress step text, show final report only

**Renderer-specific state** (owned by each renderer):
- CLI: `needs_stdout_newline`, `full_response`
- TUI: `streaming_text_buffer`, `streaming_active`, `current_tool_calls`

### RendererProtocol Interface

```python
class RendererProtocol(Protocol):
    # Core callbacks (required)
    def on_assistant_text(self, text: str, *, is_main: bool, is_streaming: bool) -> None: ...
    def on_tool_call(self, name: str, args: dict, tool_call_id: str, *, is_main: bool) -> None: ...
    def on_tool_result(self, name: str, result: str, tool_call_id: str, *, is_error: bool, is_main: bool) -> None: ...
    def on_status_change(self, state: str) -> None: ...
    def on_error(self, error: str, *, context: str | None = None) -> None: ...
    def on_progress_event(self, event_type: str, data: dict, *, namespace: tuple[str, ...]) -> None: ...
    
    # Optional fine-grained hooks
    def on_plan_created(self, plan: Plan) -> None: ...
    def on_plan_step_started(self, step_id: str, description: str) -> None: ...
    def on_plan_step_completed(self, step_id: str, success: bool, duration_ms: int) -> None: ...
    def on_turn_end(self) -> None: ...
```

## File Structure

```
src/soothe/ux/
├── core/
│   ├── __init__.py          # Export EventProcessor, RendererProtocol
│   ├── renderer_protocol.py # Abstract callback interface
│   ├── processor_state.py   # ProcessorState dataclass
│   └── event_processor.py   # Unified EventProcessor class
├── cli/
│   ├── cli_renderer.py      # CliRenderer implementation
│   └── execution/
│       └── daemon_runner.py # Refactored to use EventProcessor
└── tui/
    ├── tui_renderer.py      # TuiRenderer implementation
    └── app.py               # Refactored to use EventProcessor
```

### Deleted Files

- `src/soothe/ux/tui/event_processors.py` - Replaced by EventProcessor
- `src/soothe/ux/tui/tui_event_renderer.py` - Replaced by TuiRenderer
- `src/soothe/ux/cli/rendering/cli_event_renderer.py` - Replaced by CliRenderer

## Usage

### CLI Mode

```python
renderer = CliRenderer(verbosity="normal")
processor = EventProcessor(renderer, verbosity="normal")

# In event loop:
processor.process_event(event)
```

### TUI Mode

```python
renderer = TuiRenderer(
    on_panel_write=panel.append_entry,
    on_panel_update_last=panel.update_last_entry,
    on_status_update=update_status_bar,
    on_plan_refresh=refresh_plan_tree,
)
processor = EventProcessor(renderer, verbosity="normal")

# In event loop:
processor.process_event(event)
# Sync state from processor
state.thread_id = processor.thread_id
```

## Testing

Unit tests verify:
- Event routing to correct callbacks
- State management (deduplication, streaming accumulation)
- Plan event handling
- Verbosity-based filtering
- Thread change session clearing

See `tests/unit/test_event_processor.py`.

## Migration

This is a clean-cut migration with no backward compatibility:
1. New unified components created
2. CLI/TUI refactored to use new components
3. Old duplicate code deleted
4. Tests updated to match new output format

## Metrics

| Metric | Before | After |
|--------|--------|-------|
| Total event processing LOC | ~2090 | ~900 |
| Code duplication | ~60% | ~5% |
| Files for event handling | 4 | 3 |
