"""Channel event types."""

from __future__ import annotations

from typing import Any

from pydantic import Field
from soothe_sdk.core.events import OutputEvent, ProtocolEvent

from soothe_daemon.events.constants import (
    CHANNEL_MESSAGE_RECEIVED,
    OUTPUT_PROGRESS,
    OUTPUT_REASONING,
    OUTPUT_TEXT_COMPLETE,
    OUTPUT_TEXT_DELTA,
    OUTPUT_TEXT_END,
    OUTPUT_UI_RENDER,
)


class ChannelMessageReceived(ProtocolEvent):
    """User message received from any channel."""

    type: str = CHANNEL_MESSAGE_RECEIVED
    channel: str
    chat_id: str
    sender_id: str
    content: str
    media: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def session_key(self) -> str:
        """Unique key for session identification."""
        return f"{self.channel}:{self.chat_id}"


class TextEvent(OutputEvent):
    """Complete text output for user display."""

    type: str = OUTPUT_TEXT_COMPLETE
    content: str


class TextDeltaEvent(OutputEvent):
    """Incremental text chunk for streaming."""

    type: str = OUTPUT_TEXT_DELTA
    content: str
    stream_id: str


class TextEndEvent(OutputEvent):
    """End of text stream marker."""

    type: str = OUTPUT_TEXT_END
    stream_id: str


class AgentUIEvent(OutputEvent):
    """Structured UI payload for rich clients.

    Carries JSON-serializable UI specification for clients that support
    structured rendering (WebSocket, WebUI). Other channels may ignore
    or render as fallback text.

    Attributes:
    payload: JSON-serializable UI specification.
    """

    type: str = OUTPUT_UI_RENDER
    payload: dict[str, Any]


class ProgressEvent(OutputEvent):
    """Progress indicator for user display.

    Shows agent activity progress (tool execution, subagent work, etc.).
    May be filtered by channel settings (send_progress flag).

    Attributes:
    message: Progress message text.
    tool_name: Optional tool name being executed.
    """

    type: str = OUTPUT_PROGRESS
    message: str
    tool_name: str | None = None


class ReasoningEvent(OutputEvent):
    """Model reasoning/thinking content.

    Represents model reasoning content (e.g., DeepSeek-R1 reasoning_content).
    Channels with low-emphasis UI affordances may render this distinctly.

    Attributes:
    content: Reasoning text.
    stream_id: Optional stream identifier for streaming reasoning.
    """

    type: str = OUTPUT_REASONING
    content: str
    stream_id: str | None = None


__all__ = [
    "AgentUIEvent",
    "ChannelMessageReceived",
    "ProgressEvent",
    "ReasoningEvent",
    "TextDeltaEvent",
    "TextEndEvent",
    "TextEvent",
]
