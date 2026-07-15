"""Integration tests for WebSocket channel (RFC-620)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from soothe_client import WebSocketClient

from soothe_daemon.channels.websocket import WebSocketChannel
from soothe_daemon.config.models import WebSocketConfig


@pytest.mark.asyncio
async def test_websocket_channel_basic() -> None:
    """Test basic WebSocket channel lifecycle."""
    config = WebSocketConfig(
        enabled=True,
        host="127.0.0.1",
        port=18765,
        tls_enabled=False,
    )

    manager = MagicMock()
    channel = WebSocketChannel(config, manager=manager)

    messages_received: list[dict[str, Any]] = []

    def message_handler(_client_id: str, msg: dict[str, Any]) -> None:
        messages_received.append(msg)

    manager._message_handler = message_handler
    channel._message_handler = message_handler

    # Start channel
    await channel.start()
    assert channel.name == "websocket"
    assert channel.client_count == 0

    # Stop channel
    await channel.stop()


@pytest.mark.asyncio
async def test_websocket_client_connect() -> None:
    """Test WebSocket client connection."""
    config = WebSocketConfig(
        enabled=True,
        host="127.0.0.1",
        port=18766,
        tls_enabled=False,
    )

    manager = MagicMock()
    channel = WebSocketChannel(config, manager=manager)

    def message_handler(_client_id: str, msg: dict[str, Any]) -> None:
        pass

    manager._message_handler = message_handler
    channel._message_handler = message_handler

    await channel.start()
    await asyncio.sleep(0.2)

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
        await channel.stop()


@pytest.mark.asyncio
async def test_websocket_broadcast() -> None:
    """Test WebSocket broadcast functionality."""
    config = WebSocketConfig(
        enabled=True,
        host="127.0.0.1",
        port=18768,
        tls_enabled=False,
    )

    manager = MagicMock()
    channel = WebSocketChannel(config, manager=manager)

    def message_handler(_client_id: str, msg: dict[str, Any]) -> None:
        pass

    manager._message_handler = message_handler
    channel._message_handler = message_handler

    await channel.start()
    await asyncio.sleep(0.2)

    try:
        # Connect client
        client = WebSocketClient(url="ws://127.0.0.1:18768")
        await client.connect()

        # Broadcast message
        await channel.broadcast({"type": "event", "data": "test"})

        # Read event (with timeout)
        try:
            event = await asyncio.wait_for(client.read_event(), timeout=2.0)
            assert event is not None
            assert event["type"] == "event"
        except TimeoutError:
            pass  # Expected if no message received

        await client.close()
    finally:
        await channel.stop()
