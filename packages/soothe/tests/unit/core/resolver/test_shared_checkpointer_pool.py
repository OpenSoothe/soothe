"""Shared checkpointer pool singleton (per-process).

Host ``SharedCheckpointerPool`` is a thin subclass; singleton state lives in
``soothe_nano.resolve.shared_checkpointer_pool`` (IG-641).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.config import SootheConfig
from soothe.runner.resolver.shared_checkpointer_pool import SharedCheckpointerPool


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Isolate singleton between tests."""
    import soothe_nano.resolve.shared_checkpointer_pool as mod

    mod._shared_checkpointer_pool = None
    mod._checkpointer_setup_done = False
    mod._setup_waiter = None
    yield
    mod._shared_checkpointer_pool = None
    mod._checkpointer_setup_done = False
    mod._setup_waiter = None


@pytest.mark.integration
def test_get_or_create_returns_same_pool_instance() -> None:
    pytest.importorskip("psycopg_pool")
    pytest.importorskip("langgraph.checkpoint.postgres.aio")

    cfg = SootheConfig(
        persistence={
            "default_backend": "postgresql",
            "postgres_base_dsn": "postgresql://postgres:postgres@127.0.0.1:6432",
            "postgres": {"checkpoints_pool_size": 3},
        }
    )
    p1 = SharedCheckpointerPool.get_or_create_pool(cfg)
    p2 = SharedCheckpointerPool.get_or_create_pool(cfg)
    assert p1 is not None
    assert p1 is p2
    assert SharedCheckpointerPool.is_shared_pool(p1)


@pytest.mark.integration
def test_is_shared_pool_false_for_foreign_pool() -> None:
    pytest.importorskip("psycopg_pool")

    cfg = SootheConfig(
        persistence={
            "default_backend": "postgresql",
            "postgres_base_dsn": "postgresql://postgres:postgres@127.0.0.1:6432",
        }
    )
    pool = SharedCheckpointerPool.get_or_create_pool(cfg)
    assert pool is not None
    assert not SharedCheckpointerPool.is_shared_pool(object())


@pytest.mark.asyncio
async def test_setup_checkpointer_runs_once_after_first_success() -> None:
    import soothe_nano.resolve.shared_checkpointer_pool as mod

    setup = AsyncMock()
    pool = MagicMock()
    conn = MagicMock()
    conn.set_autocommit = AsyncMock()
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=False)
    conn.cursor = MagicMock(return_value=cursor)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    pool.connection = MagicMock(return_value=conn)

    await SharedCheckpointerPool.setup_checkpointer(pool, setup)
    await SharedCheckpointerPool.setup_checkpointer(pool, setup)

    setup.assert_awaited_once()
    assert mod._checkpointer_setup_done is True


def _mock_checkpointer_pool() -> tuple[MagicMock, AsyncMock]:
    setup = AsyncMock()
    pool = MagicMock()
    conn = MagicMock()
    conn.set_autocommit = AsyncMock()
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=False)
    conn.cursor = MagicMock(return_value=cursor)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    pool.connection = MagicMock(return_value=conn)
    return pool, setup


@pytest.mark.asyncio
async def test_setup_checkpointer_serializes_concurrent_waiters() -> None:
    import soothe_nano.resolve.shared_checkpointer_pool as mod

    pool, setup = _mock_checkpointer_pool()

    await asyncio.gather(
        SharedCheckpointerPool.setup_checkpointer(pool, setup),
        SharedCheckpointerPool.setup_checkpointer(pool, setup),
        SharedCheckpointerPool.setup_checkpointer(pool, setup),
    )

    setup.assert_awaited_once()
    assert mod._checkpointer_setup_done is True
    assert mod._setup_waiter is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reset_shared_instance_from_different_event_loop() -> None:
    pytest.importorskip("psycopg_pool")

    import soothe_nano.resolve.shared_checkpointer_pool as mod

    cfg = SootheConfig(
        persistence={
            "default_backend": "postgresql",
            "postgres_base_dsn": "postgresql://postgres:postgres@127.0.0.1:6432",
            "postgres": {"checkpoints_pool_size": 2},
        }
    )
    old_pool = MagicMock()
    old_pool.closed = False
    old_pool.close = AsyncMock(
        side_effect=ValueError(
            "The future belongs to a different loop than the one specified as the loop argument"
        )
    )
    mod._shared_checkpointer_pool = old_pool

    def _reset_from_other_loop() -> object:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(SharedCheckpointerPool.reset_shared_instance(cfg))
        finally:
            loop.close()

    second = await asyncio.to_thread(_reset_from_other_loop)
    assert second is not None
    assert second is not old_pool
    assert mod._shared_checkpointer_pool is second
