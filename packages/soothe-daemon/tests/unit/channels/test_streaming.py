"""Unit tests for streaming support (RFC-620 §6.3)."""

from __future__ import annotations

import pytest

from soothe_daemon.channel_manager import ChannelManager
from soothe_daemon.channels.message import (
    META_STREAM_DELTA,
    META_STREAM_END,
    META_STREAMED,
    ChannelMessage,
)


class MockEventBus:
    """Mock EventBus for testing."""

    def __init__(self):
        self._published: list[tuple[str, dict]] = []

    async def publish(self, topic: str, event: dict, event_meta=None):
        self._published.append((topic, event))


class MockDaemonConfig:
    """Mock daemon config for testing."""

    channels = type(
        "ChannelsConfig",
        (),
        {
            "transcription_provider": "groq",
            "send_max_retries": 3,
            "send_progress": True,
            "send_tool_hints": False,
            "show_reasoning": True,
        },
    )()

    transports = type(
        "TransportsConfig",
        (),
        {
            "websocket": type(
                "WSConfig",
                (),
                {
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": 8765,
                    "tls_enabled": False,
                    "max_frame_size": 10485760,
                },
            )(),
            "http_rest": type("HTTPConfig", (), {"enabled": False})(),
        },
    )()


class MockStreamingChannel:
    """Mock channel with streaming support."""

    name = "streaming_mock"
    supports_inbound = True
    supports_outbound = True
    supports_streaming = True

    def __init__(self):
        self._messages: list[ChannelMessage] = []
        self._deltas: list[tuple[str, str, dict]] = []

    async def send(self, chat_id: str, message: ChannelMessage):
        self._messages.append(message)

    async def send_delta(self, chat_id: str, delta: str, metadata: dict):
        self._deltas.append((chat_id, delta, metadata))


class MockNonStreamingChannel:
    """Mock channel without streaming support."""

    name = "non_streaming_mock"
    supports_inbound = True
    supports_outbound = True
    supports_streaming = False

    def __init__(self):
        self._messages: list[ChannelMessage] = []

    async def send(self, chat_id: str, message: ChannelMessage):
        self._messages.append(message)


class TestStreamingMessageSupport:
    """Tests for streaming message helper methods."""

    def test_is_stream_delta(self):
        """Test stream delta detection."""
        msg = ChannelMessage(
            channel="test",
            chat_id="123",
            content="chunk",
            metadata={META_STREAM_DELTA: True},
        )
        assert msg.is_stream_delta() is True

    def test_is_stream_end(self):
        """Test stream end detection."""
        msg = ChannelMessage(
            channel="test",
            chat_id="123",
            content="",
            metadata={META_STREAM_END: True},
        )
        assert msg.is_stream_end() is True

    def test_stream_delta_not_end(self):
        """Test delta without end flag."""
        msg = ChannelMessage(
            channel="test",
            chat_id="123",
            content="chunk",
            metadata={META_STREAM_DELTA: True},
        )
        assert msg.is_stream_end() is False

    def test_both_stream_delta_and_end(self):
        """Test message with both delta and end flags."""
        msg = ChannelMessage(
            channel="test",
            chat_id="123",
            content="final chunk",
            metadata={META_STREAM_DELTA: True, META_STREAM_END: True},
        )
        assert msg.is_stream_delta() is True
        assert msg.is_stream_end() is True


class TestChannelManagerStreaming:
    """Tests for ChannelManager streaming methods."""

    @pytest.mark.asyncio
    async def test_send_streaming_message_to_streaming_channel(self):
        """Test sending delta to streaming channel."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        channel = MockStreamingChannel()
        manager._channels["streaming_mock"] = channel

        msg = ChannelMessage(
            channel="streaming_mock",
            chat_id="chat123",
            content="delta chunk",
            metadata={META_STREAM_DELTA: True, "_stream_id": "s1"},
        )

        await manager.send_streaming_message("streaming_mock", "chat123", msg)

        # Delta should be sent via send_delta
        assert len(channel._deltas) == 1
        chat_id, delta, metadata = channel._deltas[0]
        assert chat_id == "chat123"
        assert delta == "delta chunk"

    @pytest.mark.asyncio
    async def test_send_streaming_message_to_non_streaming_channel(self):
        """Test buffering delta for non-streaming channel."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        channel = MockNonStreamingChannel()
        manager._channels["non_streaming_mock"] = channel

        # Send delta (should be buffered)
        msg1 = ChannelMessage(
            channel="non_streaming_mock",
            chat_id="chat123",
            content="chunk1",
            metadata={META_STREAM_DELTA: True, "_stream_id": "s1"},
        )
        await manager.send_streaming_message("non_streaming_mock", "chat123", msg1)

        # No message sent yet (buffered)
        assert len(channel._messages) == 0

        # Send stream end (should flush buffer)
        msg2 = ChannelMessage(
            channel="non_streaming_mock",
            chat_id="chat123",
            content="",
            metadata={META_STREAM_END: True, "_stream_id": "s1"},
        )
        await manager.send_streaming_message("non_streaming_mock", "chat123", msg2)

        # Combined message should be sent
        assert len(channel._messages) == 1
        assert channel._messages[0].content == "chunk1"
        assert META_STREAMED in channel._messages[0].metadata

    @pytest.mark.asyncio
    async def test_buffer_multiple_deltas(self):
        """Test buffering multiple deltas before flush."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        channel = MockNonStreamingChannel()
        manager._channels["non_streaming_mock"] = channel

        # Buffer multiple deltas
        for i in range(3):
            msg = ChannelMessage(
                channel="non_streaming_mock",
                chat_id="chat123",
                content=f"chunk{i}",
                metadata={META_STREAM_DELTA: True, "_stream_id": "s1"},
            )
            await manager.send_streaming_message("non_streaming_mock", "chat123", msg)

        # Flush with stream end
        end_msg = ChannelMessage(
            channel="non_streaming_mock",
            chat_id="chat123",
            content="",
            metadata={META_STREAM_END: True, "_stream_id": "s1"},
        )
        await manager.send_streaming_message("non_streaming_mock", "chat123", end_msg)

        # Combined message with all chunks
        assert len(channel._messages) == 1
        assert channel._messages[0].content == "chunk0chunk1chunk2"

    @pytest.mark.asyncio
    async def test_stream_end_to_streaming_channel(self):
        """Test stream end marker sent to streaming channel."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        channel = MockStreamingChannel()
        manager._channels["streaming_mock"] = channel

        msg = ChannelMessage(
            channel="streaming_mock",
            chat_id="chat123",
            content="",
            metadata={META_STREAM_END: True, "_stream_id": "s1"},
        )

        await manager.send_streaming_message("streaming_mock", "chat123", msg)

        # Stream end should be sent as delta with _stream_end
        assert len(channel._deltas) == 1
        _, delta, metadata = channel._deltas[0]
        assert META_STREAM_END in metadata


class TestStreamBufferManagement:
    """Tests for stream buffer management."""

    @pytest.mark.asyncio
    async def test_buffer_cleared_after_flush(self):
        """Test buffer is cleared after flush."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        channel = MockNonStreamingChannel()
        manager._channels["non_streaming_mock"] = channel

        # Buffer delta
        msg = ChannelMessage(
            channel="non_streaming_mock",
            chat_id="chat123",
            content="chunk",
            metadata={META_STREAM_DELTA: True},
        )
        await manager.send_streaming_message("non_streaming_mock", "chat123", msg)

        key = ("non_streaming_mock", "chat123")
        assert key in manager._stream_buffers

        # Flush
        end_msg = ChannelMessage(
            channel="non_streaming_mock",
            chat_id="chat123",
            content="",
            metadata={META_STREAM_END: True},
        )
        await manager.send_streaming_message("non_streaming_mock", "chat123", end_msg)

        # Buffer should be cleared
        assert key not in manager._stream_buffers

    @pytest.mark.asyncio
    async def test_different_chats_have_separate_buffers(self):
        """Test different chat_ids have separate buffers."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        channel = MockNonStreamingChannel()
        manager._channels["non_streaming_mock"] = channel

        # Buffer for chat1
        msg1 = ChannelMessage(
            channel="non_streaming_mock",
            chat_id="chat1",
            content="a",
            metadata={META_STREAM_DELTA: True},
        )
        await manager.send_streaming_message("non_streaming_mock", "chat1", msg1)

        # Buffer for chat2
        msg2 = ChannelMessage(
            channel="non_streaming_mock",
            chat_id="chat2",
            content="b",
            metadata={META_STREAM_DELTA: True},
        )
        await manager.send_streaming_message("non_streaming_mock", "chat2", msg2)

        # Both buffers should exist
        assert ("non_streaming_mock", "chat1") in manager._stream_buffers
        assert ("non_streaming_mock", "chat2") in manager._stream_buffers

        # Flush chat1
        end1 = ChannelMessage(
            channel="non_streaming_mock",
            chat_id="chat1",
            content="",
            metadata={META_STREAM_END: True},
        )
        await manager.send_streaming_message("non_streaming_mock", "chat1", end1)

        # chat1 buffer cleared, chat2 still has buffer
        assert ("non_streaming_mock", "chat1") not in manager._stream_buffers
        assert ("non_streaming_mock", "chat2") in manager._stream_buffers

    @pytest.mark.asyncio
    async def test_buffers_cleared_on_stop_all(self):
        """Test all buffers cleared on stop_all."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        # Add some buffers
        manager._stream_buffers[("ch1", "chat1")] = []
        manager._stream_buffers[("ch2", "chat2")] = []

        await manager.stop_all()

        assert len(manager._stream_buffers) == 0


class TestNonStreamingMessage:
    """Tests for non-streaming messages."""

    @pytest.mark.asyncio
    async def test_non_streaming_message_sent_directly(self):
        """Test non-streaming message sent directly without buffering."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        channel = MockNonStreamingChannel()
        manager._channels["non_streaming_mock"] = channel

        # Regular message (no streaming flags)
        msg = ChannelMessage(
            channel="non_streaming_mock",
            chat_id="chat123",
            content="complete message",
            metadata={},
        )

        await manager.send_streaming_message("non_streaming_mock", "chat123", msg)

        # Should be sent directly
        assert len(channel._messages) == 1
        assert channel._messages[0].content == "complete message"
