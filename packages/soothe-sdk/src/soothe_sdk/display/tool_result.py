"""Extract tool result fields from LangChain stream messages.

Used by the TUI to update step-card tool state (stats only; no tool-row UI).

Error detection matches the headless runtime event-processor tool-result
handling (content heuristics) with explicit ``status`` override.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from soothe_sdk.display._text_utils import text_looks_like_error
from soothe_sdk.display.tool_message_format import (
    format_tool_message_content,
    run_python_envelope_indicates_failure,
    try_parse_run_python_result_envelope,
)
from soothe_sdk.ux.task_namespace import parse_unified_tool_call_id

# Markers shared with act-wave finalize (canonical home for client + core reuse).
_ERROR_TOOL_RESULT_MARKERS = (
    "timed out",
    "timeout after",
    "command timed out",
    "error:",
    "tool error",
)


def is_error_tool_result_text(text: str) -> bool:
    """Return True when tool output text is dominated by a failure message."""
    low = (text or "").strip().lower()
    if not low:
        return False
    return any(marker in low for marker in _ERROR_TOOL_RESULT_MARKERS)


def infer_tool_output_suggests_error(output_display: str, _tool_name: str = "") -> bool:
    """Return True if formatted tool output text looks like a failure (CLI parity).

    When ``output_display`` is JSON matching the ``run_python`` result contract (fixed
    key set including ``success`` / ``error``), success is determined from fields, not
    from substrings (so ``\"error\": null`` does not imply failure).

    Args:
        output_display: Flattened tool output string.
        _tool_name: Reserved for future per-tool heuristics alongside envelopes.
    """
    env = try_parse_run_python_result_envelope(output_display)
    if env is not None:
        return run_python_envelope_indicates_failure(env)

    if not output_display:
        return False
    return text_looks_like_error(output_display)


@dataclass(frozen=True, slots=True)
class ToolResultPayload:
    """Normalized tool result fields from a stream message."""

    tool_call_id: str
    tool_name: str
    output_display: str
    is_error: bool
    status_raw: str


def _tool_dict_from_any(message: Any) -> dict[str, Any] | None:
    """Normalize to a dict with tool fields, or None if not a tool result."""
    try:
        from langchain_core.messages import ToolMessage as LCToolMessage

        if isinstance(message, LCToolMessage):
            return {
                "type": "tool",
                "content": getattr(message, "content", ""),
                "tool_call_id": getattr(message, "tool_call_id", None) or "",
                "name": getattr(message, "name", None) or "",
                "status": getattr(message, "status", None),
            }
    except Exception:
        pass

    if isinstance(message, Mapping):
        m = dict(message)
        raw_type = m.get("type")
        if isinstance(raw_type, str) and raw_type in {"tool", "ToolMessage"}:
            return m
    return None


def extract_tool_result_payload(message: Any) -> ToolResultPayload | None:
    """Build :class:`ToolResultPayload` from a tool result stream value.

    Accepts:

    * A LangChain :class:`~langchain_core.messages.ToolMessage`
    * A serialized dict (``type`` of ``\"tool\"`` or ``\"ToolMessage\"``) after JSON transport

    Does **not** handle assistant tool-call requests; those stay on ``AIMessage`` /
    ``tool_call_chunks`` in the Textual adapter.

    Args:
        message: Stream message or dict after optional normalization.

    Returns:
        Parsed payload, or ``None`` if ``message`` is not a tool result.
    """
    data = _tool_dict_from_any(message)
    if data is None:
        return None

    tool_call_id = str(data.get("tool_call_id") or "").strip()
    tool_name = str(data.get("name") or "").strip()
    if tool_call_id and (not tool_name or tool_name == "tool"):
        # Extract tool name from the unified tool-call id format
        _, _, _, tool_info = parse_unified_tool_call_id(tool_call_id)
        if tool_info:
            head = tool_info.split(":")[0].split(".")[0].strip()
            if head and head != "tool":
                tool_name = head
    if not tool_name:
        tool_name = "tool"
    raw_status = data.get("status")
    if raw_status is None:
        status_raw = "success"
    else:
        status_raw = str(raw_status).strip() or "success"

    output_display = format_tool_message_content(data.get("content"))

    status_lower = status_raw.lower()
    if status_lower in {"error", "failed"}:
        is_error = True
    elif status_lower in {"success", "completed"}:
        is_error = False
    else:
        is_error = infer_tool_output_suggests_error(output_display, tool_name)

    return ToolResultPayload(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        output_display=output_display,
        is_error=is_error,
        status_raw=status_raw,
    )


__all__ = [
    "ToolResultPayload",
    "extract_tool_result_payload",
    "infer_tool_output_suggests_error",
    "is_error_tool_result_text",
]
