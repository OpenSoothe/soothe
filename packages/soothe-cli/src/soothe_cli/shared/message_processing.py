"""Shared message processing utilities for CLI and TUI modes.

This module provides helper functions for message handling logic to ensure
consistent behavior between headless CLI mode and the TUI interface.
"""

from __future__ import annotations

import contextlib
import json
import re
from typing import Any

from soothe_sdk.ux.internal import (
    strip_internal_tags,  # noqa: F401 — re-exported via shared.__init__
)

# ============================================================================
# Shared Tool Call Streaming Helpers (IG-053)
# ============================================================================


def accumulate_tool_call_chunks(
    pending_tool_calls: dict[str, dict[str, Any]],
    tool_call_chunks: list[dict[str, Any]],
    *,
    is_main: bool = True,
) -> None:
    """Accumulate streaming tool call chunks into pending_tool_calls.

    LangChain streams tool args in chunks - first chunk has the tool name but
    empty args, subsequent chunks contain partial JSON strings. This function
    tracks and accumulates them.

    Args:
        pending_tool_calls: Dict to store pending tool calls (tool_call_id -> state).
        tool_call_chunks: List of tool_call_chunk dicts from AIMessageChunk.
        is_main: Whether this is from the main agent.
    """
    for tcc in tool_call_chunks:
        if not isinstance(tcc, dict):
            continue
        tc_id = tcc.get("id", "")
        tc_name = tcc.get("name")
        tc_args = tcc.get("args", "")

        # First chunk with a tool name: register the pending tool call
        if tc_name and tc_id and tc_id not in pending_tool_calls:
            if isinstance(tc_args, str):
                args_str = tc_args
            elif isinstance(tc_args, dict) and tc_args:
                args_str = json.dumps(tc_args)
            else:
                args_str = ""
            pending_tool_calls[tc_id] = {
                "name": tc_name,
                "args_str": args_str,
                "emitted": False,
                "is_main": is_main,
            }
        # Some providers send final args as a dict on a later chunk
        elif tc_id in pending_tool_calls and isinstance(tc_args, dict) and tc_args:
            pending_tool_calls[tc_id]["args_str"] = json.dumps(tc_args)
        # Subsequent chunks: accumulate partial JSON strings
        elif tc_args and isinstance(tc_args, str):
            # Find the tool call to accumulate args for (by order, first non-emitted)
            for pending in pending_tool_calls.values():
                if not pending["emitted"]:
                    pending["args_str"] += tc_args
                    break


def try_parse_pending_tool_call_args(
    pending: dict[str, Any],
) -> dict[str, Any] | None:
    """Try to parse the accumulated args_str as JSON.

    Args:
        pending: Pending tool call state dict with 'args_str' key.

    Returns:
        Parsed args dict if valid JSON, None otherwise.
    """
    args_str = pending.get("args_str", "")
    if not args_str:
        return None
    try:
        parsed = json.loads(args_str)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def finalize_pending_tool_call(
    pending_tool_calls: dict[str, dict[str, Any]],
    tool_call_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], bool, str]:
    """Finalize and remove a pending tool call when its result arrives.

    Args:
        pending_tool_calls: Dict of pending tool calls.
        tool_call_id: ID of the tool call to finalize.

    Returns:
        Tuple of (parsed_args, pending_state dict, needs_emit, raw_args_str).
        - parsed_args: Parsed args dict if valid JSON, None otherwise.
        - pending_state: The pending tool call state dict.
        - needs_emit: True if the tool call wasn't emitted yet.
        - raw_args_str: Raw args string for display fallback.
        If not found, returns (None, {}, False, "").
    """
    str_id = str(tool_call_id) if tool_call_id else ""
    if not str_id or str_id not in pending_tool_calls:
        return None, {}, False, ""

    pending = pending_tool_calls[str_id]
    parsed_args = None
    needs_emit = not pending.get("emitted", False)
    raw_args_str = pending.get("args_str", "")

    if needs_emit:
        # Try to parse args one more time
        if raw_args_str:
            with contextlib.suppress(json.JSONDecodeError):
                result = json.loads(raw_args_str)
                if isinstance(result, dict):
                    parsed_args = result
        pending["emitted"] = True

    # Clean up the pending entry
    del pending_tool_calls[str_id]
    return parsed_args, pending, needs_emit, raw_args_str


def extract_tool_brief(tool_name: str, content: str | dict | Any, max_length: int = 120) -> str:
    r"""Extract a concise one-line summary from tool result content.

    Uses semantic formatters to provide tool-specific summaries with meaningful
    metrics (size, count, status) instead of simple truncation.

    Args:
        tool_name: Name of the tool that produced the content.
        content: Tool result content (string, dict, or ToolOutput).
        max_length: Maximum length of the brief (default 120, unused for semantic formatting).

    Returns:
        Semantic brief suitable for display.

    Example:
        >>> extract_tool_brief("read_file", "Hello\\nWorld\\n")
        "✓ Read 12 B (2 lines)"
        >>> extract_tool_brief("run_command", "output")
        "✓ Done (6 chars output)"
    """
    # Use semantic formatter for tool-specific summarization
    from soothe_cli.shared.tool_output_formatter import ToolOutputFormatter

    try:
        formatter = ToolOutputFormatter()
        brief = formatter.format(tool_name, content)
        return brief.to_display()
    except Exception:
        # Fallback to simple truncation if formatter fails
        if isinstance(content, str):
            # Web search/crawl tools return structured output with summary on first line
            web_tools = {"search_web", "crawl_web"}
            if tool_name in web_tools:
                first_line = content.split("\n", 1)[0].strip()
                if first_line:
                    return first_line[:max_length]
            return content.replace("\n", " ")[:max_length]
        if isinstance(content, dict):
            # Simple dict formatting
            return f"Dict with {len(content)} fields"
        return str(content)[:max_length]


def coerce_tool_call_args_to_dict(raw: Any) -> dict[str, Any]:
    """Normalize tool arguments for display.

    ``tool_call_chunk`` content blocks use a JSON string; merged ``tool_calls`` use dicts
    (see LangChain ``ToolCall`` / ``ToolCallChunk``).
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {}
    return {}


def coerce_tool_call_entry_to_dict(tc: Any) -> dict[str, Any] | None:
    """Normalize a ``tool_calls`` entry to a plain dict (handles Pydantic models)."""
    if isinstance(tc, dict):
        return tc
    model_dump = getattr(tc, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            return None
    return None


def normalize_tool_calls_list(raw: list[Any]) -> list[dict[str, Any]]:
    """Coerce ``msg.tool_calls`` to ``dict`` entries for display logic."""
    out: list[dict[str, Any]] = []
    for tc in raw:
        coerced = coerce_tool_call_entry_to_dict(tc)
        if coerced:
            out.append(coerced)
    return out


def tool_calls_have_any_arg_dict(tc_list: list[Any]) -> bool:
    """True if any tool call has non-empty coerced argument dict."""
    return any(
        coerce_tool_call_args_to_dict(tc.get("args")) for tc in normalize_tool_calls_list(tc_list)
    )


# Argument display mapping for tool calls (see IG-053)
# Maps tool name to list of argument keys to display (supports multiple args)
_ARG_DISPLAY_MAP: dict[str, list[str]] = {
    # File operations — deepagents uses ``file_path`` for read/write/edit (see IG-053)
    "read_file": ["file_path", "path", "path_name"],
    "write_file": ["file_path", "path"],
    "delete_file": ["file_path", "path"],
    "file_info": ["path", "file_path"],
    "edit_file_lines": ["path", "file_path"],
    "insert_lines": ["path", "file_path"],
    "delete_lines": ["path", "file_path"],
    "apply_diff": ["path", "file_path"],
    "edit_file": ["file_path", "path"],
    # Models vary: ``path``, ``directory`` (deepagents), ``target_directory``
    "ls": ["path", "path_name", "directory", "target_directory", "dir", "pattern"],
    "glob": ["pattern", "path"],  # Glob tool
    "list_files": ["pattern"],
    "search_files": ["pattern"],
    # Execution - show command/code
    "run_command": ["command", "args"],  # Multiple args support
    "run_python": ["code"],
    "run_background": ["command"],
    "kill_process": ["pid"],
    "execute": ["command"],  # Alias for run_command
    # Search - show pattern/query
    "search_web": ["query"],
    "crawl_web": ["url"],
    # Research - show topic
    "research": ["topic", "domain"],
    # Media - show file path
    "analyze_image": ["image_path"],
    "analyze_video": ["video_path"],
    "transcribe_audio": ["audio_path"],
    # Goals - show description or ID
    "create_goal": ["description"],
    "complete_goal": ["goal_id"],
    "fail_goal": ["goal_id"],
}


def _normalize_tool_name_for_arg_map(tool_name: str) -> str:
    """Map API tool names (any casing) to snake_case for `_ARG_DISPLAY_MAP` lookup."""
    if not tool_name:
        return tool_name
    # PascalCase / camelCase -> snake_case; already-snake names pass through
    return re.sub(r"(?<!^)(?=[A-Z])", "_", tool_name).lower()


def format_tool_call_args(tool_name: str, tool_call: dict[str, Any]) -> str:
    """Format key tool arguments for display (see IG-053).

    Extracts the most relevant argument(s) for each tool type to show
    in activity events. Supports multiple arguments per tool.

    Path arguments are converted from deepagents workspace-relative format
    to actual OS paths and abbreviated for display.

    Args:
        tool_name: Tool name as emitted by the model (snake_case or PascalCase).
        tool_call: Tool call dict with 'args' key containing arguments.
            May also contain '_raw' key with raw args string for fallback display.

    Returns:
        Formatted argument string like "file_name.md" or "/Users/dev/.../file.md, pattern"
        (without outer parentheses - caller adds them).
        Returns "..." when args are empty but tool is known.
        Returns "" if tool is unknown and no args.

    Examples:
        >>> format_tool_call_args("read_file", {"args": {"path": "config.yml"}})
        'config.yml'
        >>> format_tool_call_args("run_command", {"args": {"command": "ls", "args": "-la"}})
        'ls, -la'
        >>> format_tool_call_args("read_file", {"args": {}})
        '...'
        >>> format_tool_call_args("read_file", {"args": {}, "_raw": '{"path": "file.txt"}'})
        'file.txt'
    """
    from soothe_sdk.utils import convert_and_abbreviate_path
    from soothe_sdk.utils.parsing import is_path_argument as _path_arg_name_pattern

    def _is_path_arg_name(key: str) -> bool:
        return _path_arg_name_pattern.match(key) is not None

    max_value_length = 40  # Max length for displayed values

    def _display_path_value(raw: str) -> str:
        out = convert_and_abbreviate_path(raw)
        if len(out) > max_value_length:
            return out[: max_value_length - 3] + "..."
        return out

    args = coerce_tool_call_args_to_dict(tool_call.get("args"))
    internal = _normalize_tool_name_for_arg_map(tool_name)
    key_args = _ARG_DISPLAY_MAP.get(internal)

    # Check for raw args string fallback
    raw_args_str = tool_call.get("_raw") or tool_call.get("raw_args_str", "")

    # If args are empty, try to extract from raw args string
    if not args and raw_args_str:
        # Try to parse raw string as JSON
        with contextlib.suppress(json.JSONDecodeError):
            parsed_raw = json.loads(raw_args_str)
            if isinstance(parsed_raw, dict):
                args = parsed_raw

    # If args are still empty but tool is known, show placeholder
    if not args:
        if key_args:
            # Try to extract value from partial raw args string
            if raw_args_str:
                # Try regex extraction for common patterns like "path": "value" or "path":"value"
                for key_arg in key_args:
                    # Match patterns like "key": "value" or "key":"value"
                    pattern = '"' + key_arg + '"\\s*:\\s*"([^"]+)"'
                    match = re.search(pattern, raw_args_str)
                    if match:
                        value = match.group(1)
                        if _is_path_arg_name(key_arg):
                            value = _display_path_value(value)
                        return value
                    # Also match non-string values like "key": 123 or "key": true
                    pattern2 = '"' + key_arg + '"\\s*:\\s*([^,\\}]+)'
                    match2 = re.search(pattern2, raw_args_str)
                    if match2:
                        val = match2.group(1).strip()
                        # Truncate if too long
                        if len(val) > max_value_length:
                            val = val[: max_value_length - 3] + "..."
                        return val
            return "..."
        return ""

    if not key_args:
        return ""

    # Extract values for all configured argument keys
    values = []
    for key_arg in key_args:
        if key_arg in args:
            value = str(args[key_arg])
            # Convert and abbreviate path arguments
            if _is_path_arg_name(key_arg):
                value = _display_path_value(value)
            elif len(value) > max_value_length:
                # Truncate non-path long values
                value = value[: max_value_length - 3] + "..."
            values.append(value)

    if not values:
        # Model may use different arg names than _ARG_DISPLAY_MAP; still show something useful.
        if args:
            parts: list[str] = []
            # Skip internal keys like _raw, _internal, etc.
            skip_keys = {"_raw", "_internal", "raw_args_str"}
            for k, v in list(args.items())[:3]:
                if k in skip_keys:
                    continue
                s = str(v)
                # Convert and abbreviate path arguments
                if _is_path_arg_name(k):
                    s = _display_path_value(s)
                elif len(s) > max_value_length:
                    s = s[: max_value_length - 3] + "..."
                parts.append(s)
            if parts:
                return ", ".join(parts)
            # All args were internal keys, check for raw_args_str
            raw = args.get("_raw") or args.get("raw_args_str", "")
            if raw:
                # Try to extract from raw JSON
                for key_arg in key_args:
                    pattern = '"' + key_arg + '"\\s*:\\s*"([^"]+)"'
                    match = re.search(pattern, raw)
                    if match:
                        value = match.group(1)
                        if _is_path_arg_name(key_arg):
                            value = _display_path_value(value)
                        return value
        # Known tool but no matching args found
        return "..."

    return ", ".join(values)
