"""Compact summaries for ``[tool_stream_diag]`` timing logs (daemon + TUI).

WebSocket payloads often use ``dict`` message shapes; in-process LangGraph chunks
use message objects. Both are summarized here so logs stay one line.
"""

from __future__ import annotations

from typing import Any


def summarize_messages_stream_payload(data: Any) -> str:
    """Return a one-line summary of a LangGraph ``messages`` pair payload."""
    if not isinstance(data, (list, tuple)) or len(data) < 1:
        return "messages(non-pair)"
    return _summarize_single_message(data[0])


def _summarize_single_message(msg: Any) -> str:
    if msg is None:
        return "null-msg"
    if isinstance(msg, dict):
        raw_type = str(msg.get("type", "") or "")
        if raw_type in ("tool", "ToolMessage") or raw_type.endswith("ToolMessage"):
            tc = str(msg.get("tool_call_id", "") or "").strip()
            name = str(msg.get("name", "") or "").strip()
            return f"ToolMessage name={name!r} tool_call_id={tc!r}"
        if raw_type in ("ai", "AIMessage", "AIMessageChunk") or raw_type.endswith("AIMessageChunk"):
            tcc = msg.get("tool_call_chunks") or []
            tcs = msg.get("tool_calls") or []
            if tcc or tcs:
                block = (tcc[0] if tcc else tcs[0]) if (tcc or tcs) else {}
                if isinstance(block, dict):
                    return (
                        "AI-tool "
                        f"id={str(block.get('id', '') or '')!r} "
                        f"name={str(block.get('name', '') or '')!r}"
                    )
            return f"AI type={raw_type!r}"
        return f"dict type={raw_type!r}"

    tid = getattr(msg, "tool_call_id", None)
    if tid is not None and str(tid).strip():
        name = str(getattr(msg, "name", "") or "").strip()
        return f"ToolMessage name={name!r} tool_call_id={str(tid)!r}"

    chunks = getattr(msg, "tool_call_chunks", None) or []
    tcs = getattr(msg, "tool_calls", None) or []
    if chunks or tcs:
        block = chunks[0] if chunks else tcs[0]
        if isinstance(block, dict):
            return (
                "AI-tool "
                f"id={str(block.get('id', '') or '')!r} "
                f"name={str(block.get('name', '') or '')!r}"
            )
    return type(msg).__name__


def is_tool_visible_messages_summary(summary: str) -> bool:
    """True when the summary likely corresponds to tool UI (vs plain assistant text)."""
    s = summary.lower()
    return "toolmessage" in s or "ai-tool" in s
