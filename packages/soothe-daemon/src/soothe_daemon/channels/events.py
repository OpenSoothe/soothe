"""Channel event types (RFC-620 §2.2).

Agent-layer events for channel messages. These SootheEvent subclasses
represent user input (ChannelMessageReceived) and agent output (TextEvent,
TextDeltaEvent, TextEndEvent). Translation to/from ChannelMessage occurs
at ChannelManager boundary.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field
from soothe_sdk.core.events import OutputEvent, ProtocolEvent


class ChannelMessageReceived(ProtocolEvent):
    """User message received from any channel.

    This event represents inbound user input, routed to the agent via
    EventBus topic `loop:{loop_id}`. The agent processes this as the
    primary user message for a turn.

    Attributes:
        channel: Source channel name (e.g., "websocket", "telegram").
        chat_id: Conversation identifier on the platform.
        sender_id: User identifier on the platform.
        content: Message text.
        media: Attachments (file paths or URLs).
        metadata: Channel-specific extras (e.g., platform features).
    """

    type: str = "soothe.channel.message.received"
    channel: str
    chat_id: str
    sender_id: str
    content: str
    media: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def session_key(self) -> str:
        """Unique key for session identification.

        Format: `{channel}:{chat_id}` matches loop_id for external channels.
        """
        return f"{self.channel}:{self.chat_id}"


class TextEvent(OutputEvent):
    """Complete text output for user display.

    Represents a complete (non-streaming) text response from the agent.
    ChannelManager translates this to ChannelMessage for delivery.

    Attributes:
        content: Complete text content (markdown formatted).
    """

    type: str = "soothe.output.text.complete"
    content: str


class TextDeltaEvent(OutputEvent):
    """Incremental text chunk for streaming.

    Represents a partial text chunk during streaming output. ChannelManager
    may coalesce consecutive deltas before dispatching to channel.

    Attributes:
        content: Text chunk.
        stream_id: Unique identifier for this stream (for stateful channels).
    """

    type: str = "soothe.output.text.delta"
    content: str
    stream_id: str


class TextEndEvent(OutputEvent):
    """End of text stream marker.

    Signals the end of a streaming text response. ChannelManager flushes
    any buffered deltas and sends final message.

    Attributes:
        stream_id: Unique identifier matching the TextDeltaEvent stream.
    """

    type: str = "soothe.output.text.end"
    stream_id: str


class AgentUIEvent(OutputEvent):
    """Structured UI payload for rich clients.

    Carries JSON-serializable UI specification for clients that support
    structured rendering (WebSocket, WebUI). Other channels may ignore
    or render as fallback text.

    Attributes:
        payload: JSON-serializable UI specification.
    """

    type: str = "soothe.output.ui.render"
    payload: dict[str, Any]


class ProgressEvent(OutputEvent):
    """Progress indicator for user display.

    Shows agent activity progress (tool execution, subagent work, etc.).
    May be filtered by channel settings (send_progress flag).

    Attributes:
        message: Progress message text.
        tool_name: Optional tool name being executed.
    """

    type: str = "soothe.output.progress"
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

    type: str = "soothe.output.reasoning"
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
