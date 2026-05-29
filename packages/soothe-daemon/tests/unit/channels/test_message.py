"""Unit tests for ChannelMessage dataclass (RFC-620 §2.1)."""

from __future__ import annotations

import pytest

from soothe_daemon.channels.message import (
    META_PROGRESS,
    META_REASONING,
    META_REASONING_DELTA,
    META_REASONING_END,
    META_STREAM_DELTA,
    META_STREAM_END,
    META_STREAM_ID,
    META_TOOL_HINT,
    ChannelMessage,
)


class TestChannelMessage:
    """Tests for ChannelMessage dataclass."""

    def test_basic_message(self):
        """Test basic message creation."""
        msg = ChannelMessage(
            channel="websocket",
            chat_id="chat123",
            content="Hello world",
        )

        assert msg.channel == "websocket"
        assert msg.chat_id == "chat123"
        assert msg.content == "Hello world"
        assert msg.media == []
        assert msg.buttons == []
        assert msg.metadata == {}
        assert msg.reply_to is None

    def test_message_with_all_fields(self):
        """Test message with all fields populated."""
        msg = ChannelMessage(
            channel="telegram",
            chat_id="chat456",
            content="Check this out!",
            media=["/path/to/image.png", "https://example.com/file.pdf"],
            buttons=[["Yes", "No"], ["Cancel"]],
            metadata={"message_id": "msg789"},
            reply_to="msg123",
        )

        assert msg.channel == "telegram"
        assert msg.chat_id == "chat456"
        assert msg.content == "Check this out!"
        assert len(msg.media) == 2
        assert len(msg.buttons) == 2
        assert msg.metadata["message_id"] == "msg789"
        assert msg.reply_to == "msg123"

    def test_is_stream_delta(self):
        """Test is_stream_delta helper."""
        msg = ChannelMessage(
            channel="test",
            chat_id="123",
            content="chunk",
            metadata={META_STREAM_DELTA: True},
        )

        assert msg.is_stream_delta() is True

        msg2 = ChannelMessage(
            channel="test",
            chat_id="123",
            content="complete",
            metadata={},
        )
        assert msg2.is_stream_delta() is False

    def test_is_stream_end(self):
        """Test is_stream_end helper."""
        msg = ChannelMessage(
            channel="test",
            chat_id="123",
            content="",
            metadata={META_STREAM_END: True},
        )

        assert msg.is_stream_end() is True

    def test_is_progress(self):
        """Test is_progress helper."""
        msg = ChannelMessage(
            channel="test",
            chat_id="123",
            content="Processing...",
            metadata={META_PROGRESS: True},
        )

        assert msg.is_progress() is True

    def test_is_tool_hint(self):
        """Test is_tool_hint helper."""
        msg = ChannelMessage(
            channel="test",
            chat_id="123",
            content="Running tool...",
            metadata={META_TOOL_HINT: True},
        )

        assert msg.is_tool_hint() is True

    def test_is_reasoning(self):
        """Test is_reasoning helper for all reasoning metadata types."""
        # One-shot reasoning
        msg1 = ChannelMessage(
            channel="test",
            chat_id="123",
            content="Thinking...",
            metadata={META_REASONING: True},
        )
        assert msg1.is_reasoning() is True

        # Streaming reasoning delta
        msg2 = ChannelMessage(
            channel="test",
            chat_id="123",
            content="reason chunk",
            metadata={META_REASONING_DELTA: True},
        )
        assert msg2.is_reasoning() is True

        # Reasoning end
        msg3 = ChannelMessage(
            channel="test",
            chat_id="123",
            content="",
            metadata={META_REASONING_END: True},
        )
        assert msg3.is_reasoning() is True

        # Non-reasoning
        msg4 = ChannelMessage(
            channel="test",
            chat_id="123",
            content="Regular message",
            metadata={},
        )
        assert msg4.is_reasoning() is False

    def test_get_stream_id(self):
        """Test get_stream_id helper."""
        msg = ChannelMessage(
            channel="test",
            chat_id="123",
            content="chunk",
            metadata={META_STREAM_ID: "stream-abc-123"},
        )

        assert msg.get_stream_id() == "stream-abc-123"

        msg2 = ChannelMessage(
            channel="test",
            chat_id="123",
            content="chunk",
            metadata={},
        )
        assert msg2.get_stream_id() is None

    def test_metadata_constants(self):
        """Test metadata key constants are defined."""
        assert META_STREAM_DELTA == "_stream_delta"
        assert META_STREAM_END == "_stream_end"
        assert META_STREAM_ID == "_stream_id"
        assert META_PROGRESS == "_progress"
        assert META_TOOL_HINT == "_tool_hint"
        assert META_REASONING == "_reasoning"
        assert META_REASONING_DELTA == "_reasoning_delta"


class TestChannelMessageEquality:
    """Tests for ChannelMessage comparison."""

    def test_messages_with_same_content_are_equal(self):
        """Test equality based on dataclass fields."""
        msg1 = ChannelMessage(
            channel="test",
            chat_id="123",
            content="Hello",
        )
        msg2 = ChannelMessage(
            channel="test",
            chat_id="123",
            content="Hello",
        )

        assert msg1 == msg2

    def test_messages_with_different_content_are_not_equal(self):
        """Test inequality when content differs."""
        msg1 = ChannelMessage(
            channel="test",
            chat_id="123",
            content="Hello",
        )
        msg2 = ChannelMessage(
            channel="test",
            chat_id="123",
            content="World",
        )

        assert msg1 != msg2

    def test_messages_with_different_channels_are_not_equal(self):
        """Test inequality when channel differs."""
        msg1 = ChannelMessage(
            channel="telegram",
            chat_id="123",
            content="Hello",
        )
        msg2 = ChannelMessage(
            channel="discord",
            chat_id="123",
            content="Hello",
        )

        assert msg1 != msg2


class TestChannelMessageDefaults:
    """Tests for default factory behavior."""

    def test_default_media_is_empty_list(self):
        """Test media defaults to empty list."""
        msg = ChannelMessage(channel="test", chat_id="123", content="text")
        assert msg.media == []
        assert isinstance(msg.media, list)

    def test_default_buttons_is_empty_list(self):
        """Test buttons defaults to empty list."""
        msg = ChannelMessage(channel="test", chat_id="123", content="text")
        assert msg.buttons == []
        assert isinstance(msg.buttons, list)

    def test_default_metadata_is_empty_dict(self):
        """Test metadata defaults to empty dict."""
        msg = ChannelMessage(channel="test", chat_id="123", content="text")
        assert msg.metadata == {}
        assert isinstance(msg.metadata, dict)

    def test_lists_are_independent_per_instance(self):
        """Test that default lists are not shared between instances."""
        msg1 = ChannelMessage(channel="test", chat_id="123", content="text")
        msg2 = ChannelMessage(channel="test", chat_id="456", content="text")

        msg1.media.append("file1")
        msg1.buttons.append(["btn1"])
        msg1.metadata["key"] = "value"

        # msg2 should remain empty
        assert msg2.media == []
        assert msg2.buttons == []
        assert msg2.metadata == {}