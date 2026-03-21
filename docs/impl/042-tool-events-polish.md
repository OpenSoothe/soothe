# Tool Events Polish Implementation Architecture

> Implementation guide for polishing tool-related events on CLI and TUI in Soothe.
>
> **Module**: `src/soothe/cli/`, `src/soothe/tools/`
> **Source**: Derived from user requirements and gap analysis
> **Related RFCs**: RFC-0003 (CLI TUI Architecture), RFC-0015 (Event Catalog)
> **Language**: Python 3.13
> **Framework**: Rich (TUI), LangChain (tools)

---

## 1. Overview

### 1.1 Purpose

This document specifies the **implementation architecture** for polishing tool-related events in Soothe's CLI and TUI interfaces. It provides:

- Concrete file structure and module organization
- Type definitions for display name mapping
- Function signatures for argument formatting
- Implementation details for event rendering
- Error handling and edge case strategies
- Testing approach for UI consistency

### 1.2 Problem Statement

Tool events currently have three key issues affecting user experience:

1. **Low visibility**: Tool events require "detailed" or "debug" verbosity to be visible, making them invisible at default "normal" verbosity
2. **Technical naming**: Tool names displayed as snake_case (e.g., "read_file") rather than user-friendly CamelCase (e.g., "ReadFile")
3. **Missing context**: Tool call events show no arguments, making it hard to understand what the tool is doing at a glance

### 1.3 Scope

**In Scope**:
- Verbosity category change for tool events
- Display name mapping for all built-in tools
- Argument extraction and formatting for common tools
- Consistent rendering in both CLI and TUI modes
- Unit and integration tests

**Out of Scope**:
- Tool execution logic changes
- New tool creation
- Event type structure changes
- Verbosity system redesign

### 1.4 Spec Compliance

This implementation follows the existing event classification system defined in RFC-0015 (Event Catalog) and RFC-0003 (CLI TUI Architecture). The changes:

- **Preserve** the existing verbosity category system
- **Preserve** the event emission patterns
- **Preserve** the rendering architecture separation
- **Enhance** user-facing display without changing internal event structure

---

## 2. Architectural Position

### 2.1 System Context

Tool event rendering flows through a multi-layer pipeline:

```
Tool Execution (src/soothe/tools/)
         ↓
Event Emission (soothe.utils.progress.emit_progress)
         ↓
Event Classification (src/soothe/cli/progress_verbosity.py)
         ↓
    ┌────────────────┐
    │                │
    ↓                ↓
CLI Renderer    TUI Renderer
(cli_event_renderer.py)  (tui/renderers.py)
    │                │
    ↓                ↓
  stderr         Activity Panel
```

### 2.2 Dependency Graph

```
progress_verbosity.py (verbosity classification)
        ↓
display_names.py (NEW: name mapping) ← subagent_names.py (pattern reference)
        ↓
message_processing.py (argument formatting)
        ↓
    ┌───────────────┐
    ↓               ↓
cli_event_renderer.py   tui/renderers.py
    │               │
    ↓               ↓
standalone_runner.py   tui/event_processors.py
    │               │
    ↓               ↓
daemon_runner.py    TUI OutputFormatter
```

### 2.3 Module Responsibilities

| Module | Responsibility | Dependencies |
|--------|----------------|--------------|
| `tools/display_names.py` | Map snake_case tool names to CamelCase display names | None (pure data) |
| `cli/message_processing.py` | Format tool arguments for display | `display_names.py` |
| `cli/progress_verbosity.py` | Classify events by verbosity category | `core/event_catalog.py` |
| `cli/tui/renderers.py` | Render tool events in TUI activity panel | `display_names.py`, `message_processing.py` |
| `cli/rendering/cli_event_renderer.py` | Render tool events in headless CLI | `display_names.py` |

### 2.4 Dependency Constraints

**display_names.py**:
- **MUST** be a standalone module with no external dependencies (pure data mapping)
- **MUST** provide a fallback conversion for unmapped tools
- **MAY** be imported by any rendering module

**message_processing.py**:
- **MUST** add `format_tool_call_args()` function
- **MUST NOT** modify existing function signatures without backward compatibility
- **MAY** extend `OutputFormatter` protocol with optional parameters

---

## 3. Module Structure

```
src/soothe/
├── tools/
│   └── display_names.py          # NEW: Tool display name mapping
├── cli/
│   ├── progress_verbosity.py     # Modified: Update tool event classification
│   ├── message_processing.py     # Modified: Add argument formatting
│   ├── tui/
│   │   ├── renderers.py          # Modified: Update tool call/result rendering
│   │   └── event_processors.py   # Modified: Pass tool call args
│   ├── rendering/
│   │   └── cli_event_renderer.py # Modified: Use display names
│   └── commands/
│       └── subagent_names.py     # Reference pattern for display names
```

---

## 4. Core Types

### 4.1 Tool Display Names Dictionary

Centralized mapping from internal snake_case names to user-facing CamelCase names.

```python
# src/soothe/tools/display_names.py

TOOL_DISPLAY_NAMES: dict[str, str] = {
    # File operations
    "read_file": "ReadFile",
    "write_file": "WriteFile",
    "delete_file": "DeleteFile",
    "search_files": "SearchFiles",
    "list_files": "ListFiles",
    "file_info": "FileInfo",
    "edit_file_lines": "EditFileLines",
    "insert_lines": "InsertLines",
    "delete_lines": "DeleteLines",
    "apply_diff": "ApplyDiff",

    # Execution
    "run_command": "RunCommand",
    "run_python": "RunPython",
    "run_background": "RunBackground",
    "kill_process": "KillProcess",

    # Data operations
    "inspect_data": "InspectData",
    "summarize_data": "SummarizeData",
    "check_data_quality": "CheckDataQuality",
    "extract_text": "ExtractText",
    "get_data_info": "GetDataInfo",
    "ask_about_file": "AskAboutFile",

    # Goals
    "create_goal": "CreateGoal",
    "list_goals": "ListGoals",
    "complete_goal": "CompleteGoal",
    "fail_goal": "FailGoal",

    # Web
    "search_web": "SearchWeb",
    "crawl_web": "CrawlWeb",

    # Research
    "research": "Research",

    # Media
    "analyze_image": "AnalyzeImage",
    "extract_text_from_image": "ExtractTextFromImage",
    "analyze_video": "AnalyzeVideo",
    "get_video_info": "GetVideoInfo",
    "transcribe_audio": "TranscribeAudio",
    "audio_qa": "AudioQA",

    # DateTime
    "current_datetime": "CurrentDateTime",
}
```

**Design Rationale**:
- Follows pattern from `src/soothe/cli/commands/subagent_names.py`
- Covers all tools defined in RFC-0016 (Tool Consolidation)
- Alphabetically organized by category for maintainability

### 4.2 Argument Mapping Dictionary

Internal mapping defining which argument to display for each tool type.

```python
# src/soothe/cli/message_processing.py

_ARG_DISPLAY_MAP: dict[str, str] = {
    # File operations - show path
    "read_file": "path",
    "write_file": "path",
    "delete_file": "path",
    "file_info": "path",
    "edit_file_lines": "path",
    "insert_lines": "path",
    "delete_lines": "path",
    "apply_diff": "path",

    # Execution - show command/code
    "run_command": "command",
    "run_python": "code",
    "run_background": "command",
    "kill_process": "pid",

    # Search - show pattern/query
    "search_files": "pattern",
    "list_files": "pattern",
    "search_web": "query",
    "crawl_web": "url",

    # Media - show file path
    "analyze_image": "image_path",
    "analyze_video": "video_path",
    "transcribe_audio": "audio_path",

    # Goals - show description or ID
    "create_goal": "description",
    "complete_goal": "goal_id",
    "fail_goal": "goal_id",
}
```

**Design Rationale**:
- Maps tool names to the most meaningful argument for end-users
- Prioritizes file paths for file operations, commands for execution tools
- Private constant (not exported) - encapsulated in formatting function

---

## 5. Key Interfaces

### 5.1 Display Name Lookup Function

```python
def get_tool_display_name(internal_name: str) -> str:
    """Get user-facing display name for a tool.

    Args:
        internal_name: Tool name in snake_case (e.g., "read_file")

    Returns:
        PascalCase display name (e.g., "ReadFile")

    Examples:
        >>> get_tool_display_name("read_file")
        "ReadFile"
        >>> get_tool_display_name("unknown_tool")
        "UnknownTool"
    """
    return TOOL_DISPLAY_NAMES.get(
        internal_name,
        internal_name.replace("_", " ").title().replace(" ", ""),
    )
```

**Fallback Logic**:
- If tool not in mapping, convert snake_case to PascalCase automatically
- Handles future tools without requiring mapping updates
- Example: "my_custom_tool" → "MyCustomTool"

### 5.2 Argument Formatting Function

```python
def format_tool_call_args(tool_name: str, tool_call: dict[str, Any]) -> str:
    """Format key tool arguments for display.

    Extracts the most relevant argument(s) for each tool type to show
    in activity events.

    Args:
        tool_name: Internal tool name (snake_case)
        tool_call: Tool call dict with 'args' key containing arguments

    Returns:
        Formatted argument string like "(file_name.md)" or "(query)"
        Empty string if no relevant argument found

    Examples:
        >>> format_tool_call_args("read_file", {"args": {"path": "config.yml"}})
        "(config.yml)"
        >>> format_tool_call_args("run_command", {"args": {"command": "ls -la"}})
        "(ls -la)"
        >>> format_tool_call_args("read_file", {"args": {}})
        ""
    """
    args = tool_call.get("args", {})
    if not isinstance(args, dict):
        return ""

    key_arg = _ARG_DISPLAY_MAP.get(tool_name)
    if not key_arg or key_arg not in args:
        return ""

    value = str(args[key_arg])
    # Truncate long values to prevent activity line overflow
    if len(value) > 50:
        value = value[:47] + "..."

    return f"({value})"
```

**Truncation Policy**:
- 50 character maximum for argument values
- Prevents activity lines from becoming too long
- Balances information density with readability

### 5.3 Extended OutputFormatter Protocol

The `OutputFormatter` protocol gains an optional parameter:

```python
class OutputFormatter(Protocol):
    def emit_tool_call(
        self,
        name: str,
        *,
        prefix: str | None,
        is_main: bool,
        tool_call: dict[str, Any] | None = None,  # NEW: optional
    ) -> None:
        """Emit a tool call notification.

        Args:
            name: The tool name being called.
            prefix: Optional namespace prefix for subagents.
            is_main: Whether this is from the main agent.
            tool_call: Optional tool call dict with args for display.
        """
        ...
```

**Backward Compatibility**:
- `tool_call` parameter is optional (default `None`)
- Existing implementations continue to work unchanged
- Only updated implementations use the new parameter

---

## 6. Implementation Details

### 6.1 Verbosity Classification Change

**File**: `src/soothe/cli/progress_verbosity.py`

**Change**: Re-classify tool events from `"tool_activity"` to `"protocol"`

**Before** (line 71-72):
```python
if domain == "tool":
    return "tool_activity"
```

**After**:
```python
if domain == "tool":
    return "protocol"
```

**Impact**:
- Tool events become visible at "normal" verbosity
- `"protocol"` is already in the "normal" visibility set (line 101)
- No changes needed to `should_show()` function

**Verification**:
```python
# Before: tool events hidden at normal verbosity
assert should_show("tool_activity", "normal") == False

# After: tool events visible at normal verbosity
assert should_show("protocol", "normal") == True
```

### 6.2 TUI Tool Call Rendering

**File**: `src/soothe/cli/tui/renderers.py`

**Function**: `_handle_tool_call_activity()`

**Changes**:
1. Add `tool_call` optional parameter
2. Use `get_tool_display_name()` for name conversion
3. Use `format_tool_call_args()` for argument formatting
4. Remove verbose "Calling" prefix
5. Change verbosity check from `"tool_activity"` to `"protocol"`

**Before**:
```python
def _handle_tool_call_activity(
    state: TuiState,
    name: str,
    *,
    prefix: str | None = None,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    if not name or not should_show("tool_activity", verbosity):
        return
    if prefix:
        _add_activity_from_event(
            state, Text.assemble(("  . ", "dim"), (f"[{prefix}] [tool] Calling: {name}", "blue")), {}
        )
    else:
        _add_activity_from_event(
            state, Text.assemble(("  . ", "dim"), (f"Calling {name}", "blue")), {}
        )
```

**After**:
```python
def _handle_tool_call_activity(
    state: TuiState,
    name: str,
    *,
    prefix: str | None = None,
    verbosity: ProgressVerbosity = "normal",
    tool_call: dict[str, Any] | None = None,  # NEW
) -> None:
    if not name or not should_show("protocol", verbosity):  # Changed
        return

    display_name = get_tool_display_name(name)  # NEW

    args_str = ""
    if tool_call:
        args_str = format_tool_call_args(name, tool_call)  # NEW

    if prefix:
        _add_activity_from_event(
            state,
            Text.assemble(("  . ", "dim"), (f"[{prefix}] {display_name}{args_str}", "blue")),
            {},
        )
    else:
        _add_activity_from_event(
            state,
            Text.assemble(("  . ", "dim"), (f"{display_name}{args_str}", "blue")),
            {},
        )
```

**Display Examples**:
- Before: `  . Calling read_file`
- After: `  . ReadFile(config.yml)`

### 6.3 TUI Tool Result Rendering

**File**: `src/soothe/cli/tui/renderers.py`

**Function**: `_handle_tool_result_activity()`

**Changes**:
1. Use `get_tool_display_name()` for name conversion
2. Change verbosity check from `"tool_activity"` to `"protocol"`

**Before**:
```python
def _handle_tool_result_activity(
    state: TuiState,
    tool_name: str,
    content: str,
    *,
    prefix: str | None = None,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    if not should_show("tool_activity", verbosity):
        return
    brief = _extract_tool_brief(tool_name, content)
    if prefix:
        _add_activity_from_event(
            state,
            Text.assemble(("  > ", "dim green"), (f"[{prefix}] {tool_name}", "green"), ("  ", ""), (brief, "dim")),
            {},
        )
    else:
        _add_activity_from_event(
            state, Text.assemble(("  > ", "dim green"), (tool_name, "green"), ("  ", ""), (brief, "dim")), {}
        )
```

**After**:
```python
def _handle_tool_result_activity(
    state: TuiState,
    tool_name: str,
    content: str,
    *,
    prefix: str | None = None,
    verbosity: ProgressVerbosity = "normal",
) -> None:
    if not should_show("protocol", verbosity):  # Changed
        return

    display_name = get_tool_display_name(tool_name)  # NEW
    brief = _extract_tool_brief(tool_name, content)

    if prefix:
        _add_activity_from_event(
            state,
            Text.assemble(
                ("  > ", "dim green"),
                (f"[{prefix}] {display_name}", "green"),
                ("  ", ""),
                (brief, "dim")
            ),
            {},
        )
    else:
        _add_activity_from_event(
            state,
            Text.assemble(("  > ", "dim green"), (display_name, "green"), ("  ", ""), (brief, "dim")),
            {},
        )
```

**Display Examples**:
- Before: `  > read_file  <brief result>`
- After: `  > ReadFile  <brief result>`

### 6.4 Event Processor Updates

**File**: `src/soothe/cli/tui/event_processors.py`

**Function**: Tool call processing in `process_daemon_event()`

**Changes**: Extract tool call args and pass to renderer

**Before** (line 270-272):
```python
elif btype in ("tool_call_chunk", "tool_call"):
    name = block.get("name", "")
    _handle_tool_call_activity(state, name, prefix=prefix, verbosity=verbosity)
```

**After**:
```python
elif btype in ("tool_call_chunk", "tool_call"):
    name = block.get("name", "")
    # Extract tool call with args for display
    tool_call = {
        "args": block.get("args", {})
    }
    _handle_tool_call_activity(state, name, prefix=prefix, verbosity=verbosity, tool_call=tool_call)
```

### 6.5 Message Processor Updates

**File**: `src/soothe/cli/message_processing.py`

**Function**: `process_ai_message()`

**Changes**: Pass tool call info to formatter

**Before** (line 116-120):
```python
elif btype in ("tool_call", "tool_call_chunk"):
    name = block.get("name", "")
    if name and should_show("tool_activity", verbosity):
        self.formatter.emit_tool_call(name, prefix=None, is_main=is_main)
```

**After**:
```python
elif btype in ("tool_call", "tool_call_chunk"):
    name = block.get("name", "")
    if name and should_show("protocol", verbosity):  # Changed
        # Extract args for display
        tool_call = {"args": block.get("args", {})}
        self.formatter.emit_tool_call(name, prefix=None, is_main=is_main, tool_call=tool_call)
```

### 6.6 CLI Headless Renderer

**File**: `src/soothe/cli/rendering/cli_event_renderer.py`

**Changes**: Use display names in tool-specific event renderers

**Example** (search events):
```python
from soothe.tools.display_names import get_tool_display_name

def _render_search_started(self, event: dict[str, Any]) -> list[str]:
    query = event.get("query", "")
    engines = event.get("engines", [])
    display_name = get_tool_display_name("search_web")  # NEW
    parts = [f"{display_name}:", str(query)[:40]]
    if engines:
        parts.append(f"({', '.join(engines[:_MAX_INLINE_QUERIES])})")
    return parts
```

**Display Examples**:
- Before: `[tool] Searching: query...`
- After: `SearchWeb: query...`

---

## 7. Error Handling

### 7.1 Missing Tool Names

**Scenario**: Tool name not in `TOOL_DISPLAY_NAMES` mapping

**Handling**: Fallback conversion
```python
# Fallback logic in get_tool_display_name()
internal_name.replace("_", " ").title().replace(" ", "")
# Example: "my_custom_tool" → "MyCustomTool"
```

**Rationale**: Graceful degradation for unknown tools

### 7.2 Missing Arguments

**Scenario**: Tool call doesn't have expected key argument

**Handling**: Return empty string
```python
# In format_tool_call_args()
if not key_arg or key_arg not in args:
    return ""
```

**Display**: Tool shown without arguments
- Example: `  . ReadFile` instead of `  . ReadFile(config.yml)`

### 7.3 Invalid Tool Call Structure

**Scenario**: `tool_call` dict malformed or missing `args` key

**Handling**: Type checking and early return
```python
args = tool_call.get("args", {})
if not isinstance(args, dict):
    return ""
```

**Rationale**: Defensive programming prevents crashes

### 7.4 Long Argument Values

**Scenario**: Argument value exceeds display length

**Handling**: Truncation with ellipsis
```python
if len(value) > 50:
    value = value[:47] + "..."
```

**Display**: `  . RunCommand(very long command that goes on and on...)`

---

## 8. Configuration

### 8.1 Truncation Limits

```python
# src/soothe/cli/message_processing.py

_MAX_ARG_LENGTH = 50  # Maximum characters for argument display
```

### 8.2 Verbosity Defaults

No configuration changes needed. Tool events inherit `"protocol"` category visibility:

| Verbosity | Tool Events Visible? |
|-----------|---------------------|
| `"minimal"` | ❌ No |
| `"normal"` | ✅ Yes (new) |
| `"detailed"` | ✅ Yes |
| `"debug"` | ✅ Yes |

---

## 9. Testing Strategy

### 9.1 Unit Tests

**Test File**: `tests/unit_tests/test_tools_display_names.py` (NEW)

```python
import pytest
from soothe.tools.display_names import get_tool_display_name, TOOL_DISPLAY_NAMES


def test_display_name_known_tools():
    """Test known tools return correct CamelCase names."""
    assert get_tool_display_name("read_file") == "ReadFile"
    assert get_tool_display_name("run_command") == "RunCommand"
    assert get_tool_display_name("search_web") == "SearchWeb"


def test_display_name_unknown_tool():
    """Test fallback conversion for unknown tools."""
    assert get_tool_display_name("my_custom_tool") == "MyCustomTool"
    assert get_tool_display_name("new_tool") == "NewTool"


def test_all_tool_names_covered():
    """Test that all tool names from RFC-0016 have mappings."""
    # Import tool lists from tool modules
    from soothe.tools.file_ops import ReadFileTool
    from soothe.tools.execution import RunCommandTool
    # ... etc

    tool_names = [
        ReadFileTool.name,  # "read_file"
        RunCommandTool.name,  # "run_command"
        # ... all other tools
    ]

    for name in tool_names:
        assert name in TOOL_DISPLAY_NAMES, f"Missing display name for {name}"
```

**Test File**: `tests/unit_tests/test_message_processing.py` (update existing)

```python
def test_format_tool_call_args_file_path():
    """Test argument formatting for file tools."""
    from soothe.cli.message_processing import format_tool_call_args

    tool_call = {"args": {"path": "/workspace/README.md"}}
    result = format_tool_call_args("read_file", tool_call)
    assert result == "(/workspace/README.md)"


def test_format_tool_call_args_command():
    """Test argument formatting for execution tools."""
    from soothe.cli.message_processing import format_tool_call_args

    tool_call = {"args": {"command": "ls -la"}}
    result = format_tool_call_args("run_command", tool_call)
    assert result == "(ls -la)"


def test_format_tool_call_args_truncation():
    """Test long argument truncation."""
    from soothe.cli.message_processing import format_tool_call_args

    long_path = "/very/long/path/that/exceeds/fifty/characters/and/should/be/truncated.md"
    tool_call = {"args": {"path": long_path}}
    result = format_tool_call_args("read_file", tool_call)
    assert len(result) == 53  # 50 chars + "..."
    assert result.endswith("...")


def test_format_tool_call_args_missing():
    """Test missing argument handling."""
    from soothe.cli.message_processing import format_tool_call_args

    tool_call = {"args": {}}
    result = format_tool_call_args("read_file", tool_call)
    assert result == ""


def test_format_tool_call_args_invalid():
    """Test invalid tool call structure."""
    from soothe.cli.message_processing import format_tool_call_args

    result = format_tool_call_args("read_file", {})
    assert result == ""

    result = format_tool_call_args("read_file", {"args": "not a dict"})
    assert result == ""
```

**Test File**: `tests/unit_tests/test_progress_verbosity.py` (update existing)

```python
def test_tool_events_visible_at_normal():
    """Test that tool events are visible at normal verbosity."""
    from soothe.cli.progress_verbosity import classify_custom_event, should_show

    # Tool event classification
    tool_event = {"type": "soothe.tool.websearch.search_started"}
    category = classify_custom_event((), tool_event)
    assert category == "protocol"

    # Visibility check
    assert should_show(category, "normal") is True
    assert should_show(category, "minimal") is False
```

### 9.2 Integration Tests

**Test File**: `tests/integration_tests/test_tool_event_rendering.py` (NEW)

```python
import pytest
from io import StringIO
from rich.text import Text

from soothe.cli.tui.renderers import _handle_tool_call_activity, _handle_tool_result_activity
from soothe.cli.tui.state import TuiState


def test_tool_call_display_with_args():
    """Test tool call rendering with arguments."""
    state = TuiState()

    _handle_tool_call_activity(
        state,
        "read_file",
        prefix=None,
        verbosity="normal",
        tool_call={"args": {"path": "config.yml"}}
    )

    # Check activity line was added
    assert len(state.activity_lines) == 1
    line = state.activity_lines[0]
    assert isinstance(line, Text)

    # Check display content
    plain = line.plain
    assert "ReadFile" in plain
    assert "(config.yml)" in plain
    assert "Calling" not in plain  # Should NOT have verbose prefix


def test_tool_result_display():
    """Test tool result rendering with display name."""
    state = TuiState()

    _handle_tool_result_activity(
        state,
        "read_file",
        "File contents here...",
        prefix=None,
        verbosity="normal"
    )

    assert len(state.activity_lines) == 1
    line = state.activity_lines[0]
    plain = line.plain
    assert "ReadFile" in plain
    assert "read_file" not in plain


def test_cli_headless_tool_event():
    """Test tool event rendering in headless CLI mode."""
    from soothe.cli.rendering.cli_event_renderer import CliEventRenderer

    renderer = CliEventRenderer()
    event = {
        "type": "soothe.tool.websearch.search_started",
        "query": "Python tutorials",
        "engines": ["duckduckgo"]
    }

    # Capture stderr output
    import sys
    from io import StringIO
    old_stderr = sys.stderr
    sys.stderr = StringIO()

    try:
        renderer.render(event, verbosity="normal")
        output = sys.stderr.getvalue()
        assert "SearchWeb" in output
        assert "search_web" not in output
    finally:
        sys.stderr = old_stderr
```

### 9.3 Visual Verification Tests

Manual verification checklist:

- [ ] Run `soothe run "Read README.md"` - see `  . ReadFile(README.md)`
- [ ] Run `soothe run "List Python files"` - see `  . ListFiles(*.py)`
- [ ] Run `soothe run "Search web for X"` - see `  . SearchWeb(X)`
- [ ] Run `soothe autopilot "task"` - see tool events in TUI activity panel
- [ ] Verify subagent tool calls show prefix: `  . [subagent] ReadFile(file.md)`
- [ ] Verify tool results show display name: `  > ReadFile  success`

---

## 10. Migration / Compatibility

### 10.1 Backward Compatibility

**Breaking Changes**: None

The implementation maintains full backward compatibility:

1. **Verbosity behavior**: Users who want tool events at "detailed" level can still use `--verbosity detailed` - tool events now also appear at "normal"

2. **Event structure**: No changes to event emission or internal event types - only display layer affected

3. **Protocol extensions**: `OutputFormatter.emit_tool_call()` gains optional parameter - existing implementations continue to work

### 10.2 Migration Path

**For users**: No action required. Tool events automatically visible at normal verbosity with improved display.

**For developers**: Optional updates to custom formatters:

```python
# Old implementation (still works)
def emit_tool_call(self, name: str, *, prefix: str | None, is_main: bool) -> None:
    print(f"Calling {name}")

# New implementation (enhanced)
def emit_tool_call(
    self,
    name: str,
    *,
    prefix: str | None,
    is_main: bool,
    tool_call: dict[str, Any] | None = None,
) -> None:
    from soothe.tools.display_names import get_tool_display_name
    from soothe.cli.message_processing import format_tool_call_args

    display_name = get_tool_display_name(name)
    args_str = format_tool_call_args(name, tool_call) if tool_call else ""
    print(f"{display_name}{args_str}")
```

---

## Appendix A: RFC Requirement Mapping

| RFC Requirement | Guide Section | Implementation |
|-----------------|---------------|----------------|
| RFC-0015: Event classification | Section 6.1 | `progress_verbosity.py` domain mapping |
| RFC-0003: TUI rendering | Section 6.2, 6.3 | `tui/renderers.py` display name usage |
| RFC-0003: CLI rendering | Section 6.6 | `cli_event_renderer.py` display name usage |
| RFC-0016: Tool consolidation | Section 4.1 | `display_names.py` covers all consolidated tools |

---

## Appendix B: Revision History

| Date | Version | Changes |
|------|---------|---------|
| 2026-03-21 | 1.0 | Initial implementation guide |

---

## Appendix C: Verification Checklist

Before marking implementation complete:

- [ ] All unit tests pass (`pytest tests/unit_tests/test_tools_display_names.py -v`)
- [ ] All integration tests pass (`pytest tests/integration_tests/test_tool_event_rendering.py -v`)
- [ ] Manual CLI verification with multiple tools
- [ ] Manual TUI verification with activity panel
- [ ] No regressions in existing verbosity tests
- [ ] Documentation updated (if needed)
- [ ] Change log updated

---

**Implementation Priority**: Medium - UX improvement with no breaking changes
**Estimated Effort**: 4-6 hours (implementation + testing)
**Dependencies**: None - can be implemented independently
