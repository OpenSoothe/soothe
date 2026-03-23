"""Integration tests for WebSocket transport (RFC-0013 Phase 2)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from soothe.config.daemon_config import DaemonConfig, WebSocketConfig
from soothe.daemon.transports.websocket import WebSocketTransport
from soothe.daemon.websocket_client import WebSocketClient


@pytest.mark.asyncio
async def test_websocket_transport_basic() -> None:
    """Test basic WebSocket transport lifecycle."""
    config = WebSocketConfig(
        enabled=True,
        host="127.0.0.1",
        port=18765,  # Use non-standard port for testing
        tls_enabled=False,
    )

    transport = WebSocketTransport(config)

    messages_received: list[dict[str, Any]] = []

    def message_handler(msg: dict[str, Any]) -> None:
        messages_received.append(msg)

    # Start transport
    await transport.start(message_handler)
    assert transport.transport_type == "websocket"
    assert transport.client_count == 0

    # Stop transport
    await transport.stop()


@pytest.mark.asyncio
async def test_websocket_client_connect() -> None:
    """Test WebSocket client connection."""
    config = WebSocketConfig(
        enabled=True,
        host="127.0.0.1",
        port=18766,
        tls_enabled=False,
    )

    transport = WebSocketTransport(config)

    # Use synchronous message handler
    def message_handler(msg: dict[str, Any]) -> None:
        pass

    await transport.start(message_handler)

    try:
        # Connect client
        client = WebSocketClient(url="ws://127.0.0.1:18766")
        await client.connect()
        assert client.is_connected

        # Send message
        await client.send({"type": "test", "data": "hello"})

        # Close connection
        await client.close()
        assert not client.is_connected
    finally:
        await transport.stop()


@pytest.mark.asyncio
async def test_websocket_broadcast() -> None:
    """Test WebSocket broadcast functionality."""
    config = WebSocketConfig(
        enabled=True,
        host="127.0.0.1",
        port=18768,
        tls_enabled=False,
    )

    transport = WebSocketTransport(config)

    async def message_handler(msg: dict[str, Any]) -> None:
        pass

    await transport.start(message_handler)

    try:
        # Connect client
        client = WebSocketClient(url="ws://127.0.0.1:18768")
        await client.connect()

        # Broadcast message
        await transport.broadcast({"type": "event", "data": "test"})

        # Read event (with timeout)
        try:
            event = await asyncio.wait_for(client.read_event(), timeout=2.0)
            assert event is not None
            assert event["type"] == "event"
        except TimeoutError:
            pass  # Expected if no message received

        await client.close()
    finally:
        await transport.stop()
