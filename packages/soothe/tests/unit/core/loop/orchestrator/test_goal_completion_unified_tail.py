"""Tests for unified goal-completion tail persistence path."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from soothe.foundation.sloop.orchestrator.nodes.goal_completion import (
    _goal_completion_tail_persistence,
)


@pytest.mark.asyncio
async def test_unified_tail_uses_single_goal_boundary_persist() -> None:
    state_manager = Mock()
    state_manager._ensure_loop_writer = AsyncMock(return_value=object())
    state_manager.finalize_goal = AsyncMock()
    state_manager.persist_goal_boundary_durable = AsyncMock(
        return_value=Mock(ok=True, failures=[]),
    )

    ce = Mock()
    ce.persistence_snapshot = Mock(return_value=(Mock(), [{"role": "ai"}]))

    failures = await _goal_completion_tail_persistence(
        context_engine=ce,
        state_manager=state_manager,
        goal_record=Mock(goal_id="g1"),
        full_output="done",
        loop_state=Mock(),
        loop_id="loop-unified",
    )

    assert failures == []
    state_manager.finalize_goal.assert_awaited_once()
    assert state_manager.finalize_goal.await_args.kwargs.get("skip_persist") is True
    ce.save.assert_not_called()
    state_manager.persist_goal_boundary_durable.assert_awaited_once()


@pytest.mark.asyncio
async def test_sqlite_tail_uses_ce_save_and_flush() -> None:
    """SQLite (no persistence writer) still persists CE and checkpoint separately."""
    state_manager = Mock()
    state_manager._ensure_loop_writer = AsyncMock(return_value=None)
    state_manager.finalize_goal = AsyncMock()
    state_manager._checkpoint = Mock()
    state_manager.save = AsyncMock()
    state_manager.force_flush = AsyncMock()

    ce = Mock()
    ce.save = AsyncMock()

    failures = await _goal_completion_tail_persistence(
        context_engine=ce,
        state_manager=state_manager,
        goal_record=Mock(goal_id="g1"),
        full_output="done",
        loop_state=Mock(),
        loop_id="loop-legacy",
    )

    assert failures == []
    ce.save.assert_awaited_once()
    state_manager.save.assert_awaited_once()
    state_manager.force_flush.assert_awaited_once()
    state_manager.persist_goal_boundary_durable.assert_not_called()
