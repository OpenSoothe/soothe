"""Tests for /clear cancelling in-flight queries (IG-533 §1.1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_daemon.server import commands


@pytest.mark.asyncio
async def test_cmd_clear_cancels_active_query_before_reinitialize() -> None:
    handler = MagicMock()
    handler._has_active_queries = MagicMock(return_value=True)
    handler._query_engine = AsyncMock()
    handler._runner = MagicMock(state_manager=AsyncMock())
    handler._runner.state_manager.archive_and_finalize = AsyncMock(
        return_value={"goal_count": 1, "goals_completed": 1, "archived_at": "now"}
    )
    handler._runner.state_manager.reinitialize_for_clear = AsyncMock(
        return_value=("new-loop", "new-checkpoint")
    )
    handler._thread_registry = MagicMock()
    handler._broadcast = AsyncMock()

    await commands._cmd_clear(
        handler,
        checkpoint_thread_id="ckpt-1",
        params={},
        loop_id="old-loop",
    )

    handler._query_engine.cancel_loop.assert_awaited_once_with("old-loop")
    handler._runner.state_manager.archive_and_finalize.assert_awaited_once()
