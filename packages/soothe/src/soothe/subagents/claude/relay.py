"""Relay translated LangChain messages to clients via the LangGraph stream (IG-335).

Subagent graph nodes can only write to LangGraph's `custom` stream channel
(`stream_mode="custom"`), not the `messages` channel. To surface Claude SDK
activity as if it had come from a chat-model stream, we emit a Soothe-protocol
custom event of type `soothe.relay.message` carrying a serialized LangChain
message dict. CLI/TUI clients short-circuit this event back into their
existing message-handling path, preserving namespace and tool-scope binding.

Wire shape::

    {
        "type": "soothe.relay.message",
        "message": <model_dump of AIMessage / AIMessageChunk / ToolMessage>,
        "metadata": {"lc_agent_name": "claude", ...},
    }

The relay payload itself is classified as INTERNAL verbosity so it never
renders as a generic progress line; only the inner LangChain message governs
on-screen output.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)


RELAY_EVENT_TYPE = "soothe.relay.message"


def _dump_message(msg: BaseMessage) -> dict[str, Any]:
    """Serialize a LangChain message to the same flat dict shape EventProcessor expects.

    `model_dump()` produces wire-compatible types (`"ai"`, `"AIMessageChunk"`,
    `"tool"`) recognized by both `EventProcessor._handle_dict_message` and the
    TUI textual adapter via `envelope_langchain_message_dict`.
    """
    return msg.model_dump()


def relay_message(msg: BaseMessage, *, metadata: dict[str, Any] | None = None) -> None:
    """Emit a translated LangChain message through the LangGraph custom stream.

    Args:
        msg: Translated `AIMessage` / `AIMessageChunk` / `ToolMessage`.
        metadata: Optional metadata dict (e.g. `lc_agent_name`, `langgraph_node`).
            Mirrors LangGraph's `(message, metadata)` tuple so client-side dedup
            and accumulator logic still has the same fields available.

    No-ops silently when no stream writer is attached (e.g. during tests).
    """
    try:
        from langgraph.config import get_stream_writer
    except ImportError:
        logger.debug("langgraph not available, skipping message relay")
        return

    try:
        writer = get_stream_writer()
    except (RuntimeError, KeyError):
        # Outside a running LangGraph node — relay is a no-op.
        return
    if writer is None:
        return

    try:
        wire = _dump_message(msg)
    except Exception:
        logger.debug("relay_message: model_dump failed", exc_info=True)
        return

    payload: dict[str, Any] = {
        "type": RELAY_EVENT_TYPE,
        "message": wire,
        "metadata": dict(metadata or {}),
    }
    try:
        writer(payload)
    except Exception:
        logger.debug("relay_message: writer raised", exc_info=True)


__all__ = ["RELAY_EVENT_TYPE", "relay_message"]
