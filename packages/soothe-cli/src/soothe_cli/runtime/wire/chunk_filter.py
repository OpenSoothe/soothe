"""Early filters for daemon stream chunks before the turn pipeline."""

from __future__ import annotations

from typing import Any

from soothe_cli.runtime.wire.message_text import (
    extract_plain_text_from_stream_message,
    wire_message_body,
)

_STREAM_CHUNK_LEN = 3
_MSG_PAIR_LEN = 2


def updates_chunk_is_noop(data: Any) -> bool:
    """True when an ``updates`` chunk carries no LangGraph interrupt."""
    if not isinstance(data, dict):
        return True
    return "__interrupt__" not in data


def _dict_block_is_tool_invocation(block: dict[str, Any]) -> bool:
    t = block.get("type")
    if t in ("tool_call", "tool_call_chunk", "tool_use"):
        return True
    if t == "non_standard" and isinstance(block.get("value"), dict):
        inner_t = block["value"].get("type")
        return inner_t in ("tool_use", "tool_call", "tool_call_chunk")
    return False


def message_has_tool_invocation_metadata(msg: Any) -> bool:
    """True when message carries tool_calls or tool_call_chunks."""
    from langchain_core.messages import AIMessage, AIMessageChunk

    if isinstance(msg, (AIMessage, AIMessageChunk)):
        tc = getattr(msg, "tool_calls", None)
        if isinstance(tc, list) and tc:
            return True
        tcc = getattr(msg, "tool_call_chunks", None)
        if isinstance(tcc, list) and tcc:
            return True
        for field in ("content_blocks", "content"):
            raw = getattr(msg, field, None)
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict) and _dict_block_is_tool_invocation(item):
                        return True
        return False
    if isinstance(msg, dict):
        body = wire_message_body(msg)
        if body.get("tool_calls") or body.get("tool_call_chunks"):
            return True
        for key in ("content", "content_blocks"):
            raw = body.get(key)
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict) and _dict_block_is_tool_invocation(item):
                        return True
    return False


def message_chunk_is_non_actionable(data: Any) -> bool:
    """True when a ``messages`` pair has no tool, text, or loop phase payload."""
    if not isinstance(data, (list, tuple)) or len(data) != _MSG_PAIR_LEN:
        return False
    msg = data[0]
    if msg is None:
        return True

    from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

    if isinstance(msg, ToolMessage):
        return False
    if isinstance(msg, dict):
        body = wire_message_body(msg)
        raw = str(body.get("type") or msg.get("type") or "")
        if raw in ("tool", "ToolMessage") or raw.endswith("ToolMessage"):
            return False
        if message_has_tool_invocation_metadata(msg):
            return False
        if body.get("phase"):
            return False
        return not extract_plain_text_from_stream_message(msg).strip()

    if isinstance(msg, (AIMessage, AIMessageChunk)):
        if message_has_tool_invocation_metadata(msg):
            return False
        if getattr(msg, "phase", None):
            return False
        return not extract_plain_text_from_stream_message(msg).strip()

    return False


def should_drop_stream_chunk_early(namespace: tuple[Any, ...], mode: str, data: Any) -> bool:
    """Return True when the chunk can be skipped before the turn pipeline."""
    if mode == "updates":
        return updates_chunk_is_noop(data)
    if mode == "messages":
        return message_chunk_is_non_actionable(data)
    return False


__all__ = [
    "message_chunk_is_non_actionable",
    "message_has_tool_invocation_metadata",
    "should_drop_stream_chunk_early",
    "updates_chunk_is_noop",
]
