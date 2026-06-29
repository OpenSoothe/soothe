"""Tests for transport/channel abstraction layer (RFC-0013, RFC-620)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe_daemon.channel_manager import ChannelManager
from soothe_daemon.channels.websocket import WebSocketChannel
from soothe_daemon.config import SootheDaemonConfig
from soothe_daemon.config.models import TransportConfig, WebSocketConfig
from soothe_daemon.protocol import (
    ErrorCode,
    build_error_response,
    validate_message,
    validate_message_size,
)


class TestProtocolV2:
    """Tests for protocol_v2 message validation.

    Legacy global "input" message type was removed in favor of loop_input.
    """

    def test_validate_command_message_valid(self) -> None:
        """Valid slash_command notification passes validation."""
        msg = {
            "proto": "1",
            "type": "notification",
            "method": "slash_command",
            "params": {"cmd": "/help"},
        }
        errors = validate_message(msg)
        assert errors == []

    def test_validate_command_message_missing_cmd(self) -> None:
        """slash_command notification missing cmd fails validation."""
        msg = {"proto": "1", "type": "notification", "method": "slash_command", "params": {}}
        errors = validate_message(msg)
        assert len(errors) == 1
        assert "cmd" in errors[0]

    def test_validate_resume_thread_message_rejected(self) -> None:
        """resume_thread is not a known protocol-1 type — rejected (RFC-450 §6.3)."""
        msg = {"type": "resume_thread", "thread_id": "abc123"}
        errors = validate_message(msg)
        assert len(errors) == 1
        assert "Unknown message type" in errors[0]

    def test_validate_auth_message_valid(self) -> None:
        """Valid auth request passes validation."""
        msg = {
            "proto": "1",
            "type": "request",
            "method": "auth",
            "params": {"access_key": "sk_live_abc123"},
            "id": "r1",
        }
        errors = validate_message(msg)
        assert errors == []

    def test_validate_unknown_message_type_rejected(self) -> None:
        """Unknown message types are rejected per RFC-450 §6.3."""
        msg = {"type": "future_message_type", "data": "value"}
        errors = validate_message(msg)
        assert len(errors) == 1
        assert "Unknown message type" in errors[0]

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

    def test_build_error_response(self) -> None:
        """Error response is created correctly (numeric envelope)."""
        error_dict = build_error_response(
            ErrorCode.INVALID_REQUEST,
            "Test error message",
            request_id="r-err",
            data={"key": "value"},
        )

        assert error_dict["proto"] == "1"
        assert error_dict["type"] == "error"
        assert error_dict["error"]["code"] == -32600
        assert error_dict["error"]["message"] == "Test error message"
        assert error_dict["error"]["data"]["key"] == "value"
        assert error_dict["id"] == "r-err"


class TestTransportConfig:
    """Transport configuration helpers."""

    def test_websocket_enabled_by_default(self) -> None:
        """Fresh daemon config enables WebSocket without explicit YAML."""
        assert WebSocketConfig().enabled is True
        assert TransportConfig().websocket.enabled is True
        assert SootheDaemonConfig().transports.websocket.enabled is True


class TestWebSocketChannel:
    """Tests for WebSocket channel."""

    @pytest.fixture
    def config(self) -> WebSocketConfig:
        """Create test configuration."""
        return WebSocketConfig(enabled=True, host="127.0.0.1", port=18765)

    @pytest.mark.asyncio
    async def test_channel_properties(self, config: WebSocketConfig) -> None:
        """Channel properties are correct."""
        manager = MagicMock()
        channel = WebSocketChannel(config, manager=manager)

        assert channel.name == "websocket"
        assert channel.client_count == 0


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
