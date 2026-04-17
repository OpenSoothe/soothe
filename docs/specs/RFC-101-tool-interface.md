# RFC-101: Tool Interface & Event Naming

**Status**: Implemented
**Authors**: Xiaming Chen
**Created**: 2026-03-31
**Last Updated**: 2026-03-31
**Depends on**: RFC-100 (CoreAgent Runtime), RFC-400 (Event Processing)
**Supersedes**: RFC-0016, RFC-0025
**Kind**: Implementation Interface Design

---

## 1. Abstract

This RFC defines the interface contracts for Soothe's tool layer, establishing single-purpose tool design patterns and event naming conventions. It consolidates tool interface optimization (formerly RFC-0016) and tool event naming unification (formerly RFC-0025) into a single implementation interface specification.

---

## 2. Scope and Non-Goals

### 2.1 Scope

This RFC defines:

* Tool interface contracts (single-purpose design pattern)
* Tool naming conventions and registry structure
* Event naming conventions for tool operations
* Error recovery format for tool responses
* Session management patterns for stateful tools

### 2.2 Non-Goals

This RFC does **not** define:

* Tool execution runtime (see RFC-100 CoreAgent Runtime)
* Event processing pipeline (see RFC-400)
* Security policy for tool permissions (see RFC-102)
* Backend implementations (see tool module code)

---

## 3. Background & Motivation

### 3.1 Tool Interface Problem

Analysis revealed Soothe's LLM could not effectively use tools:

- **Tool Call Success Rate**: ~60% (target: 95%)
- **Common Failures**: Wrong mode parameter, confused action parameter, missing parameters

Unified dispatch tools (`execute`, `workspace`) created cognitive load through mode/action indirection.

### 3.2 Event Naming Problem

Tool events exhibited naming inconsistency:

| Event | Pattern | Category |
|-------|---------|----------|
| `read` | Simple verb | Atomic ✓ |
| `write` | Simple verb | Atomic ✓ |
| `backup_created` | Past-tense | Neither ❌ |
| `search_started` | Lifecycle triplet | Async ✓ |

Atomic operations should use simple verbs; async operations should use lifecycle triplets.

---

## 4. Naming Conventions

### 4.1 Tool Naming

Pattern: `{verb}_{noun}` or single verb for obvious operations.

| Category | Examples | Pattern |
|----------|----------|---------|
| Shell execution | `run_command`, `run_background`, `kill_process` | `{verb}_{noun}` |
| Python execution | `run_python` | `{verb}_{noun}` |
| File operations | `read_file`, `write_file`, `delete_file`, `search_files` | `{verb}_{noun}` |
| Code editing | `edit_file_lines`, `insert_lines`, `delete_lines`, `apply_diff` | `{verb}_{context}` |
| Media analysis | `analyze_image`, `transcribe_audio` | `{verb}_{noun}` |

### 4.2 Event Naming Convention

**Atomic Operations** (single-shot, immediate completion):

```
Pattern: soothe.tool.<component>.<verb>
Examples: soothe.tool.file_ops.read
          soothe.tool.file_ops.write
          soothe.tool.file_ops.backup
```

**Async Operations** (observable lifecycle):

```
Pattern: soothe.tool.<component>.<action>_started
         soothe.tool.<component>.<action>_completed
         soothe.tool.<component>.<action>_failed
Examples: soothe.tool.file_ops.search_started
          soothe.tool.file_ops.search_completed
```

### 4.3 Type String Alignment

Event type strings follow 4-segment pattern: `soothe.tool.<component>.<action>`. The `<action>` segment uses the same naming convention as the event class.

---

## 5. Data Structures

### 5.1 Tool Event Base

```python
class ToolEvent(SootheEvent):
    """Base class for all tool events."""
    type: str  # soothe.tool.<component>.<action>
    tool_name: str = ""
    model_config = ConfigDict(extra="allow")
```

### 5.2 Atomic Event Example

```python
class BackupEvent(ToolEvent):
    type: Literal["soothe.tool.file_ops.backup"] = "soothe.tool.file_ops.backup"
    original_path: str = ""
    backup_path: str = ""
```

### 5.3 Async Event Triplet Example

```python
class SearchStartedEvent(ToolEvent):
    type: Literal["soothe.tool.file_ops.search_started"] = "soothe.tool.file_ops.search_started"
    query: str = ""
    path: str = ""

class SearchCompletedEvent(ToolEvent):
    type: Literal["soothe.tool.file_ops.search_completed"] = "soothe.tool.file_ops.search_completed"
    query: str = ""
    results_count: int = 0
    duration_ms: int = 0

class SearchFailedEvent(ToolEvent):
    type: Literal["soothe.tool.file_ops.search_failed"] = "soothe.tool.file_ops.search_failed"
    query: str = ""
    error: str = ""
```

### 5.4 Error Recovery Response

```python
@dataclass
class ToolErrorResponse:
    error: str                      # Short description
    details: dict[str, Any]         # Context-specific details
    suggestions: list[str]          # Recovery suggestions
    recoverable: bool               # Retry possible?
    auto_retry_hint: str | None     # Example command for retry
```

---

## 6. Interface Contracts

### 6.1 Shell Execution Tools

```python
class RunCommandTool(BaseTool):
    name: str = "run_command"
    description: str = "Execute shell command synchronously."

    def _run(self, command: str, timeout: int = 60) -> str:
        """Execute shell command synchronously.

        Args:
            command: Shell command to execute.
            timeout: Maximum execution time in seconds.

        Returns:
            Command output (stdout + stderr).
        """
        ...

class RunBackgroundTool(BaseTool):
    name: str = "run_background"
    description: str = "Execute command in background process."

    def _run(self, command: str) -> dict[str, Any]:
        """Execute command in background.

        Args:
            command: Shell command to execute.

        Returns:
            Dict with pid, status, and initial output.
        """
        ...

class KillProcessTool(BaseTool):
    name: str = "kill_process"
    description: str = "Terminate background process."

    def _run(self, pid: int) -> str:
        """Terminate background process.

        Args:
            pid: Process ID to terminate.

        Returns:
            Confirmation message.
        """
        ...
```

### 6.2 Python Execution Tool

```python
class RunPythonTool(BaseTool):
    name: str = "run_python"
    description: str = "Execute Python code in persistent session."

    def _run(self, code: str, session_id: str | None = None) -> dict[str, Any]:
        """Execute Python code with session persistence.

        Variables persist across calls within the same thread.

        Args:
            code: Python code to execute.
            session_id: Optional session override (uses thread ID by default).

        Returns:
            Dict with result, stdout, stderr, and execution_time_ms.
        """
        ...
```

### 6.3 File Operation Tools

```python
class ReadFileTool(BaseTool):
    name: str = "read_file"
    description: str = "Read file contents with optional line range."

    def _run(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> str:
        """Read file contents.

        Args:
            path: File path to read.
            start_line: Optional start line (1-indexed).
            end_line: Optional end line (inclusive).

        Returns:
            File contents (or line range if specified).
        """
        ...

class WriteFileTool(BaseTool):
    name: str = "write_file"
    description: str = "Write content to file."

    def _run(
        self,
        path: str,
        content: str,
        mode: Literal["overwrite", "append"] = "overwrite",
    ) -> str:
        """Write content to file.

        Args:
            path: File path to write.
            content: Content to write.
            mode: Write mode (overwrite or append).

        Returns:
            Confirmation message with bytes written.
        """
        ...

class SearchFilesTool(BaseTool):
    name: str = "search_files"
    description: str = "Search for pattern in files."

    def _run(
        self,
        pattern: str,
        path: str = ".",
        file_pattern: str = "*",
    ) -> list[dict[str, Any]]:
        """Search for pattern in files.

        Args:
            pattern: Regex or literal pattern to search.
            path: Directory to search (default: current).
            file_pattern: Glob pattern for files (default: all).

        Returns:
            List of matches with file, line, content.
        """
        ...
```

### 6.4 Code Editing Tools

```python
class EditFileLinesTool(BaseTool):
    name: str = "edit_file_lines"
    description: str = "Replace specific lines in file."

    def _run(
        self,
        path: str,
        start_line: int,
        end_line: int,
        new_content: str,
    ) -> str:
        """Replace lines in file.

        Args:
            path: File path to edit.
            start_line: First line to replace (1-indexed).
            end_line: Last line to replace (inclusive).
            new_content: New content for those lines.

        Returns:
            Confirmation with diff preview.
        """
        ...

class InsertLinesTool(BaseTool):
    name: str = "insert_lines"
    description: str = "Insert lines at position in file."

    def _run(self, path: str, line: int, content: str) -> str:
        """Insert lines at position.

        Args:
            path: File path to modify.
            line: Line number to insert at (before this line).
            content: Content to insert.

        Returns:
            Confirmation message.
        """
        ...

class ApplyDiffTool(BaseTool):
    name: str = "apply_diff"
    description: str = "Apply unified diff to file."

    def _run(self, path: str, diff: str) -> str:
        """Apply unified diff.

        Args:
            path: File path to modify.
            diff: Unified diff content.

        Returns:
            Confirmation with lines changed.
        """
        ...
```

---

## 7. Implementation Patterns

### 7.1 Single-Purpose Design

Each tool does ONE thing:

```
Bad:  execute(code, mode="shell|python|background", ...)
Good: run_command(command), run_python(code), run_background(command)
```

### 7.2 Session Management

Python execution maintains state across calls:

```python
class SessionManager:
    _sessions: dict[str, InteractiveShell]  # thread_id → shell

    def get_or_create(self, thread_id: str) -> InteractiveShell:
        """Get or create persistent Python session."""
        ...

    def cleanup(self, thread_id: str) -> None:
        """Cleanup session when thread ends."""
        ...
```

### 7.3 Event Emission Pattern

```python
# Atomic operation - single event
emit_progress(BackupEvent(
    original_path=str(file_path),
    backup_path=str(backup_path),
).to_dict(), logger)

# Async operation - triplet
emit_progress(SearchStartedEvent(query=query).to_dict(), logger)
# ... execution ...
emit_progress(SearchCompletedEvent(
    query=query,
    results_count=len(results),
    duration_ms=duration,
).to_dict(), logger)
```

### 7.4 Error Response Pattern

```python
def error_response(
    error: str,
    details: dict[str, Any],
    suggestions: list[str],
    recoverable: bool = True,
) -> ToolErrorResponse:
    """Create standardized error response."""
    return ToolErrorResponse(
        error=error,
        details=details,
        suggestions=suggestions,
        recoverable=recoverable,
        auto_retry_hint=suggestions[0] if suggestions else None,
    )
```

---

## 8. Examples

### 8.1 Tool Directory Structure

```
tools/
├── execution/           # run_command, run_python, run_background, kill_process
│   ├── __init__.py
│   ├── events.py
│   └── implementation.py
├── file_ops/            # read_file, write_file, delete_file, search_files
│   ├── __init__.py
│   ├── events.py
│   └── implementation.py
├── code_edit/           # edit_file_lines, insert_lines, delete_lines, apply_diff
│   ├── __init__.py
│   ├── events.py
│   └── implementation.py
├── image/               # analyze_image, extract_text
├── audio/               # transcribe_audio, audio_qa
├── video/               # analyze_video, video_info
├── websearch/           # web_search, crawl_url
├── research/            # research_query
├── data/                # data_analysis
└── datetime/            # current_datetime
```

### 8.2 Tool Selection Flow

```
LLM receives prompt → selects tool → calls with correct parameters

Before (unified): execute(mode="shell", code="ls")
  → LLM forgets mode, tries execute(code="ls") → fails

After (single-purpose): run_command(command="ls")
  → LLM sees obvious tool name → succeeds
```

---

## 9. Relationship to Other RFCs

* **RFC-100 (CoreAgent Runtime)**: Tool execution runtime
* **RFC-400 (Event Processing)**: Event pipeline that processes tool events
* **RFC-102 (Security Policy)**: Permission checks for tool invocation
* **RFC-500 (CLI/TUI Architecture)**: Tool output display

---

## 10. Open Questions

1. Should `run_command` auto-detect long-running commands and suggest `run_background`?
2. Should `edit_file_lines` support regex replacement within line range?
3. Maximum concurrent Python sessions per thread?
4. Event throttling for high-frequency operations?

---

## 11. Conclusion

This RFC establishes clear interface contracts for Soothe's tool layer:

- Single-purpose tools reduce cognitive load and improve success rates
- Event naming conventions distinguish atomic from async operations
- Standardized error responses enable better recovery guidance

> **One tool, one job. One event, clear pattern.**