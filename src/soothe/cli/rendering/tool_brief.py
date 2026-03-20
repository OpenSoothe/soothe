"""Shared utility functions for CLI rendering.

This module consolidates duplicated helper functions from across the CLI codebase.
"""

from __future__ import annotations


def extract_tool_brief(tool_name: str, content: str, max_length: int = 120) -> str:
    r"""Extract a concise one-line summary from tool result content.

    For search tools (wizsearch), the first line is typically a human-readable
    header like "20 results in 15.0s for 'query'" — use that instead of the raw
    content which may contain XML tags and source data.

    Args:
        tool_name: Name of the tool that produced the content.
        content: Tool result content as string.
        max_length: Maximum length of the brief (default 120).

    Returns:
        Truncated brief suitable for display.

    Example:
        >>> extract_tool_brief("wizsearch", "10 results in 1.2s for 'python'\n...more data...")
        "10 results in 1.2s for 'python'"
    """
    if tool_name.startswith("wizsearch"):
        first_line = content.split("\n", 1)[0].strip()
        if first_line:
            return first_line[:max_length]
    return content.replace("\n", " ")[:max_length]
