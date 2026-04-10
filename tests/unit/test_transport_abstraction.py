"""Tests for transport abstraction layer (RFC-0013)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from soothe.config.daemon_config import DaemonConfig, TransportConfig, WebSocketConfig
from soothe.daemon.protocol_v2 import (
    ERROR_INVALID_MESSAGE,
    create_error_response,
    validate_message,
    validate_message_size,
)
from soothe.daemon.transport_manager import TransportManager
from soothe.daemon.transports.base import TransportClient, TransportServer
from soothe.daemon.transports.websocket import WebSocketTransport


class TestProtocolV2:
    """Tests for protocol_v2 message validation."""

    def test_validate_input_message_valid(self) -> None:
        """Valid input message passes validation."""
        msg = {"type": "input", "text": "hello"}
        errors = validate_message(msg)
        assert errors == []

    def test_validate_input_message_missing_text(self) -> None:
        """Input message missing text field fails validation."""
        msg = {"type": "input"}
        errors = validate_message(msg)
        assert len(errors) == 1
        assert "text" in errors[0]

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
        msg = {"type": "input", "text": "hello" * 100}
        is_valid = validate_message_size(msg)
        assert is_valid is True

    def test_validate_message_size_exceeds_limit(self) -> None:
        """Message exceeding size limit fails validation."""
        msg = {"type": "input", "text": "x" * (11 * 1024 * 1024)}  # 11MB
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


class TestTransportManager:
    """Tests for transport manager."""

    @pytest.fixture
    def config(self) -> DaemonConfig:
        """Create test configuration with WebSocket disabled (for error tests)."""
        return DaemonConfig(transports=TransportConfig(websocket=WebSocketConfig(enabled=False)))

    @pytest.mark.asyncio
    async def test_manager_websocket_required(self, config: DaemonConfig) -> None:
        """Manager fails when WebSocket is disabled."""
        manager = TransportManager(config)
        manager.set_message_handler(lambda msg: None)

        with pytest.raises(RuntimeError, match="WebSocket transport is required"):
            await manager.start_all()

    @pytest.mark.asyncio
    async def test_manager_no_handler(self, config: DaemonConfig) -> None:
        """Manager fails when no handler is set."""
        manager = TransportManager(config)

        with pytest.raises(RuntimeError, match="Message handler not set"):
            await manager.start_all()

    @pytest.mark.asyncio
    async def test_manager_double_start(self) -> None:
        """Manager handles double start gracefully."""
        config = DaemonConfig(transports=TransportConfig(websocket=WebSocketConfig(enabled=True, port=18766)))

        manager = TransportManager(config)
        manager.set_message_handler(lambda msg: None)

        # Mock transport to avoid actual socket creation
        with patch.object(WebSocketTransport, "start", new_callable=AsyncMock):
            await manager.start_all()

            # Second start should log warning but not fail
            await manager.start_all()

        await manager.stop_all()

    def test_manager_properties(self) -> None:
        """Manager properties are correct."""
        config = DaemonConfig(transports=TransportConfig())
        manager = TransportManager(config)

        assert manager.transport_count == 0
        assert manager.client_count == 0
        assert manager.get_transport_info() == []


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
