"""Shared decoder for ``soothe.relay.message`` custom events (IG-335).

Subagent graph nodes cannot write to LangGraph's ``messages`` stream channel
directly, so they emit translated LangChain messages on the ``custom`` channel
under the event type ``soothe.relay.message``. Both the no-tui ``EventProcessor``
and the Textual adapter intercept this event type and route the payload back
through their existing ``messages``-mode handling. This module centralizes the
parsing so both consumers stay consistent.
"""

from __future__ import annotations

from typing import Any

RELAY_EVENT_TYPE = "soothe.relay.message"


def is_relay_event(data: Any) -> bool:
    """True when ``data`` is a relayed-message custom event payload."""
    return isinstance(data, dict) and data.get("type") == RELAY_EVENT_TYPE


def extract_relay_payload(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Decode a relay event into ``(message_dict, metadata_dict)``.

    Args:
        data: Custom-event payload guaranteed to be a relay event (see
            :func:`is_relay_event`).

    Returns:
        ``(message, metadata)`` where ``message`` is a flat LangChain wire
        dict (e.g. ``{"type": "ai", "content": ..., ...}``) and ``metadata``
        is the optional metadata dict. Returns ``None`` when the message
        field is missing or malformed so callers can drop the event safely.
    """
    msg = data.get("message")
    if not isinstance(msg, dict) or not msg:
        return None
    metadata_raw = data.get("metadata")
    metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
    return msg, metadata


__all__ = ["RELAY_EVENT_TYPE", "extract_relay_payload", "is_relay_event"]
