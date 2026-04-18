"""Formatting utilities for tool call display in the CLI.

This module handles rendering tool calls and tool messages for the TUI.

Imported at module level by `textual_adapter` (itself deferred from the startup
path). Heavy SDK dependencies (e.g., `backends`) are deferred to function bodies.
"""

from contextlib import suppress
from pathlib import Path
from typing import Any

from soothe_cli.shared.message_processing import (
    _normalize_tool_name_for_arg_map,
    extract_tool_args_dict,
)
from soothe_cli.tui.config import MAX_ARG_LENGTH, get_glyphs
from soothe_cli.tui.unicode_security import strip_dangerous_unicode

_HIDDEN_CHAR_MARKER = " [hidden chars removed]"
"""Marker appended to display values that had dangerous Unicode stripped, so
users know the value was modified for safety."""


def _format_timeout(seconds: int) -> str:
    """Format timeout in human-readable units (e.g., 300 -> '5m', 3600 -> '1h').

    Args:
        seconds: The timeout value in seconds to format.

    Returns:
        Human-readable timeout string (e.g., '5m', '1h', '300s').
    """
    if seconds < 60:  # noqa: PLR2004  # Time unit boundary
        return f"{seconds}s"
    if seconds < 3600 and seconds % 60 == 0:  # noqa: PLR2004  # Time unit boundaries
        return f"{seconds // 60}m"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    # For odd values, just show seconds
    return f"{seconds}s"


def _coerce_timeout_seconds(timeout: int | str | None) -> int | None:
    """Normalize timeout values to seconds for display.

    Accepts integer values and numeric strings. Returns `None` for invalid
    values so display formatting never raises.

    Args:
        timeout: Raw timeout value from tool arguments.

    Returns:
        Integer timeout in seconds, or `None` if unavailable/invalid.
    """
    if type(timeout) is int:
        return timeout
    if isinstance(timeout, str):
        stripped = timeout.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def truncate_value(value: str, max_length: int = MAX_ARG_LENGTH) -> str:
    """Truncate a string value if it exceeds max_length.

    Returns:
        Truncated string with ellipsis suffix if exceeded, otherwise original.
    """
    if len(value) > max_length:
        return value[:max_length] + get_glyphs().ellipsis
    return value


def _sanitize_display_value(value: object, *, max_length: int = MAX_ARG_LENGTH) -> str:
    """Sanitize a value for safe, compact terminal display.

    Hidden/deceptive Unicode controls are stripped. When stripping occurs, a
    marker is appended so users know the value changed for display safety.

    Args:
        value: Any value to display.
        max_length: Maximum display length before truncation.

    Returns:
        Sanitized display string.
    """
    raw = str(value)
    sanitized = strip_dangerous_unicode(raw)
    display = truncate_value(sanitized, max_length)
    if sanitized != raw:
        return display + _HIDDEN_CHAR_MARKER
    return display


def _first_nonempty_str_arg(tool_args: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """Return the first present, non-empty string value for any of ``keys``."""
    for k in keys:
        v = tool_args.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def format_tool_display(tool_name: str, tool_args: dict) -> str:
    """Format tool calls for display with tool-specific smart formatting.

    Shows the most relevant information for each tool type rather than all arguments.

    Args:
        tool_name: Name of the tool being called
        tool_args: Dictionary of tool arguments

    Returns:
        Formatted string for display (e.g., "(*) read_file(config.py)" in ASCII mode)

    Examples:
        read_file(path="/long/path/file.py") → "<prefix> read_file(file.py)"
        web_search(query="how to code") → '<prefix> web_search("how to code")'
        execute(command="pip install foo") → '<prefix> execute("pip install foo")'
    """
    prefix = get_glyphs().tool_prefix
    tool_args = extract_tool_args_dict(tool_args) if tool_args else {}
    tool_key = _normalize_tool_name_for_arg_map(tool_name or "")

    def abbreviate_path(path_str: str, max_length: int = 60) -> str:
        """Abbreviate a file path intelligently - show basename or relative path.

        Returns:
            Shortened path string suitable for display.
        """
        try:
            path = Path(path_str)

            # If it's just a filename (no directory parts), return as-is
            if len(path.parts) == 1:
                return path_str

            # Try to get relative path from current working directory
            with suppress(
                ValueError,  # ValueError: path is not relative to cwd
                OSError,  # OSError: filesystem errors when resolving paths
            ):
                rel_path = path.relative_to(Path.cwd())
                rel_str = str(rel_path)
                # Use relative if it's shorter and not too long
                if len(rel_str) < len(path_str) and len(rel_str) <= max_length:
                    return rel_str

            # If absolute path is reasonable length, use it
            if len(path_str) <= max_length:
                return path_str
        except Exception:  # noqa: BLE001  # Fallback to original string on any path resolution error
            return truncate_value(path_str, max_length)
        else:
            # Otherwise, just show basename (filename only)
            return path.name

    # Tool-specific formatting - show the most important argument(s).
    # Branch on normalized ``tool_key`` so PascalCase names (``ReadFile``) still match;
    # display the original ``tool_name`` substring for consistency with model output.
    if tool_key in {"read_file", "write_file", "edit_file"}:
        raw_path = _first_nonempty_str_arg(
            tool_args,
            ("file_path", "path", "path_name", "target_file", "file", "filepath"),
        )
        if raw_path is not None:
            path_raw = strip_dangerous_unicode(raw_path)
            path = abbreviate_path(path_raw)
            if path_raw != raw_path:
                path += _HIDDEN_CHAR_MARKER
            return f"{prefix} {tool_name}({path})"

    elif tool_key == "web_search":
        # Web search: show the query string
        if "query" in tool_args:
            query = _sanitize_display_value(tool_args["query"], max_length=100)
            return f'{prefix} {tool_name}("{query}")'

    elif tool_key == "grep":
        pat = _first_nonempty_str_arg(tool_args, ("pattern", "regex", "regexp"))
        if pat is not None:
            pattern = _sanitize_display_value(pat, max_length=70)
            return f'{prefix} {tool_name}("{pattern}")'

    elif tool_key in {"execute", "shell", "bash", "run_command"}:
        # Execute: show the command, and timeout only if non-default
        cmd = _first_nonempty_str_arg(tool_args, ("command", "cmd", "script"))
        if cmd is not None:
            command = _sanitize_display_value(cmd, max_length=120)
            timeout = _coerce_timeout_seconds(tool_args.get("timeout"))
            from soothe_sdk.client.config import DEFAULT_EXECUTE_TIMEOUT

            if timeout is not None and timeout != DEFAULT_EXECUTE_TIMEOUT:
                timeout_str = _format_timeout(timeout)
                return f'{prefix} {tool_name}("{command}", timeout={timeout_str})'
            return f'{prefix} {tool_name}("{command}")'

    elif tool_key in {"ls", "list_files"}:
        # ls / list_files: directory varies by provider (path, directory, …).
        # Show explicit cwd (".") — omitting it produced bare ls() and looked like missing args.
        path_keys = (
            "path",
            "path_name",
            "directory",
            "target_directory",
            "dir",
            "folder",
        )
        raw_path_val = None
        for k in path_keys:
            if k in tool_args:
                raw_path_val = tool_args.get(k)
                break
        if raw_path_val is not None:
            s = str(raw_path_val).strip()
            if s == "":
                pass
            elif s == ".":
                return f"{prefix} {tool_name}(.)"
            else:
                path_raw = strip_dangerous_unicode(s)
                path = abbreviate_path(path_raw)
                if path_raw != s:
                    path += _HIDDEN_CHAR_MARKER
                return f"{prefix} {tool_name}({path})"
        if tool_key == "list_files":
            pat = _first_nonempty_str_arg(tool_args, ("pattern", "glob_pattern", "glob"))
            if pat is not None and pat != "*":
                pshown = _sanitize_display_value(pat, max_length=80)
                return f'{prefix} {tool_name}("{pshown}")'
        return f"{prefix} {tool_name}()"

    elif tool_key == "glob":
        pat = _first_nonempty_str_arg(
            tool_args,
            ("pattern", "glob_pattern", "glob", "glob_file_pattern", "include"),
        )
        if pat is not None:
            pattern = _sanitize_display_value(pat, max_length=80)
            return f'{prefix} {tool_name}("{pattern}")'
        loc_raw = None
        for k in ("path", "directory", "dir", "root", "cwd", "base_path"):
            if k in tool_args and tool_args[k] is not None:
                loc_raw = str(tool_args[k]).strip()
                if loc_raw:
                    break
        if loc_raw is not None:
            path_raw = strip_dangerous_unicode(loc_raw)
            path = abbreviate_path(path_raw)
            if path_raw != loc_raw:
                path += _HIDDEN_CHAR_MARKER
            return f"{prefix} {tool_name}(dir={path})"
        if tool_args:
            args_str = ", ".join(
                f"{_sanitize_display_value(k, max_length=30)}={_sanitize_display_value(v, max_length=50)}"
                for k, v in tool_args.items()
            )
            return f"{prefix} {tool_name}({args_str})"
        return f"{prefix} {tool_name}()"

    elif tool_key == "fetch_url":
        # Fetch URL: show the URL being fetched
        if "url" in tool_args:
            url = _sanitize_display_value(tool_args["url"], max_length=80)
            return f'{prefix} {tool_name}("{url}")'

    elif tool_key == "task":
        # Task: show subagent type badge
        agent_type = tool_args.get("subagent_type", "")
        if agent_type:
            agent_type = _sanitize_display_value(agent_type, max_length=40)
            return f"{prefix} {tool_name} [{agent_type}]"
        return f"{prefix} {tool_name}"

    elif tool_key == "ask_user":
        if "questions" in tool_args and isinstance(tool_args["questions"], list):
            count = len(tool_args["questions"])
            label = "question" if count == 1 else "questions"
            return f"{prefix} {tool_name}({count} {label})"

    elif tool_key == "compact_conversation":
        return f"{prefix} {tool_name}()"

    elif tool_key == "write_todos":
        if "todos" in tool_args and isinstance(tool_args["todos"], list):
            count = len(tool_args["todos"])
            return f"{prefix} {tool_name}({count} items)"

    # Fallback: generic formatting for unknown tools
    # Show all arguments in key=value format
    args_str = ", ".join(
        f"{_sanitize_display_value(k, max_length=30)}={_sanitize_display_value(v, max_length=50)}"
        for k, v in tool_args.items()
    )
    return f"{prefix} {tool_name}({args_str})"
