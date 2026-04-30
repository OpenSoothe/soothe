"""Whether to show or elide tool-call cards (IG-300).

Cards that have no meaningful arguments and no substantive tool output add
noise (e.g. parallel ``glob`` probes that return ``[]`` while the stream never
carried kwargs on the final assistant chunk).
"""

from __future__ import annotations

import json
import re
from typing import Any

from soothe_cli.shared.message_processing import _normalize_tool_name_for_arg_map
from soothe_cli.shared.tool_call_resolution import tool_args_meaningful

# Tools whose header is still useful when kwargs are omitted (workspace default).
_TOOLS_ALLOW_STREAM_MOUNT_WITHOUT_MEANINGFUL_ARGS: frozenset[str] = frozenset(
    {
        "ls",
        "list_files",
    }
)


def tool_allows_stream_mount_without_meaningful_args(tool_name: str) -> bool:
    """True when the model may omit kwargs yet the card still shows a useful header."""
    key = _normalize_tool_name_for_arg_map(tool_name or "")
    return key in _TOOLS_ALLOW_STREAM_MOUNT_WITHOUT_MEANINGFUL_ARGS


def tool_result_display_is_insubstantial(text: str) -> bool:
    """True when formatted tool output carries no user-visible information."""
    s = (text or "").strip()
    if not s:
        return True
    low = s.lower()
    if low in ("[]", "{}", "()", "null", "none"):
        return True
    # Strip common markdown fences before JSON parse
    stripped = re.sub(r"^```(?:json|text)?\s*", "", low, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped).strip()
    try:
        parsed: Any = json.loads(stripped)
    except (json.JSONDecodeError, TypeError, ValueError):
        return False
    if parsed == [] or parsed == {}:
        return True
    if isinstance(parsed, list) and len(parsed) == 0:
        return True
    if isinstance(parsed, dict) and len(parsed) == 0:
        return True
    return False


def should_elide_tool_card_no_info(
    *,
    tool_name: str,
    args: dict[str, Any] | None,
    formatted_output: str,
    is_error: bool,
) -> bool:
    """True when a tool card should not be shown (no args signal and no output signal).

    Errors are always shown. Tools with meaningful kwargs are always shown once
    completed (even if output is empty — the header still carries intent).
    """
    if is_error:
        return False
    if tool_args_meaningful(args):
        return False
    return tool_result_display_is_insubstantial(formatted_output)


def should_elide_stream_tool_card_mount(
    *,
    tool_name: str,
    args: dict[str, Any] | None,
    message_terminal_for_tool_args: bool,
) -> bool:
    """True when the TUI should not mount a card from an assistant stream chunk.

    Mid-stream empty args are handled separately via deferral; this applies when
    the assistant message will not carry further tool-arg updates for this call.
    """
    if not message_terminal_for_tool_args:
        return False
    if tool_args_meaningful(args):
        return False
    if tool_allows_stream_mount_without_meaningful_args(tool_name):
        return False
    return True


def should_elide_completed_tool_call_message(
    tool_msg: Any,
    formatted_output: str,
    *,
    is_error: bool,
) -> bool:
    """True when a mounted tool card should be removed after completion."""
    return should_elide_tool_card_no_info(
        tool_name=getattr(tool_msg, "_tool_name", "") or "",
        args=getattr(tool_msg, "_args", None),
        formatted_output=formatted_output,
        is_error=is_error,
    )


__all__ = [
    "should_elide_completed_tool_call_message",
    "should_elide_stream_tool_card_mount",
    "should_elide_tool_card_no_info",
    "tool_allows_stream_mount_without_meaningful_args",
    "tool_result_display_is_insubstantial",
]
