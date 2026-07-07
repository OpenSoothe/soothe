# IG-075: Tool Output Formatter Implementation

**Implementation Guide**: 075
**Title**: Tool Output Formatter - Semantic Result Summarization
**RFC**: RFC-501 (Event Display Architecture - Tool Output Enhancement)
**Status**: In Progress
**Created**: 2026-03-27
**Dependencies**: RFC-501, IG-074

## Overview

This guide tracks the implementation of semantic tool output formatting for RFC-501. The goal is to replace verbose, meaningless tool result truncation with concise, tool-specific summaries that show meaningful metrics.

## Problem Statement

**Current Behavior**:
```
⚙ ReadFile("/path/to/file.txt")
  └ ✓ This is the first line of the file content that continues on and on and gets trunca...
```

**Desired Behavior**:
```
⚙ ReadFile("/path/to/file.txt")
  └ ✓ Read 2.3 KB (42 lines)
```

**Limitations of Current Implementation**:
- Simple 120-character truncation
- No semantic understanding of result content
- No tool-specific formatting
- Difficult to quickly scan results

## Solution Architecture

### Formatter-Based Pipeline

```
Tool Result → Tool Classifier → Tool-Specific Formatter → ToolBrief → RFC-501 Display
```

### Key Components

1. **ToolBrief**: Structured summary dataclass with icon, summary, detail, metrics
2. **Tool Classifier**: Routes results to formatters based on tool name and result type
3. **Tool-Specific Formatters**: 6 formatter classes for different tool categories
4. **Integration Layer**: Hooks into existing `extract_tool_brief()` function

## Implementation Phases

### Phase 1: Foundation (Core Infrastructure) ✅

**Files to Create**:
- `src/soothe/ux/core/tool_output_formatter.py` - ToolBrief + classifier + main formatter
- `src/soothe/ux/core/tool_formatters/__init__.py` - Package exports
- `src/soothe/ux/core/tool_formatters/base.py` - BaseFormatter abstract class
- `src/soothe/ux/core/tool_formatters/fallback.py` - FallbackFormatter

**Status**: ✅ Completed

**Tasks**:
- [x] Create `ToolBrief` dataclass with `to_display()` method
- [x] Create `classify_tool()` function with category mapping
- [x] Create `detect_result_type()` function for result type detection
- [x] Create `ToolOutputFormatter` main class with `format()` method
- [x] Create `BaseFormatter` abstract base class
- [x] Create `FallbackFormatter` for unknown tools
- [x] Create `__init__.py` package exports

### Phase 2: Core Formatters (High-Impact Tools) ✅

**Files to Create**:
- `src/soothe/ux/core/tool_formatters/file_ops.py` - FileOpsFormatter
- `src/soothe/ux/core/tool_formatters/execution.py` - ExecutionFormatter

**File to Modify**:
- `src/soothe/ux/core/message_processing.py` - Replace `extract_tool_brief()`

**Status**: ✅ Completed

**Tasks**:
- [x] Implement `FileOpsFormatter` with:
  - `_format_read_file()`: Calculate size, count lines
  - `_format_write_file()`: Show size written
  - `_format_list_files()`: Count items
  - `_format_search_files()`: Count matches
  - `_format_glob()`: Count files
  - `_format_size()`: Helper for human-readable bytes
- [x] Implement `ExecutionFormatter` with:
  - `_format_run_command()`: Detect errors, show "Done"/"Failed"
  - `_format_run_python()`: Handle dict returns
  - `_format_run_background()`: Extract PID from dict
  - `_format_kill_process()`: Show PID terminated
- [x] Update `extract_tool_brief()` to use `ToolOutputFormatter`
- [x] Handle dict and ToolOutput result types (currently only accepts str)
- [x] Add error handling with fallback

### Phase 3: Specialized Formatters (Medium-Impact Tools) ✅

**Files to Create**:
- `src/soothe/ux/core/tool_formatters/media.py` - MediaFormatter
- `src/soothe/ux/core/tool_formatters/goal_formatter.py` - GoalFormatter
- `src/soothe/ux/core/tool_formatters/structured.py` - StructuredFormatter

**Status**: ✅ Completed

**Tasks**:
- [x] Implement `MediaFormatter` with:
  - `_format_transcribe_audio()`: Extract duration, language from dict
  - `_format_get_video_info()`: Extract duration, resolution from dict
  - `_format_analyze_image()`: Extract size, format from dict
- [x] Implement `GoalFormatter` with:
  - `_format_create_goal()`: Extract goal ID from dict
  - `_format_list_goals()`: Count goals from dict
  - `_format_complete_goal()`: Show goal ID
  - `_format_fail_goal()`: Show goal ID and reason
- [x] Implement `StructuredFormatter` for ToolOutput:
  - Detect silent failures
  - Extract error type classification
  - Re-route to tool-specific formatter based on data

### Phase 4: Testing & Validation

**File to Create**:
- `tests/unit/test_tool_output_formatter.py` - Formatter unit tests

**Status**: Pending

**Tasks**:
- [ ] Add unit tests for ToolBrief dataclass
- [ ] Add unit tests for tool classifier
- [ ] Add unit tests for each formatter:
  - FileOpsFormatter: read, write, list, search, glob
  - ExecutionFormatter: run_command, run_python, run_background
  - MediaFormatter: transcribe, video info
  - GoalFormatter: create, list, complete, fail
  - StructuredFormatter: success, failure, silent failure
  - FallbackFormatter: string, dict, unknown
- [ ] Test edge cases:
  - Empty results (0 files, empty file)
  - Large output (truncation)
  - Errors (failed commands, missing files)
  - Formatter errors (fallback handling)
- [ ] Test RFC-501 compliance (50/80 char limits)
- [ ] Run verification suite: `./scripts/verify_finally.sh`

## Tool Summary Patterns

### FileOpsFormatter

| Tool | Input Type | Success Pattern | Example |
|------|-----------|----------------|---------|
| read_file | str | "Read {size} ({lines} lines)" | "✓ Read 2.3 KB (42 lines)" |
| write_file | str | "Wrote {size}" | "✓ Wrote 1.5 KB" |
| delete_file | str | "Deleted" | "✓ Deleted" |
| list_files | str | "Found {count} items" | "✓ Found 15 items" |
| search_files | str | "Found {count} matches" | "✓ Found 7 matches" |
| glob | str | "Found {count} files" | "✓ Found 42 files" |
| ls | str | "Listed {count} items" | "✓ Listed 23 items" |

**Edge Cases**:
- Empty file: "✓ Read 0 B (empty file)"
- No matches: "✓ Found 0 files"

### ExecutionFormatter

| Tool | Input Type | Success Pattern | Example |
|------|-----------|----------------|---------|
| run_command | str | "Done" or "Failed: {reason}" | "✓ Done" or "✗ Failed: timeout" |
| run_python | dict | "Executed" or "Error" | "✓ Executed (returned: int)" |
| run_background | dict | "Started PID {pid}" | "✓ Started PID 12345" |
| kill_process | str | "Terminated PID {pid}" | "✓ Terminated PID 12345" |

**Error Detection**:
- `run_command`: Check for "Error:" prefix or non-zero exit
- `run_python`: Check `success` field in dict

### MediaFormatter

| Tool | Input Type | Success Pattern | Example |
|------|-----------|----------------|---------|
| transcribe_audio | dict | "Transcribed {duration}s ({language})" | "✓ Transcribed 45.2s (en)" |
| get_video_info | dict | "Video: {duration}s ({resolution})" | "✓ Video: 120s (1920x1080)" |
| analyze_image | dict | "Analyzed image ({size}, {format})" | "✓ Analyzed image (2.3 MB, PNG)" |

### GoalFormatter

| Tool | Input Type | Success Pattern | Example |
|------|-----------|----------------|---------|
| create_goal | dict | "Created goal {id}" | "✓ Created goal g1" |
| list_goals | dict | "Found {count} goals" | "✓ Found 3 goals" |
| complete_goal | dict | "Completed goal {id}" | "✓ Completed goal g1" |
| fail_goal | dict | "Failed goal {id}: {reason}" | "✗ Failed goal g1: blocked" |

### StructuredFormatter

| Status | Pattern | Example |
|--------|---------|---------|
| success=True | Tool-specific | "✓ Read 2.3 KB" |
| success=False | "Failed: {error}" | "✗ Failed: File not found" |
| silent failure | "⚠ No result" | "⚠ No result" |

## File Structure

```
src/soothe/ux/core/
├── tool_output_formatter.py          # ToolBrief + classifier + main formatter
└── tool_formatters/
    ├── __init__.py                   # Package exports
    ├── base.py                       # BaseFormatter abstract class
    ├── file_ops.py                   # FileOpsFormatter
    ├── execution.py                  # ExecutionFormatter
    ├── media.py                      # MediaFormatter
    ├── goals.py                      # GoalFormatter
    ├── structured.py                 # StructuredFormatter
    └── fallback.py                   # FallbackFormatter

tests/unit/
└── test_tool_output_formatter.py     # Unit tests
```

## Integration Points

### Modified: `src/soothe/ux/core/message_processing.py`

**Before** (lines 426-451):
```python
def extract_tool_brief(tool_name: str, content: str, max_length: int = 120) -> str:
    web_tools = {"search_web", "crawl_web"}
    if tool_name in web_tools:
        first_line = content.split("\n", 1)[0].strip()
        if first_line:
            return first_line[:max_length]
    return content.replace("\n", " ")[:max_length]
```

**After**:
```python
def extract_tool_brief(tool_name: str, content: str | dict | Any, max_length: int = 120) -> str:
    """Extract concise summary using semantic formatters."""
    from soothe.ux.core.tool_output_formatter import ToolOutputFormatter

    formatter = ToolOutputFormatter()
    brief = formatter.format(tool_name, content)
    return brief.to_display()
```

### Unchanged: Renderer Files

Both `src/soothe/ux/cli/renderer.py` and `src/soothe/ux/cli/execution/standalone.py` will use the pre-formatted `brief` string from `extract_tool_brief()`, requiring no changes.

## Success Criteria

- [ ] **Semantic Summaries**: Tool outputs show meaningful metrics instead of raw truncation
- [ ] **Tool-Specific**: Each tool type has customized summary format
- [ ] **RFC-501 Compliance**: Summaries respect 50/80 char limits
- [ ] **Backward Compatible**: Unknown tools still work with fallback formatter
- [ ] **Error Resilient**: Formatter errors don't crash the system
- [ ] **Tested**: All formatters have unit tests
- [ ] **Verified**: `./scripts/verify_finally.sh` passes (formatting, linting, tests)

## Testing Strategy

### Unit Tests

**Location**: `tests/unit/test_tool_output_formatter.py`

**Test Categories**:
1. ToolBrief dataclass tests
2. Tool classifier tests
3. FileOpsFormatter tests
4. ExecutionFormatter tests
5. MediaFormatter tests
6. GoalFormatter tests
7. StructuredFormatter tests
8. FallbackFormatter tests
9. Edge case tests
10. RFC-501 compliance tests

### Manual Testing

```bash
# File operations
uv run soothe --no-tui -p "list all Python files in src/soothe"
uv run soothe --no-tui -p "read the first 10 lines of README.md"

# Execution
uv run soothe --no-tui -p "run: echo 'hello world'"
uv run soothe --no-tui -p "run: ls -la"

# Verification
./scripts/verify_finally.sh
```

## Dependencies

- **RFC-501**: Event Display Architecture
- **RFC-201**: Agentic Loop Execution (ToolOutput schema)
- **IG-074**: Claude-like Agentic Loop (ToolOutput implementation)

## Related Documents

- [RFC-501](../specs/RFC-501-event-display-architecture.md) - Event display specification
- [RFC-201](../specs/RFC-201-agentic-loop-execution.md) - ToolOutput schema
- [Plan](../../.claude/plans/eager-wibbling-crystal.md) - Implementation plan

## Progress Log

### 2026-03-27

- Created RFC-501 enhancement specification
- Created IG-075 implementation guide
- ✅ Completed Phase 1: Foundation
  - Created `tool_output_formatter.py` with ToolBrief, classifier, main formatter
  - Created `BaseFormatter` abstract base class with helper methods
  - Created `FallbackFormatter` for backward compatibility
  - Created `__init__.py` package exports
- ✅ Completed Phase 2: Core Formatters
  - Implemented `FileOpsFormatter` with read/write/list/search/glob formatting
  - Implemented `ExecutionFormatter` with run_command/run_python/run_background formatting
  - Updated `extract_tool_brief()` to use new formatter system
  - Added dict and ToolOutput result type handling
  - Added error handling with fallback
- ✅ Completed Phase 3: Specialized Formatters
  - Implemented `MediaFormatter` for audio/video/image tools
  - Implemented `GoalFormatter` for goal management tools
  - Implemented `StructuredFormatter` for ToolOutput objects
- ✅ Linting and formatting checks pass
- ✅ Manual testing confirms semantic summaries work correctly

**Test Results**:
```
read_file: ✓ Read 12 B (3 lines)
run_command: ✓ Done (11 chars output)
list_files: ✓ Found 3 items
glob: ✓ Found 2 files
```

**Next Steps**:
- [ ] Phase 4: Add unit tests
- [ ] Run full verification suite
- [ ] Create commit with implementation

---

*This implementation guide tracks the progress of semantic tool output formatting for RFC-501.*