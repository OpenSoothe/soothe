"""Unit tests for Channel events (RFC-620 §2.2)."""

from __future__ import annotations

import pytest

from soothe_daemon.channels.events import (
    AgentUIEvent,
    ChannelMessageReceived,
    ProgressEvent,
    ReasoningEvent,
    TextDeltaEvent,
    TextEndEvent,
    TextEvent,
)


class TestChannelMessageReceived:
    """Tests for ChannelMessageReceived event."""

    def test_basic_event(self):
        """Test basic event creation."""
        event = ChannelMessageReceived(
            channel="telegram",
            chat_id="chat123",
            sender_id="user456",
            content="Hello world",
        )

        assert event.type == "soothe.channel.message.received"
        assert event.channel == "telegram"
        assert event.chat_id == "chat123"
        assert event.sender_id == "user456"
        assert event.content == "Hello world"
        assert event.media == []
        assert event.metadata == {}

    def test_event_with_all_fields(self):
        """Test event with all fields populated."""
        event = ChannelMessageReceived(
            channel="discord",
            chat_id="thread789",
            sender_id="user123",
            content="Check this image",
            media=["https://example.com/image.png"],
            metadata={"platform_message_id": "msg999", "reply_to": "msg888"},
        )

        assert event.channel == "discord"
        assert event.media == ["https://example.com/image.png"]
        assert event.metadata["platform_message_id"] == "msg999"

    def test_session_key_format(self):
        """Test session_key property format."""
        event = ChannelMessageReceived(
            channel="telegram",
            chat_id="chat123",
            sender_id="user456",
            content="Hello",
        )

        assert event.session_key == "telegram:chat123"

    def test_to_dict_serialization(self):
        """Test event serialization to dict."""
        event = ChannelMessageReceived(
            channel="websocket",
            chat_id="loop-abc",
            sender_id="client-xyz",
            content="Test message",
        )

        data = event.to_dict()

        assert data["type"] == "soothe.channel.message.received"
        assert data["channel"] == "websocket"
        assert data["chat_id"] == "loop-abc"
        assert data["sender_id"] == "client-xyz"
        assert data["content"] == "Test message"

    def test_inherits_from_protocol_event(self):
        """Test event inherits from ProtocolEvent."""
        from soothe.foundation.base_events import ProtocolEvent

        event = ChannelMessageReceived(
            channel="test",
            chat_id="123",
            sender_id="456",
            content="text",
        )

        assert isinstance(event, ProtocolEvent)


class TestTextEvent:
    """Tests for TextEvent (complete text output)."""

    def test_basic_event(self):
        """Test basic TextEvent creation."""
        event = TextEvent(content="This is the complete response.")

        assert event.type == "soothe.output.text.complete"
        assert event.content == "This is the complete response."

    def test_to_dict(self):
        """Test serialization."""
        event = TextEvent(content="Response text")
        data = event.to_dict()

        assert data["type"] == "soothe.output.text.complete"
        assert data["content"] == "Response text"

    def test_inherits_from_output_event(self):
        """Test inherits from OutputEvent."""
        from soothe.foundation.base_events import OutputEvent

        event = TextEvent(content="text")
        assert isinstance(event, OutputEvent)


class TestTextDeltaEvent:
    """Tests for TextDeltaEvent (streaming chunk)."""

    def test_basic_event(self):
        """Test basic TextDeltaEvent creation."""
        event = TextDeltaEvent(
            content="This is a chunk",
            stream_id="stream-abc-123",
        )

        assert event.type == "soothe.output.text.delta"
        assert event.content == "This is a chunk"
        assert event.stream_id == "stream-abc-123"

    def test_stream_id_required(self):
        """Test stream_id is required (Pydantic ValidationError)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            # Missing stream_id raises ValidationError
            TextDeltaEvent(content="chunk")

    def test_to_dict(self):
        """Test serialization."""
        event = TextDeltaEvent(
            content="chunk",
            stream_id="stream-xyz",
        )
        data = event.to_dict()

        assert data["type"] == "soothe.output.text.delta"
        assert data["content"] == "chunk"
        assert data["stream_id"] == "stream-xyz"


class TestTextEndEvent:
    """Tests for TextEndEvent (stream end marker)."""

    def test_basic_event(self):
        """Test basic TextEndEvent creation."""
        event = TextEndEvent(stream_id="stream-abc-123")

        assert event.type == "soothe.output.text.end"
        assert event.stream_id == "stream-abc-123"

    def test_stream_id_required(self):
        """Test stream_id is required (Pydantic ValidationError)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TextEndEvent()

    def test_to_dict(self):
        """Test serialization."""
        event = TextEndEvent(stream_id="stream-end")
        data = event.to_dict()

        assert data["type"] == "soothe.output.text.end"
        assert data["stream_id"] == "stream-end"


class TestAgentUIEvent:
    """Tests for AgentUIEvent (structured UI payload)."""

    def test_basic_event(self):
        """Test basic AgentUIEvent creation."""
        event = AgentUIEvent(payload={"kind": "card", "title": "Summary"})

        assert event.type == "soothe.output.ui.render"
        assert event.payload["kind"] == "card"
        assert event.payload["title"] == "Summary"

    def test_complex_payload(self):
        """Test complex nested payload."""
        event = AgentUIEvent(
            payload={
                "kind": "form",
                "fields": [
                    {"name": "input1", "type": "text"},
                    {"name": "input2", "type": "select", "options": ["a", "b"]},
                ],
            }
        )

        assert event.payload["kind"] == "form"
        assert len(event.payload["fields"]) == 2

    def test_to_dict(self):
        """Test serialization."""
        event = AgentUIEvent(payload={"test": "value"})
        data = event.to_dict()

        assert data["type"] == "soothe.output.ui.render"
        assert data["payload"]["test"] == "value"


class TestProgressEvent:
    """Tests for ProgressEvent."""

    def test_basic_event(self):
        """Test basic ProgressEvent creation."""
        event = ProgressEvent(message="Processing...")

        assert event.type == "soothe.output.progress"
        assert event.message == "Processing..."
        assert event.tool_name is None

    def test_with_tool_name(self):
        """Test ProgressEvent with tool name."""
        event = ProgressEvent(message="Running tool...", tool_name="search")

        assert event.message == "Running tool..."
        assert event.tool_name == "search"

    def test_to_dict(self):
        """Test serialization."""
        event = ProgressEvent(message="Working", tool_name="run_command")
        data = event.to_dict()

        assert data["type"] == "soothe.output.progress"
        assert data["message"] == "Working"
        assert data["tool_name"] == "run_command"


class TestReasoningEvent:
    """Tests for ReasoningEvent."""

    def test_basic_event(self):
        """Test basic ReasoningEvent creation."""
        event = ReasoningEvent(content="The model thinks...")

        assert event.type == "soothe.output.reasoning"
        assert event.content == "The model thinks..."
        assert event.stream_id is None

    def test_with_stream_id(self):
        """Test ReasoningEvent with stream_id."""
        event = ReasoningEvent(
            content="Thinking chunk",
            stream_id="reasoning-stream-1",
        )

        assert event.stream_id == "reasoning-stream-1"

    def test_to_dict(self):
        """Test serialization."""
        event = ReasoningEvent(content="Reasoning text", stream_id="rs-1")
        data = event.to_dict()

        assert data["type"] == "soothe.output.reasoning"
        assert data["content"] == "Reasoning text"
        assert data["stream_id"] == "rs-1"


class TestEventHierarchy:
    """Tests for event inheritance hierarchy."""

    def test_all_output_events_share_base(self):
        """Test all output events inherit from OutputEvent."""
        from soothe.foundation.base_events import OutputEvent

        events = [
            TextEvent(content="text"),
            TextDeltaEvent(content="chunk", stream_id="s1"),
            TextEndEvent(stream_id="s1"),
            AgentUIEvent(payload={}),
            ProgressEvent(message="working"),
            ReasoningEvent(content="thinking"),
        ]

        for event in events:
            assert isinstance(event, OutputEvent)

    def test_all_events_have_type_field(self):
        """Test all events have type field."""
        events = [
            ChannelMessageReceived(channel="c", chat_id="1", sender_id="u", content="x"),
            TextEvent(content="text"),
            TextDeltaEvent(content="chunk", stream_id="s1"),
            TextEndEvent(stream_id="s1"),
            AgentUIEvent(payload={}),
            ProgressEvent(message="working"),
            ReasoningEvent(content="thinking"),
        ]

        for event in events:
            assert hasattr(event, "type")
            assert isinstance(event.type, str)
            assert event.type.startswith("soothe.")


class TestEventNamingConvention:
    """Tests for RFC-0015 event naming convention."""

    def test_channel_message_received_format(self):
        """Test naming follows soothe.<domain>.<component>.<action>."""
        event = ChannelMessageReceived(
            channel="test",
            chat_id="1",
            sender_id="u",
            content="x",
        )
        # soothe.channel.message.received
        parts = event.type.split(".")
        assert len(parts) == 4
        assert parts[0] == "soothe"
        assert parts[1] == "channel"
        assert parts[2] == "message"
        assert parts[3] == "received"

    def test_text_events_domain(self):
        """Test output text events have correct domain."""
        complete = TextEvent(content="text")
        delta = TextDeltaEvent(content="chunk", stream_id="s")
        end = TextEndEvent(stream_id="s")

        # All should be soothe.output.text.*
        for event in [complete, delta, end]:
            parts = event.type.split(".")
            assert parts[0] == "soothe"
            assert parts[1] == "output"
            assert parts[2] == "text"

    def test_progress_event_domain(self):
        """Test progress event domain."""
        event = ProgressEvent(message="working")
        parts = event.type.split(".")
        assert parts == ["soothe", "output", "progress"]

    def test_reasoning_event_domain(self):
        """Test reasoning event domain."""
        event = ReasoningEvent(content="thinking")
        parts = event.type.split(".")
        assert parts == ["soothe", "output", "reasoning"]

    def test_ui_event_domain(self):
        """Test UI event domain."""
        event = AgentUIEvent(payload={})
        parts = event.type.split(".")
        assert parts == ["soothe", "output", "ui", "render"]
