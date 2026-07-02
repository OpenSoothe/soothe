"""Integration: concurrent threads + shared PostgreSQL checkpointer pool.

Simulates thread_pool workers (each with its own asyncio loop) without LLM calls.
"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from soothe.config import SootheConfig
from soothe.runner import SootheRunner
from soothe.runner.resolver.shared_checkpointer_pool import SharedCheckpointerPool
from support_config import config_with_router_profile

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgresql]

_DEFAULT_BASE_DSN = "postgresql://postgres:postgres@127.0.0.1:6432"


async def _probe_config() -> SootheConfig:
    pytest.importorskip("psycopg_pool")
    base = os.getenv("SOOTHE_TEST_POSTGRES_BASE_DSN", _DEFAULT_BASE_DSN).rstrip("/")
    # Configure router based on available credentials (Anthropic, then OpenAI default)
    if os.getenv("ANTHROPIC_API_KEY"):
        router_config = {
            "default": "anthropic:claude-sonnet-4-5",
            "fast": "anthropic:claude-haiku-3-5",
        }
        memory_config = {"enabled": False}  # Anthropic doesn't support embeddings
    elif os.getenv("OPENAI_API_KEY"):
        router_config = {"default": "openai:gpt-4o-mini", "fast": "openai:gpt-4o-mini"}
        memory_config = {"enabled": False}
    else:
        router_config = {}
        memory_config = {"enabled": False}

    cfg = config_with_router_profile(
        router_config,
        persistence={
            "default_backend": "postgresql",
            "postgres_base_dsn": base,
            "checkpointer_pool_size": 3,
            "sloop_pool_size": 6,
            "postgres_pool_acquire_timeout_seconds": 5,
        },
        agent={"protocols": {"memory": memory_config}},
    )
    dsn = cfg.resolve_postgres_dsn_for_database("checkpoints")
    if "connect_timeout" not in dsn:
        dsn = f"{dsn}?connect_timeout=2"
    try:
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(dsn, min_size=1, max_size=1, open=False)
        await asyncio.wait_for(pool.open(), timeout=5.0)
        async with pool.connection():
            pass
        await pool.close()
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")
    return cfg


@pytest_asyncio.fixture
async def pg_agent_config() -> SootheConfig:
    return await _probe_config()


@pytest_asyncio.fixture(autouse=True)
async def _reset_singletons() -> None:
    import soothe.runner.resolver.shared_checkpointer_pool as cp_mod
    from soothe.foundation.sloop.state.persistence.shared_pool import SharedPostgreSQLPool

    await SharedPostgreSQLPool.close_shared_instance()
    await SharedCheckpointerPool.close_shared_instance()
    cp_mod._shared_checkpointer_pool = None
    cp_mod._checkpointer_setup_done = False
    cp_mod._setup_waiter = None
    yield
    await SharedPostgreSQLPool.close_shared_instance()
    await SharedCheckpointerPool.close_shared_instance()
    cp_mod._shared_checkpointer_pool = None
    cp_mod._checkpointer_setup_done = False
    cp_mod._setup_waiter = None


def _thread_worker_init_checkpointer(config: SootheConfig) -> object:
    """Same pattern as ``thread_runner._pool_worker`` (dedicated event loop per thread)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run() -> object:
        runner = SootheRunner(config)
        await runner._ensure_checkpointer_initialized()
        chk = runner._checkpointer_pool
        await runner.cleanup()
        return chk

    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_concurrent_thread_workers_share_checkpointer_pool(
    pg_agent_config: SootheConfig, requires_llm_api
) -> None:
    """Regression: parallel workers must not each create max_size=8 pools."""
    from soothe.foundation.sloop.state.persistence.shared_pool import SharedPostgreSQLPool

    await SharedPostgreSQLPool.get_shared_instance(pg_agent_config)
    cp = SharedCheckpointerPool.get_or_create_pool(pg_agent_config)
    assert cp is not None
    await cp.open()

    results = await asyncio.gather(
        asyncio.to_thread(_thread_worker_init_checkpointer, pg_agent_config),
        asyncio.to_thread(_thread_worker_init_checkpointer, pg_agent_config),
        asyncio.to_thread(_thread_worker_init_checkpointer, pg_agent_config),
    )

    assert results[0] is results[1] is results[2]
    assert SharedCheckpointerPool.is_shared_pool(results[0])

    async with asyncio.timeout(5.0):
        async with results[0].connection() as conn:
            await conn.execute("SELECT 1")
