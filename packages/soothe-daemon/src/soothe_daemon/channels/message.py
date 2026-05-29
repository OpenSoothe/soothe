"""Channel message types (RFC-620 §2.1).

ChannelMessage handles platform routing and delivery, separate from
agent-centric SootheEvent types. Translation occurs at ChannelManager boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChannelMessage:
    """Message for channel routing and platform delivery.

    This is the channel-layer message type, distinct from agent-layer
    SootheEvent. ChannelManager translates between the two layers.

    Attributes:
        channel: Target channel name (e.g., "websocket", "telegram").
        chat_id: Conversation/thread identifier on the platform.
        content: Text content (markdown formatted).
        media: Attachments (file paths or URLs).
        buttons: Interactive button rows (each row is a list of button labels).
        metadata: Channel-specific flags and routing hints.

    Metadata keys:
        _progress: Progress indicator message (not final output).
        _tool_hint: Tool execution hint message.
        _stream_delta: Streaming text chunk (not complete).
        _stream_end: End of stream marker.
        _stream_id: Unique stream identifier for stateful streaming.
        _reasoning: Complete reasoning block (one-shot).
        _reasoning_delta: Streaming reasoning chunk.
        _reasoning_end: End of reasoning stream.
        _wants_stream: Inbound hint that sender wants streaming responses.
    """

    channel: str
    chat_id: str
    content: str
    media: list[str] = field(default_factory=list)
    buttons: list[list[str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    reply_to: str | None = None

    def is_stream_delta(self) -> bool:
        """Check if this is a streaming delta chunk."""
        return bool(self.metadata.get("_stream_delta"))

    def is_stream_end(self) -> bool:
        """Check if this ends a stream."""
        return bool(self.metadata.get("_stream_end"))

    def is_progress(self) -> bool:
        """Check if this is a progress indicator."""
        return bool(self.metadata.get("_progress"))

    def is_tool_hint(self) -> bool:
        """Check if this is a tool execution hint."""
        return bool(self.metadata.get("_tool_hint"))

    def is_reasoning(self) -> bool:
        """Check if this is reasoning content."""
        return bool(
            self.metadata.get("_reasoning")
            or self.metadata.get("_reasoning_delta")
            or self.metadata.get("_reasoning_end")
        )

    def get_stream_id(self) -> str | None:
        """Get stream identifier for stateful streaming."""
        return self.metadata.get("_stream_id")


# Metadata key constants (for channel-agnostic UI payloads)
OUTBOUND_META_AGENT_UI = "_agent_ui"

# Internal metadata keys
META_STREAM_DELTA = "_stream_delta"
META_STREAM_END = "_stream_end"
META_STREAM_ID = "_stream_id"
META_STREAMED = "_streamed"
META_PROGRESS = "_progress"
META_TOOL_HINT = "_tool_hint"
META_REASONING = "_reasoning"
META_REASONING_DELTA = "_reasoning_delta"
META_REASONING_END = "_reasoning_end"
META_WANTS_STREAM = "_wants_stream"
