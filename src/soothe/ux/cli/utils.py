"""CLI rendering utilities.

This module provides helper functions for creating plain-text output
to stderr, following the same visual patterns as TUI but without Rich widgets.
"""

from __future__ import annotations


def make_dot_line(color_name: str, text: str, body: str | None = None) -> str:  # noqa: ARG001
    """Create a line with dot prefix and optional child content.

    Args:
        color_name: Color name (ignored in CLI, for API compatibility with TUI).
        text: Main text to display after the dot.
        body: Optional body content to show with tree connector.

    Returns:
        Plain text formatted as:
            ● text
              └ body

    Note: Color is ignored in CLI mode since we output to plain stderr.
    """
    result = f"● {text}"

    if body is not None:
        # Split body into lines and add tree connector
        lines = body.split("\n")
        for i, line in enumerate(lines):
            if i == 0:
                result += f"\n  └ {line}"
            else:
                result += f"\n    {line}"

    return result


def make_tool_block(
    name: str,
    args_summary: str,
    output: str | None = None,
    status: str = "running",  # noqa: ARG001
) -> str:
    """Create a tool block with dot prefix and optional output.

    Args:
        name: Tool name to display.
        args_summary: Summary of tool arguments.
        output: Optional tool output to show with tree connector.
        status: Tool status - 'running', 'success', or 'error'.

    Returns:
        Plain text formatted as:
            ⚙ ToolName(args_summary)
              └ output
    """
    # Use gear icon for tools (matches TUI pattern)
    result = f"⚙ {name}({args_summary})"

    if output is not None:
        # Add output with tree connector
        lines = output.split("\n")
        for i, line in enumerate(lines):
            if i == 0:
                result += f"\n  └ {line}"
            else:
                result += f"\n    {line}"

    return result


__all__ = [
    "make_dot_line",
    "make_tool_block",
]
