"""Translate Claude Agent SDK messages into LangChain message objects (IG-335).

The Claude Agent SDK streams `AssistantMessage`, `UserMessage`, `SystemMessage`,
and `ResultMessage` objects with `TextBlock`, `ToolUseBlock`, `ToolResultBlock`,
and `ThinkingBlock` content. The Soothe CLI/TUI clients render LangChain
`AIMessage` / `AIMessageChunk` / `ToolMessage` objects natively. This module
provides pure translation functions to bridge the two so Claude's internal
activity surfaces in the existing message-rendering pipeline.

All functions are side-effect free — emission via the LangGraph stream writer
lives in `relay.py`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage


def _new_message_id(prefix: str) -> str:
    """Generate a stable LangChain-style message id with a Claude prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def translate_text_chunk(message_id: str, text: str) -> AIMessageChunk:
    """Translate a streamed `TextBlock.text` slice into an `AIMessageChunk`.

    Args:
        message_id: Stable id shared across chunks of the same assistant turn.
        text: Text fragment from `TextBlock`.

    Returns:
        `AIMessageChunk` whose `content` carries the fragment so the existing
        streaming-text accumulator concatenates it correctly.
    """
    return AIMessageChunk(content=text, id=message_id)


def translate_assistant_text_final(message_id: str, text: str) -> AIMessage:
    """Translate the assembled assistant text into a finalizing `AIMessage`."""
    return AIMessage(content=text, id=message_id)


def translate_tool_use(message_id: str, block: Any) -> AIMessage:
    """Translate a Claude `ToolUseBlock` into an `AIMessage` with `tool_calls`.

    Args:
        message_id: Stable id for the parent assistant turn (one per turn).
        block: Claude SDK `ToolUseBlock` (id / name / input).

    Returns:
        `AIMessage` shaped like a LangChain provider tool-call message so
        `EventProcessor` can dedupe it by id and render it via
        `on_tool_call(name, args, tool_call_id)`.
    """
    tool_id = getattr(block, "id", "") or ""
    name = getattr(block, "name", "") or ""
    args = getattr(block, "input", None)
    if not isinstance(args, dict):
        args = {}
    return AIMessage(
        content="",
        id=message_id,
        tool_calls=[
            {
                "name": name,
                "args": dict(args),
                "id": tool_id,
                "type": "tool_call",
            }
        ],
    )


def translate_tool_result(block: Any, *, name_lookup: dict[str, str]) -> ToolMessage:
    """Translate a Claude `ToolResultBlock` into a `ToolMessage`.

    Args:
        block: Claude SDK `ToolResultBlock`.
        name_lookup: Mapping `tool_use_id -> tool_name` populated when the
            preceding `ToolUseBlock` is translated. Allows the `ToolMessage`
            to carry a tool name even though `ToolResultBlock` only has the id.

    Returns:
        `ToolMessage` with `tool_call_id`, `name`, `content`, and explicit
        `status`. CLI joins it to the prior tool-call line via the id.
    """
    tool_use_id = getattr(block, "tool_use_id", "") or ""
    raw_content = getattr(block, "content", None)
    is_error = bool(getattr(block, "is_error", False))
    name = name_lookup.get(tool_use_id, "tool")

    if raw_content is None:
        content_str = ""
    elif isinstance(raw_content, str):
        content_str = raw_content
    elif isinstance(raw_content, list):
        parts: list[str] = []
        for item in raw_content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        content_str = "\n".join(p for p in parts if p)
    else:
        content_str = str(raw_content)

    status = "error" if is_error else "success"
    return ToolMessage(
        content=content_str,
        tool_call_id=tool_use_id,
        name=name,
        status=status,
    )


def translate_thinking(message_id: str, block: Any) -> AIMessage:
    """Translate a Claude `ThinkingBlock` into an `AIMessage` with thinking blocks.

    The block uses LangChain's content-blocks shape `{type: "thinking", ...}`
    so renderers that opt in (DETAILED verbosity) can surface it. Standard
    rendering paths skip non-text blocks and stay quiet at NORMAL.
    """
    thinking = getattr(block, "thinking", "") or ""
    signature = getattr(block, "signature", "") or ""
    return AIMessage(
        content=[
            {
                "type": "thinking",
                "thinking": thinking,
                "signature": signature,
            }
        ],
        id=message_id,
    )


def translate_system(message: Any) -> dict[str, Any]:
    """Translate a Claude `SystemMessage` into a Soothe progress event dict.

    The shape `soothe.capability.claude.system.<subtype>` is classified as a
    capability event (DETAILED tier), so it stays out of normal-verbosity output
    while remaining available for telemetry and detailed traces.
    """
    subtype = str(getattr(message, "subtype", "") or "unknown")
    data = getattr(message, "data", None)
    payload: dict[str, Any] = {
        "type": f"soothe.capability.claude.system.{subtype}",
        "subtype": subtype,
    }
    if isinstance(data, dict):
        payload["data"] = data
    return payload


def translate_error(*, error: str, source: str = "assistant_message") -> dict[str, Any]:
    """Build a Soothe error custom-event for Claude assistant errors / rate limits.

    Args:
        error: Short error code or message (e.g. `rate_limit`, `server_error`).
        source: What produced the error (`assistant_message`, `rate_limit_event`).

    Returns:
        `{"type": "soothe.capability.claude.error", "error": ..., "source": ...}`.
        QUIET-tier classification (via the `soothe.error` domain prefix) ensures
        it is always visible regardless of verbosity.
    """
    return {
        "type": "soothe.capability.claude.error",
        "error": error,
        "source": source,
    }


@dataclass
class ClaudeToolCorrelator:
    """Track `ToolUseBlock.id -> tool_name` so `ToolResultBlock` can name its result.

    `ToolResultBlock` only carries `tool_use_id`; the human-readable tool name
    only appears on the earlier `ToolUseBlock`. This correlator is populated
    when a tool-use is translated and consulted when a tool-result arrives.
    """

    _id_to_name: dict[str, str] = field(default_factory=dict)

    def register(self, block: Any) -> None:
        """Record `tool_use_id -> tool_name` from a `ToolUseBlock`."""
        tool_id = getattr(block, "id", "") or ""
        name = getattr(block, "name", "") or ""
        if tool_id:
            self._id_to_name[tool_id] = name or "tool"

    def lookup(self, tool_use_id: str) -> str:
        """Return the recorded tool name for `tool_use_id` or ``"tool"``."""
        return self._id_to_name.get(tool_use_id, "tool")

    def as_lookup(self) -> dict[str, str]:
        """Expose the underlying mapping (read-only consumers may copy)."""
        return self._id_to_name


__all__ = [
    "ClaudeToolCorrelator",
    "translate_assistant_text_final",
    "translate_error",
    "translate_system",
    "translate_text_chunk",
    "translate_thinking",
    "translate_tool_result",
    "translate_tool_use",
]
