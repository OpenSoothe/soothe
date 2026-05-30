"""Unit tests for Channel base class (RFC-620 §1)."""

from __future__ import annotations

import pytest

from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage


class MockChannel(Channel):
    """Mock channel for testing."""

    name = "mock"
    display_name = "Mock Channel"
    supports_inbound = True
    supports_outbound = True
    supports_streaming = False

    def __init__(self, config, manager):
        super().__init__(config, manager)
        self._messages_sent: list[ChannelMessage] = []

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        self._messages_sent.append(message)


class MockChannelManager:
    """Mock manager for testing."""

    def __init__(self):
        self._inbound_messages: list[dict] = []

    async def handle_inbound(self, **kwargs) -> str:
        self._inbound_messages.append(kwargs)
        return f"{kwargs['channel']}:{kwargs['chat_id']}"

    async def transcribe_audio(self, file_path) -> str:
        return "transcribed text"


class TestChannelBase:
    """Tests for Channel ABC."""

    def test_channel_default_attributes(self):
        """Test default attribute values."""
        manager = MockChannelManager()
        channel = MockChannel({}, manager)

        assert channel.name == "mock"
        assert channel.display_name == "Mock Channel"
        assert channel.supports_inbound is True
        assert channel.supports_outbound is True
        assert channel.supports_streaming is False
        assert channel.is_running is False

    def test_channel_custom_capability_flags(self):
        """Test custom capability flags."""

        class ReadOnlyChannel(MockChannel):
            supports_inbound = True
            supports_outbound = False
            supports_streaming = False

        manager = MockChannelManager()
        channel = ReadOnlyChannel({}, manager)

        assert channel.supports_inbound is True
        assert channel.supports_outbound is False

    def test_is_allowed_wildcard(self):
        """Test allow_from wildcard permission."""
        manager = MockChannelManager()
        channel = MockChannel({"allow_from": ["*"]}, manager)

        assert channel.is_allowed("user123") is True
        assert channel.is_allowed("anyone") is True

    def test_is_allowed_specific_users(self):
        """Test allow_from with specific user IDs."""
        manager = MockChannelManager()
        channel = MockChannel({"allow_from": ["user123", "user456"]}, manager)

        assert channel.is_allowed("user123") is True
        assert channel.is_allowed("user456") is True
        assert channel.is_allowed("unknown") is False

    def test_is_allowed_empty_list(self):
        """Test allow_from with empty list denies all."""
        manager = MockChannelManager()
        channel = MockChannel({"allow_from": []}, manager)

        assert channel.is_allowed("user123") is False

    def test_is_allowed_no_config(self):
        """Test default behavior with no allow_from config."""
        manager = MockChannelManager()
        channel = MockChannel({}, manager)

        assert channel.is_allowed("user123") is False

    def test_client_count_default(self):
        """Test default client_count implementation."""
        manager = MockChannelManager()
        channel = MockChannel({}, manager)

        assert channel.client_count == 0

    def test_default_config(self):
        """Test default_config class method."""
        config = MockChannel.default_config()
        assert config == {"enabled": False}

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self):
        """Test start/stop lifecycle."""
        manager = MockChannelManager()
        channel = MockChannel({}, manager)

        await channel.start()
        assert channel.is_running is True

        await channel.stop()
        assert channel.is_running is False

    @pytest.mark.asyncio
    async def test_send_message(self):
        """Test send method."""
        manager = MockChannelManager()
        channel = MockChannel({}, manager)

        msg = ChannelMessage(channel="mock", chat_id="123", content="Hello")
        await channel.send("123", msg)

        assert len(channel._messages_sent) == 1
        assert channel._messages_sent[0].content == "Hello"

    @pytest.mark.asyncio
    async def test_send_delta_default_noop(self):
        """Test send_delta default implementation (no-op)."""
        manager = MockChannelManager()
        channel = MockChannel({}, manager)

        # Default send_delta is no-op, should not raise
        await channel.send_delta("123", "partial text", {})

    @pytest.mark.asyncio
    async def test_handle_message_allowed(self):
        """Test _handle_message with allowed sender."""
        manager = MockChannelManager()
        channel = MockChannel({"allow_from": ["*"]}, manager)

        loop_id = await channel._handle_message(
            sender_id="user123",
            chat_id="chat456",
            content="Hello world",
        )

        assert loop_id == "mock:chat456"
        assert len(manager._inbound_messages) == 1

    @pytest.mark.asyncio
    async def test_handle_message_denied(self):
        """Test _handle_message with denied sender."""
        manager = MockChannelManager()
        channel = MockChannel({"allow_from": []}, manager)

        loop_id = await channel._handle_message(
            sender_id="user123",
            chat_id="chat456",
            content="Hello world",
        )

        assert loop_id is None
        assert len(manager._inbound_messages) == 0

    @pytest.mark.asyncio
    async def test_handle_message_with_streaming_flag(self):
        """Test _handle_message adds streaming hint for streaming channels."""

        class StreamingChannel(MockChannel):
            supports_streaming = True

        manager = MockChannelManager()
        channel = StreamingChannel({"allow_from": ["*"]}, manager)

        await channel._handle_message(
            sender_id="user123",
            chat_id="chat456",
            content="Hello",
        )

        # Should have _wants_stream in metadata
        inbound = manager._inbound_messages[0]
        assert inbound["metadata"].get("_wants_stream") is True

    @pytest.mark.asyncio
    async def test_login_default(self):
        """Test default login implementation."""
        manager = MockChannelManager()
        channel = MockChannel({}, manager)

        # Default login returns True
        result = await channel.login()
        assert result is True

        result = await channel.login(force=True)
        assert result is True

    @pytest.mark.asyncio
    async def test_transcribe_audio_delegates_to_manager(self):
        """Test transcribe_audio delegates to manager."""
        manager = MockChannelManager()
        channel = MockChannel({}, manager)

        result = await channel.transcribe_audio("/path/to/audio.wav")
        assert result == "transcribed text"


class TestStreamingChannel:
    """Tests for streaming-capable channels."""

    class StreamingMockChannel(MockChannel):
        """Channel with streaming support."""

        supports_streaming = True
        _delta_buffer: list[str] = []

        async def send_delta(self, chat_id: str, delta: str, metadata: dict) -> None:
            self._delta_buffer.append(delta)

    def test_streaming_flag(self):
        """Test supports_streaming is True."""
        manager = MockChannelManager()
        channel = self.StreamingMockChannel({}, manager)

        assert channel.supports_streaming is True

    @pytest.mark.asyncio
    async def test_send_delta_override(self):
        """Test send_delta implementation."""
        manager = MockChannelManager()
        channel = self.StreamingMockChannel({}, manager)

        await channel.send_delta("123", "chunk1", {})
        await channel.send_delta("123", "chunk2", {})

        assert channel._delta_buffer == ["chunk1", "chunk2"]


class TestReadOnlyChannel:
    """Tests for read-only (no outbound) channels."""

    class ReadOnlyMockChannel(MockChannel):
        """Channel that only receives messages."""

        supports_outbound = False

    def test_no_outbound_capability(self):
        """Test supports_outbound is False."""
        manager = MockChannelManager()
        channel = self.ReadOnlyMockChannel({}, manager)

        assert channel.supports_outbound is False
