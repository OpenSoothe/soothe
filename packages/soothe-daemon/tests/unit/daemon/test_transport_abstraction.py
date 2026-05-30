"""Tests for transport abstraction layer (RFC-0013)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from soothe_daemon.channel_manager import ChannelManager
from soothe_daemon.channels.websocket import WebSocketChannel
from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.config.models import HttpRestConfig, TransportConfig, WebSocketConfig
from soothe_daemon.protocol import (
    ERROR_INVALID_MESSAGE,
    create_error_response,
    validate_message,
    validate_message_size,
)
from soothe_daemon.transports.base import TransportClient, TransportServer
from soothe_daemon.transports.websocket import WebSocketTransport


class TestProtocolV2:
    """Tests for protocol_v2 message validation.

    Legacy global "input" message type was removed in favor of loop_input.
    """

    def test_validate_command_message_valid(self) -> None:
        """Valid command message passes validation."""
        msg = {"type": "command", "cmd": "/help"}
        errors = validate_message(msg)
        assert errors == []

    def test_validate_command_message_missing_cmd(self) -> None:
        """Command message missing cmd field fails validation."""
        msg = {"type": "command"}
        errors = validate_message(msg)
        assert len(errors) == 1
        assert "cmd" in errors[0]

    def test_validate_resume_thread_message_valid(self) -> None:
        """Valid resume_thread message passes validation."""
        msg = {"type": "resume_thread", "thread_id": "abc123"}
        errors = validate_message(msg)
        assert errors == []

    def test_validate_auth_message_valid(self) -> None:
        """Valid auth message passes validation."""
        msg = {"type": "auth", "token": "sk_live_abc123"}
        errors = validate_message(msg)
        assert errors == []

    def test_validate_unknown_message_type(self) -> None:
        """Unknown message types are allowed (forward compatibility)."""
        msg = {"type": "future_message_type", "data": "value"}
        errors = validate_message(msg)
        assert errors == []

    def test_validate_message_missing_type(self) -> None:
        """Message missing type field fails validation."""
        msg = {"text": "hello"}
        errors = validate_message(msg)
        assert len(errors) == 1
        assert "type" in errors[0]

    def test_validate_message_size_within_limit(self) -> None:
        """Message within size limit passes validation."""
        msg = {"type": "loop_input", "loop_id": "test", "content": "hello" * 100}
        is_valid = validate_message_size(msg)
        assert is_valid is True

    def test_validate_message_size_exceeds_limit(self) -> None:
        """Message exceeding size limit fails validation."""
        msg = {"type": "loop_input", "loop_id": "test", "content": "x" * (11 * 1024 * 1024)}  # 11MB
        is_valid = validate_message_size(msg)
        assert is_valid is False

    def test_create_error_response(self) -> None:
        """Error response is created correctly."""
        error_dict = create_error_response(
            ERROR_INVALID_MESSAGE,
            "Test error message",
            {"key": "value"},
        )

        assert error_dict["type"] == "error"
        assert error_dict["code"] == "INVALID_MESSAGE"
        assert error_dict["message"] == "Test error message"
        assert error_dict["details"]["key"] == "value"


class TestTransportConfig:
    """Transport configuration helpers."""

    def test_http_rest_enabled_by_default(self) -> None:
        """Fresh daemon config enables HTTP REST without explicit YAML."""
        assert HttpRestConfig().enabled is True
        assert TransportConfig().http_rest.enabled is True
        assert SootheDaemonConfig().transports.http_rest.enabled is True

    def test_effective_http_rest_listen_when_unified(self) -> None:
        """HTTP REST reaches the WebSocket bind address when both transports are on."""
        cfg = TransportConfig(
            websocket=WebSocketConfig(enabled=True, host="10.0.0.2", port=9001),
            http_rest=HttpRestConfig(enabled=True, host="127.0.0.1", port=9002),
        )
        assert cfg.effective_http_rest_listen() == ("10.0.0.2", 9001)

    def test_effective_http_rest_listen_http_only_config(self) -> None:
        """When HTTP is disabled, helper still returns http_rest host/port (unused)."""
        cfg = TransportConfig(
            websocket=WebSocketConfig(enabled=True, host="127.0.0.1", port=8765),
            http_rest=HttpRestConfig(enabled=False, host="127.0.0.1", port=9999),
        )
        assert cfg.effective_http_rest_listen() == ("127.0.0.1", 9999)


class TestWebSocketTransport:
    """Tests for WebSocket transport."""

    @pytest.fixture
    def config(self) -> WebSocketConfig:
        """Create test configuration."""
        return WebSocketConfig(enabled=True, host="127.0.0.1", port=18765)

    @pytest.mark.asyncio
    async def test_transport_properties(self, config: WebSocketConfig) -> None:
        """Transport properties are correct."""
        transport = WebSocketTransport(config)

        assert transport.transport_type == "websocket"
        assert transport.client_count == 0


class TestChannelManager:
    """Tests for channel manager."""

    @pytest.fixture
    def config(self) -> SootheDaemonConfig:
        """Create test configuration with WebSocket disabled (for error tests)."""
        return SootheDaemonConfig(
            transports=TransportConfig(websocket=WebSocketConfig(enabled=False))
        )

    @pytest.mark.asyncio
    async def test_manager_websocket_required(self, config: SootheDaemonConfig) -> None:
        """Manager fails when WebSocket is disabled."""
        from soothe_daemon.event import EventBus

        manager = ChannelManager(config, EventBus())
        manager.set_message_handler(lambda _client_id, _msg: None)

        with pytest.raises(RuntimeError, match="WebSocket channel is required"):
            await manager.start_all()

    @pytest.mark.asyncio
    async def test_manager_no_handler(self, config: SootheDaemonConfig) -> None:
        """Manager fails when no handler is set."""
        from soothe_daemon.event import EventBus

        manager = ChannelManager(config, EventBus())

        with pytest.raises(RuntimeError, match="Message handler not set"):
            await manager.start_all()

    @pytest.mark.asyncio
    async def test_manager_double_start(self) -> None:
        """Manager handles double start gracefully."""
        from soothe_daemon.event import EventBus

        config = SootheDaemonConfig(
            transports=TransportConfig(websocket=WebSocketConfig(enabled=True, port=18766))
        )

        manager = ChannelManager(config, EventBus())
        manager.set_message_handler(lambda _client_id, _msg: None)

        with patch.object(WebSocketChannel, "start", new_callable=AsyncMock):
            await manager.start_all()

            # Second start should log warning but not fail
            await manager.start_all()

        await manager.stop_all()

    def test_manager_properties(self) -> None:
        """Manager properties are correct."""
        from soothe_daemon.event import EventBus

        config = SootheDaemonConfig(transports=TransportConfig())
        manager = ChannelManager(config, EventBus())

        assert manager.channel_count == 0
        assert manager.client_count == 0
        assert manager.get_channel_info() == []


class TestTransportInterfaces:
    """Tests for transport abstract interfaces."""

    def test_transport_server_is_abstract(self) -> None:
        """TransportServer is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            TransportServer()  # type: ignore[abstract]

    def test_transport_client_is_abstract(self) -> None:
        """TransportClient is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            TransportClient()  # type: ignore[abstract]
