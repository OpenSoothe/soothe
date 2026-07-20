"""Normalize LangGraph ``astream`` chunks for CoreAgent stream aggregation.

``CompiledStateGraph.astream`` can emit 3-tuples ``(namespace, mode, data)``,
2-tuples ``(mode, data)``, dict updates with ``{"model": {"messages": [...]}}``,
or list-shaped ``data`` ``[message, metadata]``.

This module provides a single place to extract :class:`~langchain_core.messages.BaseMessage`
instances and plain text from message ``content`` fields.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from langchain_core.messages import BaseMessage, ToolMessage

_TUPLE_LEN = 3
_MSG_TUPLE_LEN = 2
_LIST_MIN_LEN = 2


def join_text_fragments(parts: list[str]) -> str:
    """Join text fragments with newline separators between content blocks."""
    return "\n".join(parts) if parts else ""


def extract_text_from_message_content(content: Any) -> str:
    """Flatten LangChain message ``content`` (str or block list) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
        return join_text_fragments(parts)
    return ""


def parse_tuple_stream_chunk(chunk: Any) -> tuple[Any, str, Any] | None:
    """Parse stream tuple into ``(namespace, mode, data)`` if applicable."""
    if not isinstance(chunk, tuple):
        return None
    if len(chunk) == _TUPLE_LEN:
        return chunk[0], chunk[1], chunk[2]
    if len(chunk) >= _MSG_TUPLE_LEN:
        return (), chunk[0], chunk[1]
    return None


def _iter_messages_from_messages_data(data: Any) -> Iterator[BaseMessage]:
    """Yield ``BaseMessage`` instances from ``messages`` mode payload."""
    if isinstance(data, tuple) and len(data) >= _MSG_TUPLE_LEN:
        head = data[0]
        if isinstance(head, BaseMessage):
            yield head
    elif isinstance(data, list) and len(data) >= _LIST_MIN_LEN:
        head = data[0]
        if isinstance(head, BaseMessage):
            yield head


def _walk_stream_messages_payload_for_base_messages(obj: Any) -> Iterator[BaseMessage]:
    """DFS over LangGraph ``messages`` payloads that may nest lists/tuples/dicts."""
    if isinstance(obj, BaseMessage):
        yield obj
        return
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_stream_messages_payload_for_base_messages(v)
        return
    if isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _walk_stream_messages_payload_for_base_messages(item)


def iter_namespaced_tool_messages(chunk: Any) -> Iterator[tuple[tuple[str, ...], ToolMessage]]:
    """Yield ``(namespace, ToolMessage)`` from subgraph ``messages`` stream chunks."""
    parsed = parse_tuple_stream_chunk(chunk)
    if parsed is None:
        return
    namespace, mode, data = parsed
    if mode != "messages" or not namespace:
        return
    ns_tuple = tuple(str(x) for x in namespace)
    for msg in _walk_stream_messages_payload_for_base_messages(data):
        if isinstance(msg, ToolMessage):
            yield (ns_tuple, msg)


def iter_messages_for_delegate_task_scan(chunk: Any) -> Iterator[ToolMessage]:
    """Yield ``task`` tool messages from namespaced ``messages`` stream chunks only."""
    parsed = parse_tuple_stream_chunk(chunk)
    if parsed is None:
        return
    namespace, mode, data = parsed
    if mode != "messages" or not namespace:
        return
    for msg in _walk_stream_messages_payload_for_base_messages(data):
        if isinstance(msg, ToolMessage) and getattr(msg, "name", "") == "task":
            yield msg


def iter_messages_for_act_aggregation(chunk: Any) -> Iterator[BaseMessage]:
    """Yield messages from one ``astream`` chunk for Act-phase aggregation."""
    parsed = parse_tuple_stream_chunk(chunk)
    if parsed is not None:
        namespace, mode, data = parsed
        if mode == "messages" and not namespace:
            yield from _iter_messages_from_messages_data(data)
        return

    if isinstance(chunk, dict) and "model" in chunk:
        model_data = chunk["model"]
        if isinstance(model_data, dict) and "messages" in model_data:
            for msg in model_data["messages"]:
                if isinstance(msg, BaseMessage):
                    yield msg


__all__ = [
    "extract_text_from_message_content",
    "iter_messages_for_act_aggregation",
    "iter_messages_for_delegate_task_scan",
    "iter_namespaced_tool_messages",
    "join_text_fragments",
    "parse_tuple_stream_chunk",
]
