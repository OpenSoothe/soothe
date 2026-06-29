"""Tests for daemon WebSocket helper liveness checks."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from soothe_sdk.client import helpers


def test_daemon_status_indicates_live_readiness_state_ready() -> None:
    """Daemon with readiness_state 'ready' is live."""
    assert (
        helpers._daemon_status_indicates_live({"readiness_state": "ready", "running": True}) is True
    )
    assert (
        helpers._daemon_status_indicates_live({"readiness_state": "ready", "running": False})
        is True
    )


def test_daemon_status_indicates_live_readiness_state_transitional() -> None:
    """Transitional states (starting, warming) indicate daemon not ready."""
    assert (
        helpers._daemon_status_indicates_live({"readiness_state": "starting", "running": True})
        is False
    )
    assert (
        helpers._daemon_status_indicates_live({"readiness_state": "warming", "running": True})
        is False
    )
    assert (
        helpers._daemon_status_indicates_live({"readiness_state": "starting", "port_live": True})
        is False
    )


def test_daemon_status_indicates_live_readiness_state_terminal_error() -> None:
    """Terminal error states indicate daemon not live."""
    assert (
        helpers._daemon_status_indicates_live({"readiness_state": "error", "running": True})
        is False
    )
    assert (
        helpers._daemon_status_indicates_live({"readiness_state": "degraded", "running": True})
        is False
    )
    assert (
        helpers._daemon_status_indicates_live({"readiness_state": "stopped", "running": True})
        is False
    )


def test_daemon_status_indicates_live_missing_readiness_state_is_not_live() -> None:
    """Without readiness_state the daemon is not considered live (clear cut)."""
    assert helpers._daemon_status_indicates_live({"running": True, "port_live": False}) is False
    assert helpers._daemon_status_indicates_live({"port_live": True}) is False
    assert helpers._daemon_status_indicates_live({}) is False


@pytest.mark.asyncio
async def test_check_daemon_status_performs_handshake() -> None:
    """check_daemon_status must handshake before daemon_status RPC (RFC-450 §8.2)."""
    mock_client = AsyncMock()
    mock_client._handshake_complete = False
    mock_client.request_connection_init = AsyncMock()
    mock_client.wait_for_connection_ack = AsyncMock()
    mock_client.fetch_daemon_status = AsyncMock(return_value={"readiness_state": "ready"})

    result = await helpers.check_daemon_status(mock_client, timeout=3.0)

    mock_client.request_connection_init.assert_awaited_once()
    mock_client.wait_for_connection_ack.assert_awaited_once_with(ack_timeout_s=3.0)
    mock_client.fetch_daemon_status.assert_awaited_once_with(timeout=3.0, min_interval_s=1.0)
    assert result["readiness_state"] == "ready"


@pytest.mark.asyncio
async def test_check_daemon_status_skips_handshake_when_complete() -> None:
    """An already-handshaked client should not repeat connection_init."""
    mock_client = AsyncMock()
    mock_client._handshake_complete = True
    mock_client.request_connection_init = AsyncMock()
    mock_client.wait_for_connection_ack = AsyncMock()
    mock_client.fetch_daemon_status = AsyncMock(return_value={"readiness_state": "ready"})

    await helpers.check_daemon_status(mock_client, timeout=2.0)

    mock_client.request_connection_init.assert_not_awaited()
    mock_client.wait_for_connection_ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_is_daemon_live_retries_on_transient_failure() -> None:
    """Second attempt succeeds after one connect failure."""
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock(side_effect=[ConnectionError("refused"), None])
    mock_client.close = AsyncMock()

    with (
        patch.object(helpers, "WebSocketClient", return_value=mock_client),
        patch.object(
            helpers,
            "check_daemon_status",
            new=AsyncMock(return_value={"readiness_state": "ready"}),
        ),
    ):
        assert await helpers.is_daemon_live("ws://127.0.0.1:9", timeout=1.0) is True

    assert mock_client.connect.await_count == 2


@pytest.mark.asyncio
async def test_is_daemon_live_wait_for_ready_returns_immediately_when_ready() -> None:
    """When daemon is already ready, wait_for_ready returns immediately."""
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.close = AsyncMock()

    with (
        patch.object(helpers, "WebSocketClient", return_value=mock_client),
        patch.object(
            helpers,
            "check_daemon_status",
            new=AsyncMock(return_value={"readiness_state": "ready", "running": True}),
        ),
    ):
        result = await helpers.is_daemon_live(
            "ws://127.0.0.1:9", timeout=1.0, wait_for_ready=True, ready_timeout=5.0
        )
        assert result is True

    # Should only connect once since daemon was immediately ready
    assert mock_client.connect.await_count == 1


@pytest.mark.asyncio
async def test_is_daemon_live_wait_for_ready_polls_during_warming() -> None:
    """When daemon is warming, wait_for_ready polls until ready or timeout."""
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.close = AsyncMock()

    # First check: warming, second check: ready
    status_responses = [
        {"readiness_state": "warming", "running": True},
        {"readiness_state": "ready", "running": True},
    ]

    with (
        patch.object(helpers, "WebSocketClient", return_value=mock_client),
        patch.object(
            helpers,
            "check_daemon_status",
            new=AsyncMock(side_effect=status_responses),
        ),
    ):
        result = await helpers.is_daemon_live(
            "ws://127.0.0.1:9", timeout=1.0, wait_for_ready=True, ready_timeout=5.0
        )
        assert result is True

    # Should connect multiple times (warming -> ready)
    assert mock_client.connect.await_count >= 2


@pytest.mark.asyncio
async def test_is_daemon_live_wait_for_ready_timeout_on_warming() -> None:
    """When daemon stays in warming, wait_for_ready returns False after timeout."""
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.close = AsyncMock()

    # Always return warming state
    with (
        patch.object(helpers, "WebSocketClient", return_value=mock_client),
        patch.object(
            helpers,
            "check_daemon_status",
            new=AsyncMock(return_value={"readiness_state": "warming", "running": True}),
        ),
    ):
        result = await helpers.is_daemon_live(
            "ws://127.0.0.1:9", timeout=0.5, wait_for_ready=True, ready_timeout=1.0
        )
        assert result is False
