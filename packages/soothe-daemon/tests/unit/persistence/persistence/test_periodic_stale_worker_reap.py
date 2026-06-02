"""Periodic stale worker reap asyncio helper."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from soothe_daemon.persistence.process_cleanup import periodic_stale_worker_reap


@pytest.mark.asyncio
async def test_periodic_stale_worker_reap_runs_once_via_to_thread() -> None:
    state = {"running": True}

    def is_running() -> bool:
        return state["running"]

    async def stop_after_reap(*_args: object, **_kwargs: object) -> int:
        state["running"] = False
        return 0

    with (
        patch(
            "soothe_daemon.persistence.process_cleanup.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        patch(
            "soothe_daemon.persistence.process_cleanup.asyncio.to_thread",
            side_effect=stop_after_reap,
        ) as mock_to_thread,
    ):
        await periodic_stale_worker_reap(
            is_running=is_running,
            interval_s=60,
            daemon_pid=42,
        )

    mock_to_thread.assert_awaited_once()
    call_kwargs = mock_to_thread.await_args.kwargs
    assert call_kwargs["daemon_pid"] == 42
