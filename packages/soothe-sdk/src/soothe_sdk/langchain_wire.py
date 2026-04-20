"""Normalize LangChain message dicts for JSON wire transport.

``model_dump()`` / :func:`soothe_sdk.client.protocol._serialize_for_json` produce flat
dicts like ``{"type": "human", "content": ...}``. :func:`langchain_core.messages.messages_from_dict`
expects ``{"type": "...", "data": {...}}`` (from :func:`message_to_dict`). This module
bridges the two shapes for daemon and client code paths.
"""

from __future__ import annotations

from typing import Any

# ``messages_from_dict`` / ``_message_from_dict`` only accept short wire tags (``ai``,
# ``human``, ``tool``, …) or explicit ``*Chunk`` tags — not Pydantic class names like
# ``AIMessage``. Some serializers emit class names; normalize before enveloping.
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


def messages_from_wire_dicts(messages: list[Any]) -> list[Any]:
    """Deserialize LangChain messages from daemon/JSON list payloads.

    Args:
        messages: List of dicts (flat or enveloped) as received over the wire.

    Returns:
        List of :class:`~langchain_core.messages.BaseMessage` instances.
    """
    from langchain_core.messages import messages_from_dict

    enveloped = [envelope_langchain_message_dict(m) if isinstance(m, dict) else m for m in messages]
    return messages_from_dict(enveloped)


__all__ = ["envelope_langchain_message_dict", "messages_from_wire_dicts"]
