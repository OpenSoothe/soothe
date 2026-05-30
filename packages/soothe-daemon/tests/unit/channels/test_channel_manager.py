"""Unit tests for ChannelManager (RFC-620 §3)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_daemon.channel_manager import _SEND_RETRY_DELAYS, ChannelManager
from soothe_daemon.channels.message import ChannelMessage


class MockChannel:
    """Mock channel for testing."""

    name = "mock"
    display_name = "Mock"
    supports_inbound = True
    supports_outbound = True
    supports_streaming = False
    client_count = 0

    def __init__(self, config, **kwargs):
        self.config = config
        self._messages: list[ChannelMessage] = []
        self._running = False

    async def start(self):
        self._running = True

    async def stop(self):
        self._running = False

    async def broadcast(self, message):
        pass

    async def send(self, chat_id: str, message: ChannelMessage):
        self._messages.append(message)


class MockEventBus:
    """Mock EventBus for testing."""

    def __init__(self):
        self._published: list[tuple[str, dict]] = []

    async def publish(self, topic: str, event: dict, event_meta=None):
        self._published.append((topic, event))


class MockDaemonConfig:
    """Mock daemon config for testing."""

    channels = MagicMock()
    channels.transcription_provider = "groq"
    channels.send_max_retries = 3

    transports = MagicMock()
    transports.websocket = MagicMock()
    transports.websocket.enabled = True
    transports.websocket.host = "127.0.0.1"
    transports.websocket.port = 8765
    transports.websocket.tls_enabled = False
    transports.websocket.max_frame_size = 10485760

    transports.http_rest = MagicMock()
    transports.http_rest.enabled = False


class TestChannelManagerInit:
    """Tests for ChannelManager initialization."""

    def test_basic_init(self):
        """Test basic initialization."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()

        manager = ChannelManager(config, event_bus)

        assert manager._config == config
        assert manager._event_bus == event_bus
        assert manager._channels == {}
        assert manager._loop_to_channel == {}
        assert manager._channel_to_loop == {}
        assert manager._started is False

    def test_init_with_optional_params(self):
        """Test initialization with optional parameters."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        runner = MagicMock()
        soothe_config = MagicMock()
        session_manager = MagicMock()
        autopilot_service = MagicMock()

        manager = ChannelManager(
            config,
            event_bus,
            runner=runner,
            soothe_config=soothe_config,
            session_manager=session_manager,
            autopilot_service=autopilot_service,
        )

        assert manager._runner == runner
        assert manager._soothe_config == soothe_config
        assert manager._session_manager == session_manager
        assert manager._autopilot_service == autopilot_service


class TestHandleInbound:
    """Tests for handle_inbound method."""

    @pytest.mark.asyncio
    async def test_creates_loop_id_for_new_conversation(self):
        """Test loop_id creation for new (channel, chat_id)."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        loop_id = await manager.handle_inbound(
            channel="telegram",
            chat_id="chat123",
            sender_id="user456",
            content="Hello",
        )

        # Should create loop_id = "telegram:chat123"
        assert loop_id == "telegram:chat123"

        # Should store mapping
        assert manager._channel_to_loop[("telegram", "chat123")] == loop_id
        assert manager._loop_to_channel[loop_id] == ("telegram", "chat123")

    @pytest.mark.asyncio
    async def test_returns_existing_loop_id(self):
        """Test returns existing loop_id for same (channel, chat_id)."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        # First call creates loop_id
        loop_id1 = await manager.handle_inbound(
            channel="telegram",
            chat_id="chat123",
            sender_id="user1",
            content="First",
        )

        # Second call should return same loop_id
        loop_id2 = await manager.handle_inbound(
            channel="telegram",
            chat_id="chat123",
            sender_id="user2",
            content="Second",
        )

        assert loop_id1 == loop_id2

    @pytest.mark.asyncio
    async def test_websocket_chat_id_is_loop_id(self):
        """Test WebSocket chat_id IS the loop_id."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        loop_id = await manager.handle_inbound(
            channel="websocket",
            chat_id="explicit-loop-abc",
            sender_id="client-xyz",
            content="Hello",
        )

        # For WebSocket, chat_id is used directly as loop_id
        assert loop_id == "explicit-loop-abc"

    @pytest.mark.asyncio
    async def test_publishes_to_event_bus(self):
        """Test publishes ChannelMessageReceived to EventBus."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        await manager.handle_inbound(
            channel="telegram",
            chat_id="chat123",
            sender_id="user456",
            content="Hello world",
            media=["image.png"],
            metadata={"platform_msg_id": "msg789"},
        )

        # Should have published to loop topic
        assert len(event_bus._published) == 1
        topic, event = event_bus._published[0]

        assert topic == "loop:telegram:chat123"
        assert event["type"] == "soothe.channel.message.received"
        assert event["channel"] == "telegram"
        assert event["chat_id"] == "chat123"
        assert event["sender_id"] == "user456"
        assert event["content"] == "Hello world"
        assert event["media"] == ["image.png"]


class TestLoopIdMapping:
    """Tests for loop ID mapping methods."""

    def test_get_loop_for_channel_chat(self):
        """Test get_loop_for_channel_chat method."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        # Pre-populate mapping
        manager._channel_to_loop[("telegram", "chat123")] = "telegram:chat123"

        result = manager.get_loop_for_channel_chat("telegram", "chat123")
        assert result == "telegram:chat123"

        result = manager.get_loop_for_channel_chat("telegram", "nonexistent")
        assert result is None

    def test_get_channel_chat_for_loop(self):
        """Test get_channel_chat_for_loop method."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        # Pre-populate mapping
        manager._loop_to_channel["telegram:chat123"] = ("telegram", "chat123")

        result = manager.get_channel_chat_for_loop("telegram:chat123")
        assert result == ("telegram", "chat123")

        result = manager.get_channel_chat_for_loop("nonexistent")
        assert result is None


class TestRetryPolicy:
    """Tests for retry policy."""

    def test_retry_delays_constant(self):
        """Test retry delays are defined."""
        assert _SEND_RETRY_DELAYS == (1, 2, 4)

    @pytest.mark.asyncio
    async def test_send_with_retry_success_on_first_attempt(self):
        """Test successful send on first attempt."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        channel = MockChannel({})
        msg = ChannelMessage(channel="mock", chat_id="123", content="Hello")

        # Should succeed on first attempt
        await manager._send_with_retry(channel, "123", msg)

        assert len(channel._messages) == 1

    @pytest.mark.asyncio
    async def test_send_with_retry_retries_on_failure(self):
        """Test retries on failure."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        # Create channel with failing send
        class FailingChannel(MockChannel):
            def __init__(self, config, fail_count=2):
                super().__init__(config)
                self._fail_count = fail_count
                self._call_count = 0

            async def send(self, chat_id: str, message: ChannelMessage):
                self._call_count += 1
                if self._call_count <= self._fail_count:
                    raise ConnectionError("Failed")
                self._messages.append(message)

        channel = FailingChannel({}, fail_count=2)
        msg = ChannelMessage(channel="mock", chat_id="123", content="Hello")

        await manager._send_with_retry(channel, "123", msg)

        # Should have retried (failed twice, succeeded on third)
        assert channel._call_count == 3
        assert len(channel._messages) == 1

    @pytest.mark.asyncio
    async def test_send_with_retry_max_attempts(self):
        """Test max attempts before giving up."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        # Create channel that always fails
        class AlwaysFailChannel(MockChannel):
            def __init__(self, config):
                super().__init__(config)
                self._call_count = 0

            async def send(self, chat_id: str, message: ChannelMessage):
                self._call_count += 1
                raise ConnectionError("Always fails")

        channel = AlwaysFailChannel({})
        msg = ChannelMessage(channel="mock", chat_id="123", content="Hello")

        await manager._send_with_retry(channel, "123", msg)

        # Should have tried max_retries times (default 3)
        assert channel._call_count == 3
        # Message should not be delivered
        assert len(channel._messages) == 0

    @pytest.mark.asyncio
    async def test_send_with_retry_raises_cancelled(self):
        """Test CancelledError is re-raised."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        # Create channel that raises CancelledError
        class CancelledChannel(MockChannel):
            async def send(self, chat_id: str, message: ChannelMessage):
                raise asyncio.CancelledError()

        channel = CancelledChannel({})
        msg = ChannelMessage(channel="mock", chat_id="123", content="Hello")

        with pytest.raises(asyncio.CancelledError):
            await manager._send_with_retry(channel, "123", msg)


class TestChannelManagerProperties:
    """Tests for ChannelManager properties."""

    def test_client_count_empty(self):
        """Test client_count with no channels."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        assert manager.client_count == 0

    def test_client_count_with_channels(self):
        """Test client_count aggregates from channels."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        # Add mock channels with client counts
        ch1 = MockChannel({})
        ch1.client_count = 5
        ch2 = MockChannel({})
        ch2.client_count = 3

        manager._channels["ch1"] = ch1
        manager._channels["ch2"] = ch2

        assert manager.client_count == 8

    def test_channel_count(self):
        """Test channel_count."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        assert manager.channel_count == 0

        manager._channels["ch1"] = MockChannel({})
        manager._channels["ch2"] = MockChannel({})

        assert manager.channel_count == 2

    def test_enabled_channels(self):
        """Test enabled_channels returns channel names."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        manager._channels["websocket"] = MockChannel({})
        manager._channels["http_rest"] = MockChannel({})

        assert manager.enabled_channels == ["websocket", "http_rest"]

    def test_get_channel_info(self):
        """Test get_channel_info returns list of dicts."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        ch1 = MockChannel({})
        ch1.client_count = 5
        manager._channels["ch1"] = ch1

        info = manager.get_channel_info()

        assert len(info) == 1
        assert info[0]["type"] == "mock"
        assert info[0]["client_count"] == 5

    def test_channels_property(self):
        """Test channels property returns _channels dict."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        manager._channels["test"] = MockChannel({})

        assert manager.channels == manager._channels
        assert "test" in manager.channels


class TestBroadcast:
    """Tests for broadcast method."""

    @pytest.mark.asyncio
    async def test_broadcast_to_all_channels(self):
        """Test broadcast sends to all channels."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        ch1 = MockChannel({})
        ch1.broadcast = AsyncMock()
        ch2 = MockChannel({})
        ch2.broadcast = AsyncMock()

        manager._channels["ch1"] = ch1
        manager._channels["ch2"] = ch2
        manager._started = True

        await manager.broadcast({"type": "status", "state": "idle"})

        ch1.broadcast.assert_called_once()
        ch2.broadcast.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_skips_when_not_started(self):
        """Test broadcast skips when manager not started."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        manager._channels["ch1"] = MockChannel({})
        manager._started = False

        await manager.broadcast({"type": "status"})

        # No exception, just skipped


class TestSendToChannel:
    """Tests for send_to_channel method."""

    @pytest.mark.asyncio
    async def test_send_to_existing_channel(self):
        """Test send_to_channel to existing channel."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        channel = MockChannel({})
        manager._channels["mock"] = channel

        msg = ChannelMessage(channel="mock", chat_id="123", content="Hello")
        await manager.send_to_channel("mock", "123", msg)

        assert len(channel._messages) == 1

    @pytest.mark.asyncio
    async def test_send_to_unknown_channel(self):
        """Test send_to_channel to unknown channel."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        msg = ChannelMessage(channel="unknown", chat_id="123", content="Hello")
        await manager.send_to_channel("unknown", "123", msg)

        # Should not raise, just log warning

    @pytest.mark.asyncio
    async def test_send_to_no_outbound_channel(self):
        """Test send_to_channel skips channel with no outbound."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        channel = MockChannel({})
        channel.supports_outbound = False
        manager._channels["readonly"] = channel

        msg = ChannelMessage(channel="readonly", chat_id="123", content="Hello")
        await manager.send_to_channel("readonly", "123", msg)

        # Should not send to channel
        assert len(channel._messages) == 0


class TestGetChannel:
    """Tests for get_channel method."""

    def test_get_existing_channel(self):
        """Test get_channel returns existing channel."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        channel = MockChannel({})
        manager._channels["test"] = channel

        result = manager.get_channel("test")
        assert result == channel

    def test_get_nonexistent_channel(self):
        """Test get_channel returns None for nonexistent."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        result = manager.get_channel("nonexistent")
        assert result is None


class TestSetMessageHandler:
    """Tests for set_message_handler method."""

    def test_set_message_handler(self):
        """Test setting message handler."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        handler = MagicMock()
        manager.set_message_handler(handler)

        assert manager._message_handler == handler

    def test_set_handshake_callback(self):
        """Test setting handshake callback."""
        config = MockDaemonConfig()
        event_bus = MockEventBus()
        manager = ChannelManager(config, event_bus)

        callback = MagicMock()
        manager.set_handshake_callback(callback)

        assert manager._handshake_callback == callback
