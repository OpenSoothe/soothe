"""Normalize LangChain message dicts for JSON wire transport.

Canonical serialization uses :func:`langchain_core.messages.message_to_dict` (enveloped)
then flattens to ``{type, content, tool_calls, …}`` with short wire type tags (``ai``,
``human``, …) for full messages and explicit ``*Chunk`` tags for streaming chunks.
Deserialization uses :func:`messages_from_wire_dicts`.

IMPORTANT: ``AIMessageChunk`` / ``HumanMessageChunk`` MUST keep their distinct wire
tags. Collapsing them to ``ai`` / ``human`` (the pre-IG-440 mapping) causes the TUI
to receive synthesis stream chunks as plain ``AIMessage`` instances, breaking the
streaming branch (``isinstance(message, AIMessageChunk)`` returns ``False``) and
silently dropping all chunks after the first. See IG-440.
"""

from __future__ import annotations

import json
from typing import Any

# ``messages_from_dict`` / ``_message_from_dict`` only accept short wire tags (``ai``,
# ``human``, ``tool``, …) or explicit ``*Chunk`` tags — not Pydantic class names like
# ``AIMessage``. Some serializers emit class names; normalize before enveloping.
#
# Chunk types (``AIMessageChunk`` / ``HumanMessageChunk``) intentionally pass through
# unchanged: ``messages_from_dict`` understands these tags natively, and preserving
# them on the wire keeps the chunk identity intact so streaming consumers (TUI
# synthesis branch, etc.) can use ``isinstance(msg, AIMessageChunk)``.
_LC_MESSAGE_CLASS_TO_WIRE: dict[str, str] = {
    "AIMessage": "ai",
    "HumanMessage": "human",
    "SystemMessage": "system",
    "ToolMessage": "tool",
    "FunctionMessage": "function",
    "ChatMessage": "chat",
    "RemoveMessage": "remove",
}


def envelope_langchain_message_dict(message: dict[str, Any]) -> dict[str, Any]:
    """Wrap flat ``model_dump``-style message dicts for ``messages_from_dict``.

    Args:
        message: Decoded JSON object for a single stream or state message.

    Returns:
        Either the original dict (already enveloped or not a message body) or the
        wrapped form suitable for ``messages_from_dict``.
    """
    if "data" in message:
        return message
    body = dict(message)
    raw_type = body.get("type")
    if isinstance(raw_type, str) and raw_type in _LC_MESSAGE_CLASS_TO_WIRE:
        body["type"] = _LC_MESSAGE_CLASS_TO_WIRE[raw_type]
    msg_type = body.get("type")
    if not isinstance(msg_type, str):
        return message
    if not any(k in body for k in ("content", "tool_calls", "tool_call_id", "tool_call_chunks")):
        return message
    return {"type": msg_type, "data": body}


def _stringify_tool_call_chunk_args_in_body(body: dict[str, Any]) -> bool:
    """Coerce ``tool_call_chunks[].args`` dicts to JSON strings for LangChain deserialize.

    ``AIMessageChunk`` validates chunk ``args`` as ``str`` (streaming JSON fragments).
    Executor backfill/enrich may attach complete dict kwargs; without this step
    ``messages_from_dict`` fails and the TUI never merges task descriptions.
    """
    chunks = body.get("tool_call_chunks")
    if not isinstance(chunks, list):
        return False
    changed = False
    new_chunks: list[Any] = []
    for tc in chunks:
        if not isinstance(tc, dict):
            new_chunks.append(tc)
            continue
        block = dict(tc)
        args = block.get("args")
        if isinstance(args, dict):
            block["args"] = json.dumps(args, separators=(",", ":"))
            changed = True
        new_chunks.append(block)
    if changed:
        body["tool_call_chunks"] = new_chunks
    return changed


def coerce_tool_call_chunk_args_for_wire(message: dict[str, Any]) -> dict[str, Any]:
    """Return a wire message dict safe for :func:`messages_from_dict`."""
    if "data" in message and isinstance(message.get("data"), dict):
        body = dict(message["data"])
        if _stringify_tool_call_chunk_args_in_body(body):
            out = dict(message)
            out["data"] = body
            return out
        return message
    if isinstance(message, dict):
        body = dict(message)
        if _stringify_tool_call_chunk_args_in_body(body):
            return body
    return message


def _backfill_tool_calls_on_wire_body(body: dict[str, Any]) -> dict[str, Any]:
    """Copy complete chunk kwargs onto empty ``tool_calls[].args`` in a wire dict."""
    chunks = body.get("tool_call_chunks")
    calls = body.get("tool_calls")
    if not isinstance(chunks, list) or not isinstance(calls, list):
        return body
    args_by_id: dict[str, dict[str, Any]] = {}
    args_by_index: dict[int, dict[str, Any]] = {}
    for tc in chunks:
        if not isinstance(tc, dict):
            continue
        raw = tc.get("args")
        parsed: dict[str, Any] = {}
        if isinstance(raw, dict) and raw:
            parsed = dict(raw)
        elif isinstance(raw, str) and raw.strip():
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    parsed = loaded
            except json.JSONDecodeError:
                parsed = {}
        if not parsed:
            continue
        tid = str(tc.get("id") or "").strip()
        if tid:
            args_by_id[tid] = parsed
        idx_raw = tc.get("index")
        if idx_raw is not None:
            try:
                args_by_index[int(idx_raw)] = parsed
            except (TypeError, ValueError):
                pass
    if not args_by_id and not args_by_index:
        return body
    new_calls: list[Any] = []
    changed = False
    for call_idx, tc in enumerate(calls):
        if not isinstance(tc, dict):
            new_calls.append(tc)
            continue
        tid = str(tc.get("id") or "").strip()
        existing = tc.get("args")
        empty = existing is None or existing == {} or existing == ""
        fill: dict[str, Any] | None = None
        if empty and tid and tid in args_by_id:
            fill = args_by_id[tid]
        elif empty and call_idx in args_by_index:
            fill = args_by_index[call_idx]
        if fill is not None:
            patched = dict(tc)
            patched["args"] = fill
            new_calls.append(patched)
            changed = True
        else:
            new_calls.append(tc)
    if not changed:
        return body
    out = dict(body)
    out["tool_calls"] = new_calls
    return out


def _wire_type_tag(raw_type: Any) -> Any:
    if isinstance(raw_type, str):
        return _LC_MESSAGE_CLASS_TO_WIRE.get(raw_type, raw_type)
    return raw_type


def flatten_enveloped_message_dict(message: dict[str, Any]) -> dict[str, Any]:
    """Flatten ``{type, data: body}`` to ``{type, …body fields}`` for JSON wire."""
    if "data" in message and isinstance(message.get("data"), dict):
        body = dict(message["data"])
        body.pop("type", None)
        wire_type = _wire_type_tag(message.get("type"))
        body = coerce_tool_call_chunk_args_for_wire(body)
        body = _backfill_tool_calls_on_wire_body(body)
        if isinstance(wire_type, str):
            return {"type": wire_type, **body}
        return body
    if isinstance(message, dict):
        body = dict(message)
        if "type" in body:
            body["type"] = _wire_type_tag(body["type"])
        body = coerce_tool_call_chunk_args_for_wire(body)
        return _backfill_tool_calls_on_wire_body(body)
    return message


def serialize_langchain_message_for_wire(message: Any) -> dict[str, Any]:
    """Canonical JSON-ready dict for one LangChain message (RFC-450 wire)."""
    if isinstance(message, dict):
        return flatten_enveloped_message_dict(message)
    try:
        from langchain_core.messages import BaseMessage, message_to_dict
    except ImportError:
        from soothe_sdk.client.protocol import _serialize_for_json

        flat = _serialize_for_json(message)
        return flatten_enveloped_message_dict(flat) if isinstance(flat, dict) else {}
    if isinstance(message, BaseMessage):
        return flatten_enveloped_message_dict(message_to_dict(message))
    from soothe_sdk.client.protocol import _serialize_for_json

    flat = _serialize_for_json(message)
    return flatten_enveloped_message_dict(flat) if isinstance(flat, dict) else {}


def deserialize_langchain_message_from_wire(message: Any) -> Any:
    """Restore a LangChain message from a wire dict (flat or enveloped)."""
    if not isinstance(message, dict):
        return message
    restored = messages_from_wire_dicts([message])
    if restored:
        return restored[0]
    return message


def prepare_stream_message_for_wire(message: Any) -> Any:
    """Serialize a LangChain stream message for WebSocket/JSON clients."""
    return serialize_langchain_message_for_wire(message)


def prepare_stream_data_for_wire(data: Any) -> Any:
    """Serialize a LangGraph ``messages`` stream pair ``(message, metadata)``."""
    if not isinstance(data, (list, tuple)) or len(data) != 2:
        return data
    msg, meta = data[0], data[1]
    from soothe_sdk.client.protocol import _serialize_for_json

    out_meta = _serialize_for_json(meta) if meta is not None else {}
    return (prepare_stream_message_for_wire(msg), out_meta)


def messages_from_wire_dicts(messages: list[Any]) -> list[Any]:
    """Deserialize LangChain messages from daemon/JSON list payloads.

    Args:
        messages: List of dicts (flat or enveloped) as received over the wire.

    Returns:
        List of :class:`~langchain_core.messages.BaseMessage` instances.
    """
    from langchain_core.messages import messages_from_dict

    prepared: list[Any] = []
    for m in messages:
        if isinstance(m, dict):
            m = coerce_tool_call_chunk_args_for_wire(m)
            m = envelope_langchain_message_dict(m)
        prepared.append(m)
    return messages_from_dict(prepared)


__all__ = [
    "coerce_tool_call_chunk_args_for_wire",
    "deserialize_langchain_message_from_wire",
    "envelope_langchain_message_dict",
    "flatten_enveloped_message_dict",
    "messages_from_wire_dicts",
    "prepare_stream_data_for_wire",
    "prepare_stream_message_for_wire",
    "serialize_langchain_message_for_wire",
]
