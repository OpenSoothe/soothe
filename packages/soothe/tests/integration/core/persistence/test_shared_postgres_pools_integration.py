"""Integration tests for shared PostgreSQL pools (IG-406 + checkpointer singleton).

Requires PostgreSQL at ``127.0.0.1:6432`` (docker-compose soothe-pgvector) or
``SOOTHE_TEST_POSTGRES_BASE_DSN``. Run with::

    pytest packages/soothe/tests/integration/core/persistence/test_shared_postgres_pools_integration.py --run-integration -v
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio

from soothe.config import SootheConfig
from soothe.foundation.loop.state.manager import AgentLoopStateManager
from soothe.foundation.loop.state.persistence.shared_pool import SharedPostgreSQLPool
from soothe.runner import SootheRunner
from soothe.runner.resolver.shared_checkpointer_pool import SharedCheckpointerPool

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgresql]

_DEFAULT_BASE_DSN = "postgresql://postgres:postgres@127.0.0.1:6432"


def _dsn_with_connect_timeout(dsn: str, seconds: int = 2) -> str:
    if "connect_timeout" in dsn:
        return dsn
    sep = "&" if "?" in dsn else "?"
    return f"{dsn}{sep}connect_timeout={seconds}"


def _postgres_integration_config() -> SootheConfig:
    base = os.getenv("SOOTHE_TEST_POSTGRES_BASE_DSN", _DEFAULT_BASE_DSN).rstrip("/")
    return SootheConfig(
        persistence={
            "default_backend": "postgresql",
            "postgres_base_dsn": base,
            "checkpointer_pool_size": 3,
            "agentloop_pool_size": 6,
            "postgres_pool_max_idle_seconds": 30,
            "postgres_pool_max_lifetime_seconds": 300,
            "postgres_pool_acquire_timeout_seconds": 5,
        }
    )


async def _probe_postgres() -> SootheConfig:
    pytest.importorskip("psycopg_pool")
    cfg = _postgres_integration_config()
    dsn = _dsn_with_connect_timeout(cfg.resolve_postgres_dsn_for_database("checkpoints"))
    try:
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(dsn, min_size=1, max_size=1, open=False)
        await asyncio.wait_for(pool.open(), timeout=5.0)
        async with asyncio.timeout(5.0):
            async with pool.connection() as conn:
                await conn.execute("SELECT 1")
        await pool.close()
    except Exception as exc:
        pytest.skip(f"PostgreSQL checkpoints DB not available: {exc}")
    return cfg


@pytest_asyncio.fixture
async def pg_config() -> SootheConfig:
    """Config with live PostgreSQL checkpoints DB."""
    return await _probe_postgres()


@pytest_asyncio.fixture(autouse=True)
async def _reset_pool_singletons() -> None:
    """Isolate singleton state between integration tests."""
    import soothe.foundation.loop.state.persistence.shared_pool as agent_mod
    import soothe.runner.resolver.shared_checkpointer_pool as cp_mod

    await SharedPostgreSQLPool.close_shared_instance()
    await SharedCheckpointerPool.close_shared_instance()
    agent_mod._shared_pool = None
    cp_mod._shared_checkpointer_pool = None
    yield
    await SharedPostgreSQLPool.close_shared_instance()
    await SharedCheckpointerPool.close_shared_instance()
    agent_mod._shared_pool = None
    cp_mod._shared_checkpointer_pool = None


@pytest.mark.asyncio
async def test_shared_checkpointer_pool_singleton_with_real_db(pg_config: SootheConfig) -> None:
    """Two resolve paths must return the same openable pool."""
    p1 = SharedCheckpointerPool.get_or_create_pool(pg_config)
    p2 = SharedCheckpointerPool.get_or_create_pool(pg_config)
    assert p1 is not None and p1 is p2
    await asyncio.wait_for(p1.open(), timeout=5.0)
    async with asyncio.timeout(5.0):
        async with p1.connection() as conn:
            await conn.execute("SELECT 1")


@pytest.mark.asyncio
async def test_sequential_runner_cleanup_preserves_shared_checkpointer_pool(
    pg_config: SootheConfig,
) -> None:
    """Regression: per-request pool close caused PoolTimeout under thread_pool load."""
    pools: list[object] = []
    for _ in range(4):
        runner = SootheRunner(pg_config)
        assert runner._checkpointer_pool is not None
        pools.append(runner._checkpointer_pool)
        await runner._ensure_checkpointer_initialized()
        await runner.cleanup()

    assert pools[0] is pools[1] is pools[2] is pools[3]
    assert SharedCheckpointerPool.is_shared_pool(pools[0])

    pool = pools[0]
    async with asyncio.timeout(5.0):
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")


@pytest.mark.asyncio
async def test_shared_agentloop_pool_parallel_load(pg_config: SootheConfig) -> None:
    """Concurrent checkpoint reads must not exhaust the shared AgentLoop pool."""
    shared = await SharedPostgreSQLPool.get_shared_instance(pg_config)
    assert shared is not None
    loop_id = f"test-pool-{uuid.uuid4().hex}"
    thread_id = str(uuid.uuid4())

    manager = AgentLoopStateManager(
        loop_id,
        config=pg_config,
        shared_pool=shared,
    )
    await manager.initialize(thread_id, max_iterations=3)

    async def _load_once() -> bool:
        mgr = AgentLoopStateManager(
            loop_id,
            config=pg_config,
            shared_pool=shared,
        )
        cp = await mgr.load()
        return cp is not None

    results = await asyncio.gather(*[_load_once() for _ in range(6)])
    assert all(results)


@pytest.mark.asyncio
async def test_release_idle_keeps_pools_acquiring_connections(pg_config: SootheConfig) -> None:
    """Daemon maintenance path must not break checkout after idle release."""
    cp_pool = SharedCheckpointerPool.get_or_create_pool(pg_config)
    agent_shared = await SharedPostgreSQLPool.get_shared_instance(pg_config)
    assert cp_pool is not None and agent_shared is not None

    await cp_pool.open()
    await SharedCheckpointerPool.release_idle()
    await SharedPostgreSQLPool.release_idle_shared()

    async with asyncio.timeout(5.0):
        async with cp_pool.connection() as conn:
            await conn.execute("SELECT 1")
        agent_pool = agent_shared.get_pool()
        assert agent_pool is not None
        async with agent_pool.connection() as conn:
            await conn.execute("SELECT 1")


@pytest.mark.asyncio
async def test_close_shared_instances_allow_reopen(pg_config: SootheConfig) -> None:
    """Shutdown close must allow a fresh singleton on next get."""
    first = SharedCheckpointerPool.get_or_create_pool(pg_config)
    assert first is not None
    await first.open()
    await SharedCheckpointerPool.close_shared_instance()

    second = SharedCheckpointerPool.get_or_create_pool(pg_config)
    assert second is not None
    assert second is not first
    await asyncio.wait_for(second.open(), timeout=5.0)
