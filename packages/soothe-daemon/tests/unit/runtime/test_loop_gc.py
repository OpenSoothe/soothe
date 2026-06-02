"""Unit tests for ephemeral loop GC helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_daemon.runtime.loop_gc import purge_loop_execution_data


@pytest.mark.asyncio
async def test_purge_skips_running_loop() -> None:
    daemon = MagicMock()
    metadata = {"status": "running", "thread_ids": []}
    ok = await purge_loop_execution_data(daemon, "loop-1", metadata)
    assert ok is False
    daemon._query_engine.cancel_loop.assert_not_called()


@pytest.mark.asyncio
async def test_purge_ephemeral_loop_calls_cleanup() -> None:
    daemon = MagicMock()
    daemon._query_engine.cancel_loop = AsyncMock()
    daemon._session_manager._sessions = {}
    daemon._loop_input_dispatcher.cleanup_loop = AsyncMock()
    daemon._thread_registry.cleanup_loop.return_value = []
    daemon._runner = None
    daemon._persistence_manager.purge_loop_execution_data = AsyncMock()

    metadata: dict[str, Any] = {
        "status": "created",
        "thread_ids": ["thr-1"],
        "current_thread_id": "thr-1",
    }
    ok = await purge_loop_execution_data(daemon, "loop-ephem", metadata)
    assert ok is True
    daemon._persistence_manager.purge_loop_execution_data.assert_awaited_once_with("loop-ephem")
