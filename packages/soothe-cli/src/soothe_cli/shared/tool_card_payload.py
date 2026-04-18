"""Unified extraction of tool-card update data from LangChain stream messages.

The TUI uses this to turn ``ToolMessage`` instances (or serialized wire dicts) into
display-ready fields for ``ToolCallMessage`` lifecycle updates.

Error detection matches :class:`soothe_cli.shared.event_processor.EventProcessor`
tool-result handling (content heuristics) with explicit ``status`` override.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from soothe_cli.shared.tool_message_format import format_tool_message_content


def infer_tool_output_suggests_error(output_display: str) -> bool:
    """Return True if formatted tool output text looks like a failure (CLI parity)."""
    if not output_display:
        return False
    lowered = output_display.lower()
    return any(indicator in lowered for indicator in ("error", "failed", "exception", "traceback"))


@dataclass(frozen=True, slots=True)
class ToolResultCardPayload:
    """Fields needed to update a tool card after a tool has returned."""

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


def extract_tool_result_card_payload(message: Any) -> ToolResultCardPayload | None:
    """Build :class:`ToolResultCardPayload` from a tool result stream value.

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
    tool_name = str(data.get("name") or "tool").strip() or "tool"
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
        is_error = infer_tool_output_suggests_error(output_display)

    return ToolResultCardPayload(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        output_display=output_display,
        is_error=is_error,
        status_raw=status_raw,
    )


__all__ = [
    "ToolResultCardPayload",
    "extract_tool_result_card_payload",
    "infer_tool_output_suggests_error",
]
