"""Tests for headless /cron slash-command handling."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.cli.execution.daemon import _run_headless_session_once


@pytest.mark.asyncio
async def test_headless_cron_slash_uses_command_client(monkeypatch) -> None:
    """Headless /cron submits via WebSocket command client and skips the agent loop."""
    cfg = MagicMock()
    mock_client = AsyncMock()
    mock_client.cron_add.return_value = {
        "job": {
            "id": "cron001",
            "description": "verify headless path",
            "next_run": datetime(2026, 6, 25, 12, 0, 0, tzinfo=UTC).isoformat(),
        }
    }

    monkeypatch.setattr(
        "soothe_cli.cli.execution.daemon.async_command_client_from_config",
        lambda _cfg: mock_client,
    )
    session_factory = MagicMock()
    monkeypatch.setattr(
        "soothe_cli.cli.execution.daemon.DaemonSession",
        session_factory,
    )

    exit_code, retry = await _run_headless_session_once(
        cfg,
        "/cron in 1 hour verify headless path",
    )

    assert exit_code == 0
    assert retry is False
    session_factory.assert_not_called()
    mock_client.cron_add.assert_called_once_with("in 1 hour verify headless path")


@pytest.mark.asyncio
async def test_headless_cron_slash_requires_text(monkeypatch) -> None:
    session_factory = MagicMock()
    monkeypatch.setattr(
        "soothe_cli.cli.execution.daemon.DaemonSession",
        session_factory,
    )

    exit_code, retry = await _run_headless_session_once(MagicMock(), "/cron")

    assert exit_code == 1
    assert retry is False
    session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_headless_cron_ws_failure(monkeypatch) -> None:
    mock_client = AsyncMock()
    mock_client.cron_add.side_effect = RuntimeError("WebSocket command failed")
    monkeypatch.setattr(
        "soothe_cli.cli.execution.daemon.async_command_client_from_config",
        lambda _cfg: mock_client,
    )

    exit_code, retry = await _run_headless_session_once(
        MagicMock(),
        "/cron in 1 hour fail",
    )

    assert exit_code == 1
    assert retry is False
