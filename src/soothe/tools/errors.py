"""Standardized error response format for tools (RFC-0016 Phase 4).

Provides structured error responses with contextual suggestions and
actionable guidance for recovery.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ToolError(BaseModel):
    """Standardized tool error response.

    All tools should return errors in this format to provide
    consistent, actionable guidance for the LLM.
    """

    error: str  # Short error description
    details: dict[str, Any] = {}  # Context-specific details
    suggestions: list[str] = []  # Recovery suggestions
    recoverable: bool = True  # Whether retry is possible
    auto_retry_hint: str | None = None  # Example command for retry

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for tool return."""
        return {
            "error": self.error,
            "details": self.details,
            "suggestions": self.suggestions,
            "recoverable": self.recoverable,
            "auto_retry_hint": self.auto_retry_hint,
        }


# Common error patterns


def file_not_found_error(path: str, action: str) -> ToolError:
    """Generate file not found error with suggestions."""
    return ToolError(
        error="File not found",
        details={"path": path, "action": action},
        suggestions=[
            "Check the file path is correct",
            "Use list_files to see available files",
            "Use search_files to find similar files",
        ],
        recoverable=True,
        auto_retry_hint=f"list_files(path='{path.rsplit('/', 1)[0] if '/' in path else '.'}')",
    )


def file_already_exists_error(path: str) -> ToolError:
    """Generate file already exists error with suggestions."""
    return ToolError(
        error="File already exists",
        details={"path": path},
        suggestions=[
            "Use read_file first to check current contents",
            "Use edit_file_lines to modify specific sections",
            "Use write_file with mode='overwrite' to replace entirely",
        ],
        recoverable=True,
        auto_retry_hint=f"read_file(path='{path}')",
    )


def invalid_line_range_error(start_line: int, end_line: int, total_lines: int, operation: str) -> ToolError:
    """Generate invalid line range error."""
    return ToolError(
        error="Invalid line range",
        details={"start_line": start_line, "end_line": end_line, "total_lines": total_lines, "operation": operation},
        suggestions=[
            f"Valid line range: 1 to {total_lines}",
            "Use read_file to check file contents first",
            "Line numbers are 1-indexed (start at 1, not 0)",
        ],
        recoverable=True,
        auto_retry_hint=f"read_file(path='<path>', start_line=1, end_line={min(total_lines, 20)})",
    )


def command_not_found_error(command: str) -> ToolError:
    """Generate command not found error."""
    suggestions = ["Check the command name is correct"]

    # Try to suggest similar commands
    base_cmd = command.split(maxsplit=1)[0] if " " in command else command
    common_commands = ["ls", "cat", "grep", "find", "python", "pip", "git", "npm", "docker"]
    similar = [cmd for cmd in common_commands if base_cmd in cmd or cmd in base_cmd]

    if similar:
        suggestions.append(f"Did you mean: {', '.join(similar)}?")

    return ToolError(
        error="Command not found",
        details={"command": command},
        suggestions=suggestions,
        recoverable=False,
        auto_retry_hint=None,
    )


def command_timeout_error(command: str, timeout: int) -> ToolError:
    """Generate command timeout error."""
    return ToolError(
        error="Command timed out",
        details={"command": command, "timeout": timeout},
        suggestions=[
            f"Command took longer than {timeout} seconds",
            "Use run_background for long-running commands",
            "Check if the command is waiting for input",
        ],
        recoverable=True,
        auto_retry_hint=f"run_background(command='{command}')",
    )


def python_execution_error(code: str, error_msg: str) -> ToolError:
    """Generate Python execution error."""
    suggestions = ["Check the Python syntax"]

    # Parse error type for specific suggestions
    if "NameError" in error_msg:
        suggestions.append("The variable or function is not defined")
        suggestions.append("Check for typos in variable names")
    elif "SyntaxError" in error_msg:
        suggestions.append("Check for missing parentheses, brackets, or quotes")
    elif "ImportError" in error_msg or "ModuleNotFoundError" in error_msg:
        suggestions.append("The module is not installed")
        suggestions.append("Install with: pip install <module_name>")
    elif "TypeError" in error_msg:
        suggestions.append("Check the function arguments and types")
    elif "ValueError" in error_msg:
        suggestions.append("Check the value is valid for the operation")

    return ToolError(
        error="Python execution failed",
        details={"error_type": error_msg.split(":", maxsplit=1)[0] if ":" in error_msg else "Unknown"},
        suggestions=suggestions,
        recoverable=True,
        auto_retry_hint=None,
    )


def permission_denied_error(path: str, action: str) -> ToolError:
    """Generate permission denied error."""
    return ToolError(
        error="Permission denied",
        details={"path": path, "action": action},
        suggestions=[
            "Check file permissions",
            "Verify you have write access to the directory",
            "Try a different location",
        ],
        recoverable=False,
        auto_retry_hint=None,
    )


def directory_not_found_error(path: str) -> ToolError:
    """Generate directory not found error."""
    return ToolError(
        error="Directory not found",
        details={"path": path},
        suggestions=[
            "Check the directory path is correct",
            "Use list_files to see available directories",
            "Create the directory first if needed",
        ],
        recoverable=True,
        auto_retry_hint=f"list_files(path='{path.rsplit('/', 1)[0] if '/' in path else '.'}')",
    )
