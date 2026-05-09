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
