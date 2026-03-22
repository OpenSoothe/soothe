"""Tests for transport abstraction layer (RFC-0013)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.config.daemon_config import DaemonConfig, TransportConfig, UnixSocketConfig
from soothe.daemon.protocol_v2 import (
    ERROR_INVALID_MESSAGE,
    ProtocolError,
    create_error_response,
    validate_message,
    validate_message_size,
)
from soothe.daemon.transport_manager import TransportManager
from soothe.daemon.transports.base import TransportClient, TransportServer
from soothe.daemon.transports.unix_socket import UnixSocketTransport


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
        assert validate_message_size(msg, max_size_bytes=1024)

    def test_validate_message_size_exceeds_limit(self) -> None:
        """Message exceeding size limit fails validation."""
        msg = {"type": "input", "text": "x" * 10000}
        assert not validate_message_size(msg, max_size_bytes=100)

    def test_create_error_response(self) -> None:
        """Error response is created correctly."""
        error_msg = create_error_response(ERROR_INVALID_MESSAGE, "Missing required field", {"field": "type"})
        assert error_msg["type"] == "error"
        assert error_msg["code"] == ERROR_INVALID_MESSAGE
        assert error_msg["message"] == "Missing required field"
        assert error_msg["details"]["field"] == "type"

    def test_protocol_error_to_dict(self) -> None:
        """ProtocolError converts to dict correctly."""
        error = ProtocolError("CODE", "message", {"key": "value"})
        error_dict = error.to_dict()
        assert error_dict["type"] == "error"
        assert error_dict["code"] == "CODE"
        assert error_dict["message"] == "message"
        assert error_dict["details"]["key"] == "value"


class TestUnixSocketTransport:
    """Tests for Unix socket transport."""

    @pytest.fixture
    def config(self) -> UnixSocketConfig:
        """Create test configuration."""
        return UnixSocketConfig(enabled=True, path="/tmp/test_soothe.sock")

    @pytest.mark.asyncio
    async def test_transport_start_disabled(self, config: UnixSocketConfig) -> None:
        """Disabled transport doesn't start."""
        config.enabled = False
        transport = UnixSocketTransport(config)

        # Should not raise an error
        await transport.start(lambda msg: None)

        assert transport.client_count == 0
        assert transport.transport_type == "unix_socket"

    @pytest.mark.asyncio
    async def test_transport_properties(self, config: UnixSocketConfig) -> None:
        """Transport properties are correct."""
        transport = UnixSocketTransport(config)

        assert transport.transport_type == "unix_socket"
        assert transport.client_count == 0


class TestTransportManager:
    """Tests for transport manager."""

    @pytest.fixture
    def config(self) -> DaemonConfig:
        """Create test configuration."""
        return DaemonConfig(transports=TransportConfig(unix_socket=UnixSocketConfig(enabled=False)))

    @pytest.mark.asyncio
    async def test_manager_no_transports(self, config: DaemonConfig) -> None:
        """Manager fails when no transports are enabled."""
        manager = TransportManager(config)
        manager.set_message_handler(lambda msg: None)

        with pytest.raises(RuntimeError, match="No transports enabled"):
            await manager.start_all()

    @pytest.mark.asyncio
    async def test_manager_no_handler(self, config: DaemonConfig) -> None:
        """Manager fails when no handler is set."""
        manager = TransportManager(config)

        with pytest.raises(RuntimeError, match="Message handler not set"):
            await manager.start_all()

    @pytest.mark.asyncio
    async def test_manager_double_start(self, config: DaemonConfig) -> None:
        """Manager handles double start gracefully."""
        config.transports.unix_socket.enabled = True
        config.transports.unix_socket.path = "/tmp/test_manager.sock"

        manager = TransportManager(config)
        manager.set_message_handler(lambda msg: None)

        # Mock transport to avoid actual socket creation
        with patch.object(UnixSocketTransport, "start", new_callable=AsyncMock):
            await manager.start_all()

            # Second start should log warning but not fail
            await manager.start_all()

        await manager.stop_all()

    def test_manager_properties(self, config: DaemonConfig) -> None:
        """Manager properties are correct."""
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


class TestMessageFlow:
    """Integration tests for message flow through transport layer."""

    @pytest.mark.asyncio
    async def test_message_handler_called(self) -> None:
        """Messages from transport are routed to handler."""
        config = DaemonConfig(
            transports=TransportConfig(unix_socket=UnixSocketConfig(enabled=True, path="/tmp/test_flow.sock"))
        )

        received_messages: list[dict[str, Any]] = []

        def message_handler(msg: dict[str, Any]) -> None:
            received_messages.append(msg)

        manager = TransportManager(config)
        manager.set_message_handler(message_handler)

        # Mock transport to simulate message
        with patch.object(UnixSocketTransport, "start", new_callable=AsyncMock):
            await manager.start_all()

            # Get the transport and simulate receiving a message
            if manager._transports:
                # Simulate calling the handler directly
                manager._message_handler({"type": "input", "text": "test"})

        await manager.stop_all()

        # Message should have been received
        assert len(received_messages) == 1
        assert received_messages[0]["type"] == "input"

    @pytest.mark.asyncio
    async def test_broadcast_to_all_transports(self) -> None:
        """Broadcast sends message to all transports."""
        config = DaemonConfig(
            transports=TransportConfig(unix_socket=UnixSocketConfig(enabled=True, path="/tmp/test_broadcast.sock"))
        )

        manager = TransportManager(config)
        manager.set_message_handler(lambda msg: None)

        # Mock transport
        with patch.object(UnixSocketTransport, "start", new_callable=AsyncMock):
            with patch.object(UnixSocketTransport, "broadcast", new_callable=AsyncMock) as mock_broadcast:
                await manager.start_all()

                # Broadcast a message
                await manager.broadcast({"type": "status", "state": "idle"})

                # Verify broadcast was called on transport
                mock_broadcast.assert_called_once()

        await manager.stop_all()
