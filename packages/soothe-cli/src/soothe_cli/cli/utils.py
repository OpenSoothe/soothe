"""CLI rendering utilities.

This module provides helper functions for creating plain-text output
to stderr, following the same visual patterns as TUI but without Rich widgets.
"""

from __future__ import annotations


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
    "make_tool_block",
]
