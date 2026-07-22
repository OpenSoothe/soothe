"""Tests for LoopPersistenceWriter cross-event-loop submit bridge (IG-571)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.persistence.loop_writer import (
    LoopPersistenceWriter,
    PersistWriteMode,
)
from soothe.sloop.state.checkpoint import StrangeLoopCheckpoint, ThreadHealthMetrics


def _checkpoint(loop_id: str, *, status: str = "running") -> StrangeLoopCheckpoint:
    now = datetime.now(UTC)
    return StrangeLoopCheckpoint(
        loop_id=loop_id,
        current_thread_id=loop_id,
        status=status,
        current_goal_index=0,
        thread_health_metrics=ThreadHealthMetrics(
            thread_id=loop_id,
            last_updated=now,
        ),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture(autouse=True)
def _reset_writer_singleton() -> None:
    import soothe.persistence.loop_writer as mod

    mod._writer_singleton = None
    LoopPersistenceWriter._bound_loop = None
    yield
    mod._writer_singleton = None
    LoopPersistenceWriter._bound_loop = None


@pytest.mark.asyncio
async def test_submit_enqueue_from_secondary_event_loop() -> None:
    """Worker-thread loop must enqueue via main-loop bridge without cross-loop lock errors."""
    main_loop = asyncio.get_running_loop()
    LoopPersistenceWriter.bind_main_loop(main_loop)

    writer = LoopPersistenceWriter(shared_pool=MagicMock(), flush_interval=60.0)
    writer._flush_loop = AsyncMock()

    cp = _checkpoint("loop-bridge")

    def _run_on_secondary() -> None:
        secondary = asyncio.new_event_loop()
        asyncio.set_event_loop(secondary)
        try:
            secondary.run_until_complete(
                writer.submit_enqueue("loop-bridge", cp, write_mode=PersistWriteMode.INDEX_ONLY)
            )
        finally:
            secondary.close()

    await asyncio.to_thread(_run_on_secondary)

    assert writer._pending["loop-bridge"].checkpoint is cp


@pytest.mark.asyncio
async def test_force_flush_degraded_does_not_bypass_writer() -> None:
    """PostgreSQL path uses writer result only; no direct backend save on failure."""
    from soothe.sloop.state.sloop_manager import StrangeLoopStateManager

    manager = StrangeLoopStateManager(loop_id="loop-degraded", config=MagicMock())
    manager._backend_type = "postgresql"
    manager._config = MagicMock()
    manager._last_save_checkpoint = _checkpoint("loop-degraded")

    mock_writer = MagicMock()
    mock_writer.submit_flush_durable = AsyncMock(
        return_value=MagicMock(ok=False, failures=["durable_flush:TimeoutError"])
    )
    manager._loop_writer = mock_writer
    manager._do_save_checkpoint = AsyncMock()

    await manager.force_flush(timeout=1.0)

    mock_writer.submit_flush_durable.assert_awaited_once()
    manager._do_save_checkpoint.assert_not_awaited()
