"""Tests for LoopPersistenceWriter coalescing and bounded release."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.persistence.loop_writer import (
    LoopPersistenceWriter,
    PersistWriteMode,
)
from soothe.foundation.sloop.state.checkpoint import StrangeLoopCheckpoint, ThreadHealthMetrics


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


@pytest.mark.asyncio
async def test_enqueue_coalesces_latest_checkpoint() -> None:
    shared_pool = MagicMock()
    writer = LoopPersistenceWriter(shared_pool=shared_pool, flush_interval=60.0)
    writer._write_checkpoint = AsyncMock()

    cp1 = _checkpoint("loop-a", status="running")
    cp2 = _checkpoint("loop-a", status="idle")

    await writer.enqueue_checkpoint("loop-a", cp1)
    await writer.enqueue_checkpoint("loop-a", cp2)

    assert writer._pending["loop-a"].checkpoint.status == "idle"
    await writer._flush_loop("loop-a", force_full=False)
    writer._write_checkpoint.assert_awaited_once()
    written = writer._write_checkpoint.await_args.args[0]
    assert written.status == "idle"


@pytest.mark.asyncio
async def test_durable_enqueue_sets_full_write_mode() -> None:
    shared_pool = MagicMock()
    writer = LoopPersistenceWriter(
        shared_pool=shared_pool,
        durable_flush_timeout=1.0,
    )
    writer._flush_loop = AsyncMock()

    cp = _checkpoint("loop-b")
    await writer.enqueue_checkpoint(
        "loop-b",
        cp,
        durable=True,
        write_mode=PersistWriteMode.FULL,
    )

    entry = writer._pending.get("loop-b")
    assert entry is not None
    assert entry.durable is True
    assert entry.write_mode == PersistWriteMode.FULL


@pytest.mark.asyncio
async def test_release_loop_bounded_on_hung_flush() -> None:
    shared_pool = MagicMock()
    writer = LoopPersistenceWriter(
        shared_pool=shared_pool,
        close_timeout_seconds=0.05,
    )

    async def _hang(*_args: object, **_kwargs: object) -> None:
        await asyncio.Event().wait()

    writer._flush_loop = _hang  # type: ignore[method-assign]
    writer._pending["loop-c"] = MagicMock(checkpoint=_checkpoint("loop-c"), durable=False)

    await writer.release_loop("loop-c", timeout=0.05)
    assert "loop-c" in writer._released_loops
