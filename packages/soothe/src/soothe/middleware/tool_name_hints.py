"""Hint helpers for invalid or hallucinated tool names."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.types import Command

INVALID_TOOL_ERROR_MARKER = "is not a valid tool"

# Shell-style names models invent instead of run_command.
_SHELL_TOOL_ALIASES: frozenset[str] = frozenset(
    {
        "read_command",
        "execute_command",
        "shell",
        "bash",
        "cmd",
        "exec",
        "run_shell",
        "terminal",
    }
)

# File-read aliases.
_READ_FILE_ALIASES: frozenset[str] = frozenset({"cat", "view_file", "view", "show_file"})

# Search aliases.
_GREP_ALIASES: frozenset[str] = frozenset({"search", "search_text", "find_text"})
_GLOB_ALIASES: frozenset[str] = frozenset({"find", "search_files", "find_files"})

# Tool names that may embed an operand in the name field (model formatting drift).
_OPERAND_IN_NAME_RE = re.compile(
    r"^(?P<base>ls|read_file|glob|grep|run_command)\s+(?P<operand>.+)$",
    re.IGNORECASE,
)

_ARG_VALUE_ARTIFACT_RE = re.compile(r"</arg_value>\s*$", re.IGNORECASE)


def is_invalid_tool_error(content: str) -> bool:
    """Return whether *content* is LangGraph's unregistered-tool error."""
    return INVALID_TOOL_ERROR_MARKER in content


def _coerce_args(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return args
    return {}


def sanitize_hallucinated_tool_name(tool_name: str) -> tuple[str, dict[str, Any]]:
    """Normalize tool names that embed paths or XML artifacts in the name field."""
    raw = (tool_name or "").strip()
    if not raw:
        return raw, {}

    cleaned = _ARG_VALUE_ARTIFACT_RE.sub("", raw).strip()
    match = _OPERAND_IN_NAME_RE.match(cleaned)
    if not match:
        return cleaned, {}

    base = match.group("base").lower()
    operand = match.group("operand").strip().strip("'\"")
    if base == "ls":
        return "ls", {"path": operand}
    if base == "read_file":
        return "read_file", {"file_path": operand}
    if base == "glob":
        return "glob", {"pattern": operand}
    if base == "grep":
        return "grep", {"pattern": operand}
    if base == "run_command":
        return "run_command", {"command": operand}
    return base, {}


def suggest_invalid_tool_hint(tool_name: str, args: Any) -> str | None:
    """Return an actionable hint for a hallucinated tool name, if recognized."""
    normalized_name, embedded_args = sanitize_hallucinated_tool_name(tool_name)
    merged_args = {**embedded_args, **_coerce_args(args)}
    lower = normalized_name.lower()

    if lower in _SHELL_TOOL_ALIASES or (
        lower == "read_command" and merged_args.get("command") is not None
    ):
        if merged_args.get("command") is not None:
            return "Hint: use run_command with the same command argument for shell output."
        return "Hint: use run_command for shell commands, or grep to search file contents."

    if lower in _READ_FILE_ALIASES:
        return "Hint: use read_file with file_path (not read_command or cat)."

    if lower in _GREP_ALIASES:
        return "Hint: use grep with pattern (and optional path/glob) to search file contents."

    if lower in _GLOB_ALIASES:
        return "Hint: use glob with a path pattern to find files."

    if embedded_args:
        if lower == "ls":
            return (
                "Hint: use ls with path in args, not in the tool name "
                f"(e.g. path={embedded_args.get('path')!r})."
            )
        if lower == "read_file":
            return (
                "Hint: use read_file with file_path in args, not in the tool name "
                f"(e.g. file_path={embedded_args.get('file_path')!r})."
            )
        if lower == "run_command":
            return "Hint: use run_command with command in args, not in the tool name."

    return None


def extract_tool_message_content(result: ToolMessage | Command[Any]) -> str | None:
    """Return ToolMessage text from a middleware tool-call result."""
    if isinstance(result, ToolMessage):
        return str(result.content or "")
    if isinstance(result, Command):
        update = result.update
        if not isinstance(update, dict):
            return None
        messages = update.get("messages")
        if not isinstance(messages, list):
            return None
        for msg in messages:
            if isinstance(msg, ToolMessage):
                return str(msg.content or "")
    return None


def append_hint_to_tool_result(
    result: ToolMessage | Command[Any],
    *,
    hint: str,
) -> ToolMessage | Command[Any]:
    """Append *hint* to invalid-tool error content on *result*."""
    if isinstance(result, ToolMessage):
        content = str(result.content or "")
        if hint not in content:
            return ToolMessage(
                content=f"{content.rstrip()}\n\n{hint}",
                tool_call_id=result.tool_call_id,
                name=result.name,
                status=result.status,
            )
        return result

    if isinstance(result, Command):
        update = result.update
        if not isinstance(update, dict):
            return result
        messages = update.get("messages")
        if not isinstance(messages, list):
            return result
        new_messages: list[Any] = []
        changed = False
        for msg in messages:
            if isinstance(msg, ToolMessage):
                content = str(msg.content or "")
                if hint not in content:
                    msg = ToolMessage(
                        content=f"{content.rstrip()}\n\n{hint}",
                        tool_call_id=msg.tool_call_id,
                        name=msg.name,
                        status=msg.status,
                    )
                    changed = True
            new_messages.append(msg)
        if changed:
            return Command(update={**update, "messages": new_messages})
    return result
