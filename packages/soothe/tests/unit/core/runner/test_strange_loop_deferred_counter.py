"""Tests for awaited loop message counter bump after goal completion."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.runner._runner_strange_loop import _increment_loop_ai_message_count


@pytest.mark.asyncio
async def test_increment_loop_ai_message_count_uses_shared_pool() -> None:
    pm = MagicMock()
    pm.increment_loop_message_count = AsyncMock()
    pm.close = AsyncMock()

    with patch(
        "soothe.sloop.checkpoints.manager.StrangeLoopCheckpointPersistenceManager.for_shared_checkpoint_pool",
        new=AsyncMock(return_value=pm),
    ) as factory:
        await _increment_loop_ai_message_count(MagicMock(), "loop-1")

    factory.assert_awaited_once()
    pm.increment_loop_message_count.assert_awaited_once_with("loop-1", ai=1)
    pm.close.assert_awaited_once()
