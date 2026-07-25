"""Tests for SootheRunner.cleanup closing SQLite aiosqlite connections."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.runner import SootheRunner


@pytest.mark.asyncio
async def test_cleanup_closes_aiosqlite_checkpointer_connection() -> None:
    """Standalone SQLite runners must close aiosqlite to allow process exit."""
    runner = object.__new__(SootheRunner)
    conn = AsyncMock()
    checkpointer = SimpleNamespace(conn=conn)
    graph = SimpleNamespace(checkpointer=checkpointer)
    runner._checkpointer_pool = "/tmp/test-checkpoints.db"
    runner._checkpointer = checkpointer
    runner._checkpointer_initialized = True
    runner._core_agent = SimpleNamespace(graph=graph)
    runner._sloop_shared_pool = object()
    runner._durability = None
    runner._memory = None

    await SootheRunner.cleanup(runner)

    conn.close.assert_awaited_once()
    assert runner._checkpointer is None
    assert runner._checkpointer_initialized is False
    assert graph.checkpointer is None
    assert runner._sloop_shared_pool is None


@pytest.mark.asyncio
async def test_cleanup_skips_shared_postgres_pool_close() -> None:
    """Shared Postgres checkpointer pools stay open until daemon shutdown."""
    runner = object.__new__(SootheRunner)
    pool = MagicMock()
    pool.close = AsyncMock()
    runner._checkpointer_pool = pool
    runner._checkpointer = None
    runner._checkpointer_initialized = True
    runner._core_agent = None
    runner._sloop_shared_pool = object()
    runner._durability = None
    runner._memory = None

    with pytest.MonkeyPatch.context() as mp:
        shared = MagicMock()
        shared.is_shared_pool = MagicMock(return_value=True)
        mp.setattr(
            "soothe.runner.resolver.shared_checkpointer_pool.SharedCheckpointerPool",
            shared,
        )
        await SootheRunner.cleanup(runner)

    pool.close.assert_not_awaited()
    assert runner._sloop_shared_pool is None
