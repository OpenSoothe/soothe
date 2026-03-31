# IG-076: CLI Output Formatting Optimization

**Status**: In Progress
**Created**: 2026-03-27
**Related RFCs**: RFC-501 (Event Display Architecture)

## Context and Motivation

### Problem Statement

The CLI output exhibited three formatting bugs that degraded user experience:

1. **Duplicated checkmarks**: Tool results showed `✓ ✓ Found 1 file` instead of `✓ Found 1 file`
2. **Markdown concatenation**: Headers and text were joined without spaces: `# Report## Overview`
3. **Missing whitespace**: Numbers appeared directly after colons: `**File Size:**5,599 bytes`

### Root Causes

**Bug 1 (Duplicated Checkmarks)**:
- `standalone._emit_result()` hardcoded `✓` prefix
- `ToolBrief.to_display()` already included semantic icon (`✓`, `✗`, `⚠`)
- Result: Double icon display

**Bugs 2-3 (Whitespace Issues)**:
- Content filtering removed blocks (JSON, `<search_data>`) via string concatenation
- No whitespace context preservation when joining segments
- Adjacent text merged without spacing

### Architectural Insight

Investigation revealed:
- **JSON internal keys** (`sub_questions`, etc.): Already filtered at **event level** via `ResearchInternalLLMResponseEvent`
- **`<search_data>` tags**: From **tool output strings**, not events
  - Tools embed instructions in return values
  - Goes into LLM context via `ToolMessage`
  - Requires post-hoc content filtering

### Solution Direction

Instead of reactive content filtering, implement **event-level filtering** by:

1. Creating `ToolResultEvent` that separates:
   - `llm_content`: Full result with instructions (for LLM)
   - `display_content`: Semantic summary (for user)

2. Emitting event at tool execution time (already has formatter access)

3. Consuming event in message processing (use pre-computed display content)

This follows RFC-501 architecture and eliminates need for `_filter_search_data_tags()`.

## Technical Design

### Component 1: Fix Duplicated Checkmarks

**File**: `src/soothe/ux/cli/execution/standalone.py:168-174`

**Change**: Remove hardcoded `✓` from `_emit_result()` since `brief` already contains icon from `ToolBrief.to_display()`.

**Impact**: All tool results show single checkmark.

### Component 2: ToolResultEvent Definition

**File**: `src/soothe/core/event_catalog.py`

Add new event type:

```python
@dataclass
class ToolResultEvent(ToolEvent):
    """Tool execution result with separated LLM and display content."""
    type: Literal["soothe.tool.execution.result"] = "soothe.tool.execution.result"
    tool_call_id: str = ""
    tool_name: str = ""
    llm_content: str = ""      # Full result for LLM context
    display_content: str = ""  # Semantic summary for user display
    duration_ms: int = 0
    args: dict[str, Any] = field(default_factory=dict)
```

**Registration**:
```python
register_event(
    ToolResultEvent,
    summary_template="{tool_name}: {display_content}",
    verbosity="tool_activity"
)
```

### Component 3: Emit ToolResultEvent

**File**: `src/soothe/utils/tool_logging.py:178-190`

Modify tool wrapper to emit event with separated content:

1. Call `ToolOutputFormatter.format()` to get semantic brief
2. Emit `ToolResultEvent` with both `llm_content` and `display_content`
3. Continue with normal `tool_completed` event

**Integration Point**: Chosen because:
- Has access to raw result before ToolMessage creation
- Already has event emission infrastructure
- Can call formatter without additional imports

### Component 4: Consume ToolResultEvent

**File**: `src/soothe/ux/core/message_processing.py:350-393`

Modify `process_tool_message()`:

1. Check if `ToolResultEvent` was emitted for this tool call
2. If found, use `display_content` (no formatting needed)
3. If not found, fallback to `extract_tool_brief()` (backward compatibility)

**Event Correlation**: Use `tool_call_id` to match ToolMessage with ToolResultEvent.

### Component 5: Proactive Whitespace Preservation

**File**: `src/soothe/ux/core/display_policy.py`

With event-level filtering handling most cases, add safety net for edge cases.

**Helper Method**: `_preserve_whitespace_around_removal()`

Analyzes whitespace context before removing content:
- Finds trailing whitespace before removal point
- Finds leading whitespace after removal point
- Determines appropriate preserved whitespace:
  - Newlines → preserve max 2
  - Spaces → preserve single space
  - No whitespace → add space between words (unless after punctuation)

**Update Filtering Methods**:
- `_filter_json_code_blocks()` - use helper for removal
- `_filter_plain_json()` - use helper for removal
- `_filter_search_data_tags()` - use helper for removal (reduced importance with events)

## Implementation Checklist

### Phase 1: Quick Wins

- [ ] Fix duplicated checkmarks in `standalone.py` (2 lines)
- [ ] Run tests to verify no regression

### Phase 2: Event-Level Filtering

- [ ] Define `ToolResultEvent` in `event_catalog.py`
- [ ] Register event with appropriate verbosity
- [ ] Emit `ToolResultEvent` in `tool_logging.py`
- [ ] Consume `ToolResultEvent` in `message_processing.py`
- [ ] Handle event correlation via `tool_call_id`

### Phase 3: Whitespace Preservation

- [ ] Add `_preserve_whitespace_around_removal()` helper in `display_policy.py`
- [ ] Update `_filter_json_code_blocks()` to use helper
- [ ] Update `_filter_plain_json()` to use helper
- [ ] Update `_filter_search_data_tags()` to use helper

### Phase 4: Testing

- [ ] Add unit test for duplicated checkmark fix
- [ ] Add unit test for ToolResultEvent emission/consumption
- [ ] Add unit tests for whitespace preservation
- [ ] Run integration test with research subagent
- [ ] Run full test suite: `./scripts/verify_finally.sh`

### Phase 5: Documentation

- [ ] Update tool development guide with ToolResultEvent
- [ ] Document LLM content vs display content separation
- [ ] Update RFC-501 with event-based filtering pattern

## Verification

### Unit Tests

1. **Duplicated Checkmark Fix**:
   ```python
   def test_single_checkmark_in_tool_result():
       formatter = _CliOutputFormatter()
       formatter.emit_tool_result("test_tool", "✓ Found 1 file", prefix=None, is_main=True)
       # Verify stderr contains single checkmark
   ```

2. **ToolResultEvent Emission**:
   ```python
   def test_tool_result_event_separated_content():
       # Mock tool execution
       # Verify ToolResultEvent emitted
       # Verify llm_content has tags
       # Verify display_content is clean
   ```

3. **Whitespace Preservation**:
   ```python
   def test_whitespace_preservation_newlines():
       text = "Para 1\n\n```json\n{...}\n```\n\nPara 2"
       result = policy.filter_content(text)
       assert result == "Para 1\n\nPara 2"

   def test_whitespace_preservation_spaces():
       text = "Before <search_data>...</search_data> after"
       result = policy.filter_content(text)
       assert result == "Before after"
   ```

### Integration Test

```bash
uv run soothe --no-tui "research Python 3.12 features"
```

**Verify**:
- No duplicated checkmarks
- No internal JSON in output
- No `<search_data>` tags in output
- Clean semantic tool summaries
- Proper spacing throughout

### Regression Test

```bash
./scripts/verify_finally.sh
```

All 900+ tests must pass.

## Migration Path

1. **Phase 1**: Add ToolResultEvent support (backward compatible)
2. **Phase 2**: Migrate high-traffic tools (wizsearch, etc.)
3. **Phase 3**: Make ToolResultEvent standard for all tools
4. **Phase 4**: Consider deprecating `_filter_search_data_tags()` once events are universal

## Edge Cases

- Tools returning binary data or large outputs
- Tools with streaming results
- Tools that fail mid-execution
- Empty tool results
- Event correlation when tool_call_id is missing

## Performance Impact

- **Positive**: ToolOutputFormatter called once (same as before), but result reused
- **Minimal**: Event emission adds ~microseconds
- **Reduced**: Less content filtering in DisplayPolicy (fewer regex passes)

## Backwards Compatibility

- **100% Compatible**: Existing tools continue to work
- **Fallback**: If ToolResultEvent not emitted, use current formatting path
- **No Breaking Changes**: Tool interface unchanged

## References

- [RFC-501: Event Display Architecture](../specs/RFC-501-event-display-architecture.md)
- [IG-075: Tool Output Formatter](IG-075-tool-output-formatter.md)
- `src/soothe/ux/core/tool_output_formatter.py` - ToolBrief definition
- `src/soothe/ux/core/tool_formatters/` - Tool-specific formatters
- `src/soothe/utils/tool_logging.py` - Tool execution logging wrapper