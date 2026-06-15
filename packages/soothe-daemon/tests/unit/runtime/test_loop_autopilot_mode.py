"""Tests for per-loop autopilot mode helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from soothe_daemon.runtime.loop_autopilot_mode import (
    config_default_loop_mode,
    ensure_loop_autopilot_mode,
    get_loop_autopilot_mode,
    set_loop_autopilot_mode,
)


def _config(*, enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(agent=SimpleNamespace(autonomous=SimpleNamespace(enabled=enabled)))


class _Daemon:
    def __init__(self, *, enabled: bool, metadata: dict[str, Any] | None = None) -> None:
        self._config = _config(enabled=enabled)
        self._loop_autopilot_modes: dict[str, str] = {}
        self._persistence_manager = SimpleNamespace(
            get_loop_metadata=AsyncMock(return_value=metadata),
            update_loop_metadata=AsyncMock(),
        )
        self._broadcast = AsyncMock()


@pytest.mark.asyncio
async def test_config_default_loop_mode() -> None:
    assert config_default_loop_mode(_config(enabled=False)) == "solo"
    assert config_default_loop_mode(_config(enabled=True)) == "autopilot"


@pytest.mark.asyncio
async def test_ensure_persists_config_default_when_missing() -> None:
    daemon = _Daemon(enabled=True, metadata={"loop_id": "loop-1"})
    mode = await ensure_loop_autopilot_mode(daemon, "loop-1")
    assert mode == "autopilot"
    daemon._persistence_manager.update_loop_metadata.assert_awaited_once_with(
        "loop-1", autopilot_mode="autopilot"
    )


@pytest.mark.asyncio
async def test_get_respects_persisted_metadata() -> None:
    daemon = _Daemon(enabled=True, metadata={"autopilot_mode": "solo"})
    assert await get_loop_autopilot_mode(daemon, "loop-1") == "solo"


@pytest.mark.asyncio
async def test_set_loop_autopilot_mode_broadcasts() -> None:
    daemon = _Daemon(enabled=True, metadata={"autopilot_mode": "autopilot"})
    mode = await set_loop_autopilot_mode(daemon, "loop-1", "solo")
    assert mode == "solo"
    daemon._broadcast.assert_awaited_once()
    payload = daemon._broadcast.await_args.args[0]
    assert payload["type"] == "autopilot_mode_changed"
    assert payload["mode"] == "solo"
    assert payload["previous_mode"] == "autopilot"
