"""Unit tests for WebSocketChannel (RFC-620)."""

from __future__ import annotations

from soothe_daemon.channels.websocket import WebSocketChannel


class TestWebSocketChannelAttributes:
    """Tests for WebSocketChannel attributes."""

    def test_channel_metadata(self):
        """Test channel name and display name."""
        assert WebSocketChannel.name == "websocket"
        assert WebSocketChannel.display_name == "WebSocket"

    def test_capability_flags(self):
        """Test capability flags are correct."""
        assert WebSocketChannel.supports_inbound is True
        assert WebSocketChannel.supports_outbound is True
        assert WebSocketChannel.supports_streaming is True

    def test_inherits_from_channel(self):
        """Test inherits from Channel base class."""
        from soothe_daemon.channels.base import Channel

        assert issubclass(WebSocketChannel, Channel)


class TestWebSocketChannelMethods:
    """Tests for WebSocketChannel methods."""

    def test_channel_name(self):
        """Test channel name identifier."""
        config = MockWebSocketConfig()
        manager = MockManager()
        channel = WebSocketChannel(config, manager)

        assert channel.name == "websocket"


class MockWebSocketConfig:
    """Mock WebSocket config."""

    enabled = True
    host = "127.0.0.1"
    port = 8765
    tls_enabled = False
    tls_cert = None
    tls_key = None
    cors_origins = ["http://localhost:*"]
    max_frame_size = 10485760


class MockManager:
    """Mock manager for testing."""

    _message_handler = None
    _handshake_callback = None


class TestWebSocketChannelInit:
    """Tests for WebSocketChannel initialization."""

    def test_basic_init(self):
        """Test basic initialization."""
        config = MockWebSocketConfig()
        manager = MockManager()

        channel = WebSocketChannel(config, manager)

        assert channel.name == "websocket"
        assert channel._ws_config == config
        assert channel._manager == manager
        assert channel.is_running is False

    def test_init_with_session_manager(self):
        """Test initialization with session manager."""
        config = MockWebSocketConfig()
        manager = MockManager()
        session_manager = object()

        channel = WebSocketChannel(
            config,
            manager,
            session_manager=session_manager,
        )

        assert channel._session_manager == session_manager

    def test_init_with_unified_app(self):
        """Test initialization with unified app."""
        from fastapi import FastAPI

        config = MockWebSocketConfig()
        manager = MockManager()
        app = FastAPI()

        channel = WebSocketChannel(
            config,
            manager,
            unified_app=app,
        )

        assert channel._unified_parent_app == app


class TestWebSocketChannelStreaming:
    """Tests for WebSocketChannel streaming capabilities."""

    def test_supports_streaming_is_true(self):
        """Test streaming capability."""
        config = MockWebSocketConfig()
        manager = MockManager()
        channel = WebSocketChannel(config, manager)

        assert channel.supports_streaming is True

    def test_send_delta_method_exists(self):
        """Test send_delta method exists."""
        config = MockWebSocketConfig()
        manager = MockManager()
        channel = WebSocketChannel(config, manager)

        assert hasattr(channel, "send_delta")
        assert callable(channel.send_delta)


class TestWebSocketChannelMessageConversion:
    """Tests for message conversion."""

    def test_channel_message_to_wire(self):
        """Test ChannelMessage to wire format conversion."""
        from soothe_daemon.channels.message import ChannelMessage

        config = MockWebSocketConfig()
        manager = MockManager()
        channel = WebSocketChannel(config, manager)

        msg = ChannelMessage(
            channel="websocket",
            chat_id="loop-abc",
            content="Hello world",
            metadata={"_progress": True},
        )

        wire = channel._channel_message_to_wire(msg)

        assert wire["type"] == "event"
        assert wire["loop_id"] == "loop-abc"
        assert wire["data"]["type"] == "soothe.output.text.complete"
        assert wire["data"]["content"] == "Hello world"
        assert wire["data"]["_progress"] is True

    def test_channel_message_to_wire_with_streaming(self):
        """Test streaming message conversion."""
        from soothe_daemon.channels.message import META_STREAM_DELTA, ChannelMessage

        config = MockWebSocketConfig()
        manager = MockManager()
        channel = WebSocketChannel(config, manager)

        msg = ChannelMessage(
            channel="websocket",
            chat_id="loop-xyz",
            content="partial",
            metadata={META_STREAM_DELTA: True, "_stream_id": "s1"},
        )

        wire = channel._channel_message_to_wire(msg)

        assert wire["data"]["_stream_delta"] is True
        assert wire["data"]["_stream_id"] == "s1"


class TestWebSocketChannelCORS:
    """Tests for CORS validation."""

    def test_empty_origin_allowed(self):
        """Test empty origin is allowed."""
        config = MockWebSocketConfig()
        manager = MockManager()
        channel = WebSocketChannel(config, manager)

        assert channel._validate_cors(None) is True

    def test_matching_origin_allowed(self):
        """Test matching origin pattern is allowed."""
        config = MockWebSocketConfig()
        manager = MockManager()
        channel = WebSocketChannel(config, manager)

        assert channel._validate_cors("http://localhost:3000") is True
        assert channel._validate_cors("http://localhost:8080") is True

    def test_non_matching_origin_denied(self):
        """Test non-matching origin is denied."""
        config = MockWebSocketConfig()
        manager = MockManager()
        channel = WebSocketChannel(config, manager)

        assert channel._validate_cors("http://example.com") is False
        assert channel._validate_cors("https://evil.com") is False
