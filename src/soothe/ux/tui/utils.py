"""TUI rendering utilities.

This module provides helper functions for creating Rich Text renderables
used by the TUI. Event processing is handled by EventProcessor (RFC-0019).
"""

from __future__ import annotations

from rich.text import Text

# Claude Code-style dot prefix colors for different event types
DOT_COLORS: dict[str, str] = {
    "assistant": "blue",
    "success": "green",
    "error": "red",
    "progress": "yellow",
    "subagent": "magenta",
    "protocol": "dim",
}


def make_dot_line(color: str, text: str | Text, body: str | Text | None = None) -> Text:
    """Create a Claude Code-style line with colored dot prefix.

    Args:
        color: Rich color name for the dot (e.g., 'blue', 'green', 'red').
        text: Main text to display after the dot.
        body: Optional body content to show on subsequent lines with tree connector.

    Returns:
        Rich Text with `● ` prefix in the given color, followed by the text.
        If body is provided, it's appended on the next line(s) with `  └ ` indent.
    """
    dot = Text("● ", style=color)
    main_text = Text(text) if isinstance(text, str) else text

    result = Text()
    result.append(dot)
    result.append(main_text)

    if body is not None:
        result.append("\n")
        if isinstance(body, str):
            # Split body into lines and add tree connector to first line
            lines = body.split("\n")
            for i, line in enumerate(lines):
                if i == 0:
                    result.append(Text("  └ ", style="dim"))
                else:
                    result.append(Text("    ", style="dim"))
                result.append(line)
                if i < len(lines) - 1:
                    result.append("\n")
        else:
            result.append(Text("  └ ", style="dim"))
            result.append(body)

    return result


def make_user_prompt_line(text: str) -> Text:
    """Create a user prompt line with heavy right-pointing angle prefix.

    Args:
        text: The user input text to display.

    Returns:
        Rich Text with prompt prefix styled in bold white/bright.
    """
    result = Text()
    result.append("\u276f ", style="bold bright_white")
    result.append(text, style="bold bright_white")
    return result


def make_tool_block(
    name: str,
    args_summary: str,
    output: str | None = None,
    status: str = "running",
) -> Text:
    """Create a Claude Code-style tool block with dot prefix.

    Args:
        name: Tool name to display.
        args_summary: Summary of tool arguments (e.g., "path='/foo'").
        output: Optional tool output to show with tree connector.
        status: Tool status - 'running' (yellow), 'success' (green), 'error' (red).

    Returns:
        Rich Text formatted as:
            ● ToolName(args_summary)
              └ output line 1
                output line 2
    """
    # Determine dot color based on status
    if status == "success":
        dot_color = "green"
    elif status == "error":
        dot_color = "red"
    else:  # running or any other status
        dot_color = "yellow"

    # Build the tool call line
    tool_text = Text()
    tool_text.append(name, style="bold")
    tool_text.append(f"({args_summary})")

    return make_dot_line(dot_color, tool_text, output)


def make_status_line(text: str, elapsed: str = "") -> Text:
    """Create a status line with asterisk prefix.

    Args:
        text: Status text to display.
        elapsed: Optional elapsed time string to append in parentheses.

    Returns:
        Rich Text formatted as `* {text} ({elapsed})` in yellow/dim style.
    """
    result = Text()
    result.append("* ", style="yellow dim")
    result.append(text, style="yellow dim")
    if elapsed:
        result.append(f" ({elapsed})", style="dim")
    return result
