"""Process-wide singleton LangGraph checkpointer pool (thread_pool / daemon).

Each ``SootheRunner`` in the same process reuses this pool instead of creating
``max_size`` connections per request (which exhausts PgBouncer under concurrency).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from soothe_nano.persistence.postgres_pool_lifecycle import (
    apply_row_factory,
    close_async_pool,
    postgres_pool_timing_from_config,
    release_idle_pool_connections,
)
from soothe_nano.persistence.postgres_pool_registry import PostgresPoolRegistry
from soothe_nano.persistence.retry_utils import is_duplicate_schema_error

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)

_shared_checkpointer_pool: AsyncConnectionPool | None = None
_checkpointer_setup_done = False
_setup_waiter: threading.Event | None = None
_sync_lock = threading.Lock()


def _checkpointer_setup_lock_key() -> int:
    """Stable 63-bit advisory lock id for LangGraph checkpointer DDL."""
    digest = hashlib.sha256(b"langgraph_checkpoint_setup").digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


class SharedCheckpointerPool:
    """Singleton ``AsyncConnectionPool`` for LangGraph ``AsyncPostgresSaver``."""

    @classmethod
    def _register_pool(cls, pool: AsyncConnectionPool) -> None:
        """Bind the registry checkpoints pool to this shim (daemon pre-open)."""
        global _shared_checkpointer_pool

        with _sync_lock:
            _shared_checkpointer_pool = pool

    @classmethod
    def get_or_create_pool(cls, config: SootheConfig) -> AsyncConnectionPool | None:
        """Return the shared checkpoints pool (registry-backed when pre-opened)."""
        global _shared_checkpointer_pool

        if config.persistence.default_backend != "postgresql":
            return None
        if config.resolve_checkpointer_backend() != "postgresql":
            return None

        with _sync_lock:
            if _shared_checkpointer_pool is not None:
                return _shared_checkpointer_pool

            try:
                registry = PostgresPoolRegistry.get_instance(config)
                reg_pool = registry.try_get_pool("checkpoints")
                if reg_pool is not None:
                    _shared_checkpointer_pool = reg_pool
                    return reg_pool
            except RuntimeError:
                pass

            try:
                from psycopg_pool import AsyncConnectionPool
            except ImportError:
                logger.warning("psycopg-pool not installed; shared checkpointer unavailable")
                return None

            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: F401
            except ImportError:
                logger.warning(
                    "langgraph-checkpoint-postgres not installed; shared checkpointer unavailable"
                )
                return None

            from soothe_nano.persistence.postgres_provisioning import (
                ensure_postgres_databases,
            )

            ensure_postgres_databases(config)
            dsn = config.resolve_postgres_dsn_for_database("checkpoints")
            max_size = PostgresPoolRegistry.resolve_checkpoints_pool_size(config)
            timing = postgres_pool_timing_from_config(config, max_size=max_size)
            pool_kwargs: dict[str, Any] = {
                "max_size": max_size,
                "open": False,
                **timing,
            }
            pool = AsyncConnectionPool(dsn, **apply_row_factory(pool_kwargs))
            _shared_checkpointer_pool = pool
            logger.info(
                "Created singleton shared PostgreSQL checkpointer pool (max_size=%d)",
                max_size,
            )
            return pool

    @classmethod
    async def setup_checkpointer(
        cls,
        pool: AsyncConnectionPool,
        setup: Callable[[], Awaitable[None]],
    ) -> None:
        """Run LangGraph checkpointer ``setup()`` once under a PostgreSQL advisory lock.

        Concurrent ``SootheRunner`` instances share one pool and may call setup in
        parallel (lazy CoreAgent materialization, thread-pool workers). Without
        serialization, PostgreSQL raises ``UniqueViolation`` on checkpoint types.

        Args:
            pool: Open checkpointer connection pool.
            setup: Async callable that runs ``AsyncPostgresSaver.setup()``.
        """

        global _checkpointer_setup_done, _setup_waiter

        if _checkpointer_setup_done:
            return

        leader = False
        waiter: threading.Event | None = None
        with _sync_lock:
            if _checkpointer_setup_done:
                return
            if _setup_waiter is None:
                _setup_waiter = threading.Event()
                leader = True
            else:
                waiter = _setup_waiter

        if not leader:
            assert waiter is not None
            completed = await asyncio.to_thread(waiter.wait, 120.0)
            if not completed:
                logger.warning("Timed out waiting for shared checkpointer setup")
            return

        lock_key = _checkpointer_setup_lock_key()
        try:
            if _checkpointer_setup_done:
                return
            async with pool.connection() as conn:
                await conn.set_autocommit(True)
                async with conn.cursor() as cur:
                    await cur.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
                try:
                    if _checkpointer_setup_done:
                        return
                    try:
                        await setup()
                    except Exception as exc:
                        if not is_duplicate_schema_error(exc):
                            raise
                        logger.debug(
                            "Checkpointer schema already exists (concurrent setup): %s: %s",
                            type(exc).__name__,
                            exc,
                        )
                    _checkpointer_setup_done = True
                finally:
                    async with conn.cursor() as cur:
                        await cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
        finally:
            with _sync_lock:
                setup_event = _setup_waiter
                _setup_waiter = None
            if setup_event is not None:
                setup_event.set()

    @classmethod
    def is_shared_pool(cls, pool: Any) -> bool:
        """Return whether *pool* is the process singleton (must not be closed per request)."""
        return pool is not None and pool is _shared_checkpointer_pool

    @classmethod
    async def release_idle(cls) -> None:
        """Drop idle checkpointer connections (daemon periodic maintenance)."""
        await release_idle_pool_connections(_shared_checkpointer_pool, label="checkpointer")

    @classmethod
    async def close_shared_instance(cls) -> None:
        """Close the singleton at daemon shutdown (registry owns pool lifecycle)."""
        global _checkpointer_setup_done, _shared_checkpointer_pool

        with _sync_lock:
            _shared_checkpointer_pool = None
            _checkpointer_setup_done = False

    @classmethod
    async def reset_shared_instance(cls, config: SootheConfig) -> AsyncConnectionPool | None:
        """Reset the singleton pool after connection error.

        Closes the stale pool and creates a fresh one. Called when
        PostgreSQL restarts or connection is lost during checkpointer
        operations.

        Args:
            config: SootheConfig to create new pool with same settings.

        Returns:
            New pool instance, or None if not using PostgreSQL.
        """
        global _checkpointer_setup_done, _shared_checkpointer_pool

        with _sync_lock:
            pool_to_close = _shared_checkpointer_pool
            _shared_checkpointer_pool = None
            _checkpointer_setup_done = False

        await close_async_pool(pool_to_close, label="checkpointer")

        new_pool = cls.get_or_create_pool(config)
        if new_pool is not None:
            logger.info("Created fresh shared checkpointer pool after reset")
        return new_pool


__all__ = ["SharedCheckpointerPool"]
