"""Tests for daemon WebSocket helper liveness checks."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from soothe_sdk.client import helpers


def test_daemon_status_indicates_live_prefers_running_key() -> None:
    """Explicit ``running`` wins when both fields are present."""
    assert helpers._daemon_status_indicates_live({"running": True, "port_live": False}) is True
    assert helpers._daemon_status_indicates_live({"running": False, "port_live": True}) is False


def test_daemon_status_indicates_live_missing_running_falls_back() -> None:
    """Missing ``running`` must not imply dead (regression: default False was wrong)."""
    assert helpers._daemon_status_indicates_live({"port_live": True}) is True
    assert helpers._daemon_status_indicates_live({"port_live": False}) is False
    assert helpers._daemon_status_indicates_live({}) is True


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


def test_daemon_status_indicates_live_readiness_state_unknown_falls_back() -> None:
    """Unknown readiness_state falls back to legacy check."""
    assert (
        helpers._daemon_status_indicates_live({"readiness_state": "unknown", "running": True})
        is True
    )
    assert (
        helpers._daemon_status_indicates_live({"readiness_state": "unknown", "running": False})
        is False
    )


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
            new=AsyncMock(return_value={"running": True}),
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
