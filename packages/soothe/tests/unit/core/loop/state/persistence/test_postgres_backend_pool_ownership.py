"""PostgreSQLPersistenceBackend pool ownership (IG-406 shared pool)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("psycopg_pool")

from soothe.foundation.loop.state.persistence.postgres_backend import (
    PostgreSQLPersistenceBackend,
)


def test_pool_size_zero_does_not_own_pool() -> None:
    """Shared mode must not claim ownership; per-loop close must not shut down daemon pool."""
    backend = PostgreSQLPersistenceBackend(dsn="postgresql://localhost/db", pool_size=0)
    assert backend._owns_pool is False


def test_pool_size_positive_owns_pool() -> None:
    backend = PostgreSQLPersistenceBackend(dsn="postgresql://localhost/db", pool_size=5)
    assert backend._owns_pool is True


@pytest.mark.asyncio
async def test_close_does_not_close_injected_shared_pool() -> None:
    """Regression: shared pool was closed when first StrangeLoopStateManager closed."""
    pool = MagicMock()
    pool.closed = False
    pool.close = AsyncMock()

    backend = PostgreSQLPersistenceBackend(dsn="postgresql://localhost/db", pool_size=0)
    backend._pool = pool

    await backend.close()

    pool.close.assert_not_called()


@pytest.mark.asyncio
async def test_close_closes_owned_pool() -> None:
    pool = MagicMock()
    pool.closed = False
    pool.close = AsyncMock()

    backend = PostgreSQLPersistenceBackend(dsn="postgresql://localhost/db", pool_size=10)
    backend._pool = pool

    await backend.close()

    pool.close.assert_awaited_once()
    assert backend._pool is None
