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
        tc_id_raw = tcc.get("id")
        tc_id = str(tc_id_raw) if tc_id_raw not in (None, "") else ""
        tc_name = tcc.get("name")
        tc_args = tcc.get("args", "")

        # First chunk with a tool name: register the pending tool call
        if tc_name and tc_id and tc_id not in pending_tool_calls:
            if isinstance(tc_args, str):
                args_str = tc_args
                is_complete = False  # String may be partial JSON
            elif isinstance(tc_args, dict) and tc_args:
                args_str = json.dumps(tc_args)
                is_complete = True  # Dict yields complete JSON
            else:
                args_str = ""
                is_complete = False  # Empty or missing args
            pending_tool_calls[tc_id] = {
                "name": tc_name,
                "args_str": args_str,
                "is_complete_json": is_complete,
                "emitted": False,
                "is_main": is_main,
            }
        # Some providers send final args as a dict on a later chunk (replace previous)
        elif tc_id and tc_id in pending_tool_calls and isinstance(tc_args, dict) and tc_args:
            pending_tool_calls[tc_id]["args_str"] = json.dumps(tc_args)
            pending_tool_calls[tc_id]["is_complete_json"] = True
        # Subsequent chunks: accumulate partial JSON strings for this tool call id
        elif tc_id and tc_id in pending_tool_calls and isinstance(tc_args, str) and tc_args:
            # If args_str already contains complete JSON, provider refined args → restart
            if pending_tool_calls[tc_id].get("is_complete_json"):
                pending_tool_calls[tc_id]["args_str"] = tc_args
                pending_tool_calls[tc_id]["is_complete_json"] = False
            else:
                # Normal partial accumulation
                pending_tool_calls[tc_id]["args_str"] += tc_args
        elif tc_args and isinstance(tc_args, str) and tc_args:
            # Legacy: chunks missing ``id`` — attach to the first non-emitted pending call
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
            web_tools = {"wizsearch_search", "wizsearch_crawl", "web_search", "fetch_url"}
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


# Keys that are metadata on tool-call blocks / ``tool_calls`` entries, not tool parameters.
_TOOL_CALL_METADATA_KEYS: frozenset[str] = frozenset(
    {"name", "id", "type", "index", "tool_call_id"},
)


def extract_tool_args_dict(tool_like: Any) -> dict[str, Any]:
    """Flatten tool arguments from a ``tool_calls`` entry, content block, or args dict.

    Providers and transports differ: some use ``args``, others ``arguments`` (JSON string),
    Anthropic-style ``input``, or top-level parameter keys without an ``args`` envelope.
    """
    if not isinstance(tool_like, dict):
        return coerce_tool_call_args_to_dict(tool_like)

    base = coerce_tool_call_args_to_dict(tool_like.get("args"))
    if base:
        return base

    base = coerce_tool_call_args_to_dict(tool_like.get("arguments"))
    if base:
        return base

    inp = tool_like.get("input")
    if isinstance(inp, dict) and inp:
        return dict(inp)
    if isinstance(inp, str) and inp.strip():
        base = coerce_tool_call_args_to_dict(inp)
        if base:
            return base

    raw_s = tool_like.get("_raw") or tool_like.get("raw_args_str")
    if isinstance(raw_s, str) and raw_s.strip():
        base = coerce_tool_call_args_to_dict(raw_s)
        if base:
            return base

    skip = _TOOL_CALL_METADATA_KEYS | {"args", "arguments", "input", "_raw", "raw_args_str"}
    flat = {k: v for k, v in tool_like.items() if k not in skip}
    if flat:
        return flat

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
    return any(extract_tool_args_dict(tc) for tc in normalize_tool_calls_list(tc_list))


# Argument display mapping for tool calls (see IG-053)
# Maps tool name to list of argument keys to display (supports multiple args)
# Now derived from the canonical ToolMeta registry (IG-232)
from soothe_sdk.utils import TOOL_REGISTRY  # noqa: E402, I001 -- module-level import after code


def _get_arg_display_map_from_registry() -> dict[str, list[str]]:
    """Derive arg display map from ToolMeta registry."""
    result: dict[str, list[str]] = {}
    seen_ids: set[int] = set()
    for name, meta in TOOL_REGISTRY.items():
        if id(meta) in seen_ids or not meta.arg_keys:
            continue
        seen_ids.add(id(meta))
        result[name] = list(meta.arg_keys)
        for alias in meta.aliases:
            result[alias] = list(meta.arg_keys)
    return result


_ARG_DISPLAY_MAP: dict[str, list[str]] = _get_arg_display_map_from_registry()


def _normalize_tool_name_for_arg_map(tool_name: str) -> str:
    """Map API tool names (any casing) to snake_case for `_ARG_DISPLAY_MAP` lookup."""
    if not tool_name:
        return tool_name
    # PascalCase / camelCase -> snake_case; already-snake names pass through
    return re.sub(r"(?<!^)(?=[A-Z])", "_", tool_name).lower()


_ARG_SUMMARY_SKIP_KEYS: frozenset[str] = frozenset({"_raw", "_internal", "raw_args_str"})


def _compact_tool_args_display_values(
    args: dict[str, Any],
    *,
    max_value_length: int = 40,
    max_items: int = 3,
) -> str:
    """Build comma-separated display values from the first tool parameters (values only)."""
    from soothe_sdk.utils import convert_and_abbreviate_path
    from soothe_sdk.utils.parsing import PATH_ARG_PATTERN as _PATH_ARG_PATTERN

    def _is_path_arg_name(key: str) -> bool:
        return _PATH_ARG_PATTERN.match(key) is not None

    def _display_path_value(raw: str) -> str:
        out = convert_and_abbreviate_path(raw)
        if len(out) > max_value_length:
            return out[: max_value_length - 3] + "..."
        return out

    parts: list[str] = []
    for k, v in args.items():
        if len(parts) >= max_items:
            break
        if k in _ARG_SUMMARY_SKIP_KEYS:
            continue
        s = str(v)
        if _is_path_arg_name(k):
            s = _display_path_value(s)
        elif len(s) > max_value_length:
            s = s[: max_value_length - 3] + "..."
        parts.append(s)
    return ", ".join(parts)


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
        Returns "..." when args are empty but tool is known (or placeholders while streaming).
        Returns "…" when the tool is not in the display map and there are no usable args,
        or when parsed args exist but only contain internal/skip keys.
        For unmapped tools with parameters, returns a compact comma-separated value summary.

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
    from soothe_sdk.utils.parsing import PATH_ARG_PATTERN as _PATH_ARG_PATTERN

    def _is_path_arg_name(key: str) -> bool:
        return _PATH_ARG_PATTERN.match(key) is not None

    max_value_length = 40  # Max length for displayed values

    def _display_path_value(raw: str) -> str:
        out = convert_and_abbreviate_path(raw)
        if len(out) > max_value_length:
            return out[: max_value_length - 3] + "..."
        return out

    args = extract_tool_args_dict(tool_call)
    internal = _normalize_tool_name_for_arg_map(tool_name)
    key_args = _ARG_DISPLAY_MAP.get(internal)

    # Partial streaming JSON (``extract_tool_args_dict`` needs complete JSON)
    raw_args_str = tool_call.get("_raw") or tool_call.get("raw_args_str", "")

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
        return "…"

    if not key_args:
        if args:
            compact = _compact_tool_args_display_values(args, max_value_length=max_value_length)
            return compact if compact else "…"
        return "…"

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
            compact = _compact_tool_args_display_values(args, max_value_length=max_value_length)
            if compact:
                return compact
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
