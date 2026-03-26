# IG-064: Unified Display Policy and Internal Event Filtering

**Date**: 2026-03-26  
**Status**: Completed  
**Related**: RFC-0015 (Event Classification), RFC-0019 (Unified Event Processing)

## Overview

This implementation guide documents the creation of a unified display policy system for event filtering and content processing in both CLI and TUI modes. The key innovation is replacing fragile regex-based content filtering with event-based internal context tracking and JSON parsing.

## Problem Statement

### Previous Issues

1. **Regex-based filtering was unreliable**: Used complex regex patterns to detect internal LLM JSON responses, which failed on edge cases and nested JSON
2. **Duplicated filtering logic**: `message_processing.py` had ~130 lines of regex patterns duplicated across the codebase
3. **No clear separation of concerns**: Display filtering logic scattered across multiple modules
4. **Internal LLM responses leaked to CLI output**: Research tool's intermediate JSON responses (`sub_questions`, `queries`, `is_sufficient`) appeared in user-facing output
5. **Confused LLM meta-responses**: When research engine had empty data, LLM generated confused responses like "I notice that no sub-questions were actually provided..."
6. **Inconsistent event separation**: Events ran together without clear visual separation

## Solution Architecture

### Core Design Principles

1. **Event-based filtering over content-based filtering**: Mark messages as internal at the source, don't try to detect internal content at display layer
2. **JSON parsing instead of regex**: Use `json.loads()` for reliable detection of internal JSON keys
3. **Centralized policy**: Single `DisplayPolicy` class controls all filtering decisions
4. **Internal context tracking**: State-based suppression during internal LLM calls

### New Components

#### 1. DisplayPolicy Module (`src/soothe/ux/core/display_policy.py`)

**Purpose**: Unified policy for event filtering and content processing

**Key Classes**:
- `DisplayPolicy`: Main policy class with filtering methods
- `EventCategory`: Enum for event classification (ASSISTANT_TEXT, PROTOCOL, INTERNAL, etc.)

**Key Methods**:
- `should_show_event(event_type, data, namespace)`: Determine if event should be displayed
- `filter_content(text)`: Filter internal JSON, confused responses, search tags
- `enter_internal_context(context_type)` / `exit_internal_context()`: Track internal state
- `_is_internal_json_content(content)`: Check if JSON contains internal keys using set intersection

**Constants**:
- `INTERNAL_JSON_KEYS`: Keys that indicate internal research responses (`sub_questions`, `queries`, `is_sufficient`, `knowledge_gap`, `follow_up_queries`)
- `INTERNAL_EVENT_TYPES`: Event types never shown (`soothe.tool.research.internal_llm`)
- `SKIP_EVENT_TYPES`: Events handled by plan update mechanism (batch/step events)

#### 2. Internal LLM Response Event (`src/soothe/tools/research/events.py`)

**New Event Type**: `ResearchInternalLLMResponseEvent`

**Purpose**: Wrap internal LLM responses as events with "internal" verbosity so they're filtered by the event system

**Event Type**: `soothe.tool.research.internal_llm`

**Fields**:
- `response_type`: Type of internal response ("analysis", "queries", "reflection")

**Registration**:
```python
register_event(
    ResearchInternalLLMResponseEvent,
    verbosity="internal",  # NEVER shown at any verbosity level
    summary_template="Internal: {response_type}",
)
```

#### 3. Progress Verbosity Enhancement (`src/soothe/ux/core/progress_verbosity.py`)

**Added**: `"internal"` category to `ProgressCategory` type

**Behavior**: Internal category is NEVER shown at any verbosity level (even "debug")

```python
def should_show(category: ProgressCategory, verbosity: VerbosityLevel) -> bool:
    # Internal category is NEVER shown at any verbosity level
    if category == "internal":
        return False
    # ... rest of logic
```

#### 4. Inquiry Engine Integration (`src/soothe/inquiry/engine.py`)

**Modified**: Emit internal events before LLM calls in research engine

**Changes**:
- `analyze_topic_node`: Emits `ResearchInternalLLMResponseEvent(response_type="analysis")` before LLM call
- `generate_queries_node`: Emits `ResearchInternalLLMResponseEvent(response_type="queries")` before LLM call
- `reflect_node`: Emits `ResearchInternalLLMResponseEvent(response_type="reflection")` before LLM call

**Effect**: Sets internal context flag, suppressing assistant text from research subagent

#### 5. Event Processor Integration (`src/soothe/ux/core/event_processor.py`)

**Modified**: Track internal context based on events

**Changes**:
- Import `TOOL_RESEARCH_INTERNAL_LLM` constant
- In `_handle_custom_event()`:
  - When receiving `TOOL_RESEARCH_INTERNAL_LLM`: Set `internal_context_active = True`
  - When receiving other research events: Set `internal_context_active = False`
- In `_handle_ai_message()`: Suppress assistant text during internal context for non-main agent

#### 6. Processor State Enhancement (`src/soothe/ux/core/processor_state.py`)

**Added**: `internal_context_active: bool = False` field

**Purpose**: Track when in internal processing context to suppress internal LLM responses

#### 7. CLI Renderer Separator Newlines (`src/soothe/ux/cli/renderer.py`)

**Added**: Separator newline before each event for clearer visual separation

**Changes**:
- `on_tool_call()`: `\n⚙ {display_name}{args_str}\n`
- `on_progress_event()`: `\n` before rendering event
- `on_plan_created()`: `\n[plan] ● {goal}...`
- `_render_plan_update()`: `\n[plan] ● {goal}...`
- `on_error()`: `\n{prefix}ERROR: {error}\n` (newly added)

#### 8. Message Processing Simplification (`src/soothe/ux/core/message_processing.py`)

**Removed**: ~130 lines of redundant regex-based filtering logic

**Before**:
- `_INTERNAL_JSON_KEYS` tuple
- `_JSON_CODE_BLOCK_PATTERN` regex
- `_PLAIN_JSON_PATTERN` regex
- `_INTERNAL_META_RESPONSE_PATTERNS` list (5 regex patterns)
- Complex filtering loops in `strip_internal_tags()`

**After**:
```python
def strip_internal_tags(text: str) -> str:
    from soothe.ux.core.display_policy import DisplayPolicy
    
    # Use unified display policy for content filtering
    policy = DisplayPolicy()
    return policy.filter_content(text)
```

**Benefits**:
- Single source of truth for content filtering
- JSON parsing instead of regex (more reliable)
- Easier to maintain and extend

## Implementation Details

### Content Filtering Logic

The `DisplayPolicy.filter_content()` method applies multiple filters in sequence:

1. **JSON Code Block Filtering** (`_filter_json_code_blocks`):
   - Finds ```json ... ``` blocks
   - Parses JSON content with `json.loads()`
   - Checks if parsed dict contains any `INTERNAL_JSON_KEYS`
   - Removes entire block if internal

2. **Plain JSON Filtering** (`_filter_plain_json`):
   - Finds JSON objects at line start or after whitespace
   - Uses brace counting to find matching closing brace
   - Parses and checks for internal keys
   - Removes if internal

3. **Confused Response Filtering** (`_filter_confused_responses`):
   - Detects LLM meta-responses about missing data
   - Uses keyword-based detection (not regex):
     - Primary: "sub-questions", "sub_questions", "section appears to be empty", "once you share them"
     - Secondary: "provide", "share", "empty", "not provided", "json format"
   - Filters line-by-line to remove confused responses

4. **Search Data Tag Filtering** (`_filter_search_data_tags`):
   - Removes `<search_data>...</search_data>` blocks
   - Removes synthesis instructions

5. **Whitespace Normalization** (`_normalize_whitespace`):
   - Normalizes 2+ spaces to single space
   - Normalizes 3+ newlines to 2 newlines

### Internal Context Flow

```
Research Engine (inquiry/engine.py)
    ↓
Emits ResearchInternalLLMResponseEvent
    ↓
Event Processor (_handle_custom_event)
    ↓
Sets state.internal_context_active = True
    ↓
AI Message Handler (_handle_ai_message)
    ↓
Suppresses non-main agent text if internal_context_active
    ↓
Research Engine emits non-internal event (e.g., ResearchAnalyzeEvent)
    ↓
Event Processor sets internal_context_active = False
    ↓
Normal text display resumes
```

## Testing

### Unit Tests Passed
- `test_message_processing.py`: 14 tests
- `test_event_processor.py`: 13 tests
- `test_progress_rendering.py`: 8 tests
- Total: 35 tests, all passing

### Manual Testing
Verified with actual research queries:
- Internal JSON blocks (`{"sub_questions": [...]}`) are filtered
- Confused LLM responses are filtered
- Events have clear separator newlines
- Plan status updates display correctly

## Files Modified

1. **Created**: `src/soothe/ux/core/display_policy.py` (488 lines)
2. **Modified**: `src/soothe/ux/core/__init__.py` (added exports)
3. **Modified**: `src/soothe/ux/core/progress_verbosity.py` (added "internal" category)
4. **Modified**: `src/soothe/tools/research/events.py` (added ResearchInternalLLMResponseEvent)
5. **Modified**: `src/soothe/inquiry/engine.py` (emit internal events)
6. **Modified**: `src/soothe/ux/core/event_processor.py` (track internal context)
7. **Modified**: `src/soothe/ux/core/processor_state.py` (added internal_context_active)
8. **Modified**: `src/soothe/ux/cli/renderer.py` (separator newlines, type updates)
9. **Modified**: `src/soothe/ux/core/message_processing.py` (removed ~130 lines of regex code)

## Benefits

### Reliability
- JSON parsing instead of regex: No more fragile pattern matching
- Event-based filtering: Clear intent at source, not guessing at display layer
- Centralized policy: Single source of truth for all filtering decisions

### Maintainability
- Removed 130+ lines of duplicated regex patterns
- Clear separation of concerns: DisplayPolicy handles all filtering
- Easy to extend: Add new internal keys or event types to constants

### User Experience
- No more internal JSON leaking to CLI output
- No more confused LLM meta-responses
- Clear visual separation between events with separator newlines
- Consistent behavior between CLI and TUI modes

### Architecture
- Follows RFC-0015 event classification principles
- Aligns with RFC-0019 unified event processing
- Extensible for future internal event types
- Type-safe with `VerbosityLevel` type alias

## Future Enhancements

1. **TUI Integration**: Apply DisplayPolicy to TUI renderer for consistency
2. **Configurable Filtering**: Allow users to customize what internal content to show in debug mode
3. **Event Metadata**: Add more context to internal events for better debugging
4. **Performance**: Cache DisplayPolicy instances instead of creating new ones

## Migration Notes

### For Plugin Developers
- Internal tool responses should emit events with `verbosity="internal"` to be filtered
- Use `DisplayPolicy` for any custom content filtering in plugins
- The `strip_internal_tags()` function now delegates to `DisplayPolicy.filter_content()`

### For Core Developers
- Add new internal JSON keys to `INTERNAL_JSON_KEYS` in `display_policy.py`
- Add new internal event types to `INTERNAL_EVENT_TYPES`
- Use `enter_internal_context()` / `exit_internal_context()` for internal LLM calls
- Prefer event-based filtering over content-based filtering

## References

- RFC-0015: Event Classification and Verbosity
- RFC-0019: Unified Event Processing Architecture
- IG-053: CLI/TUI Event Progress Implementation
- IG-061: Unified Event Processing
