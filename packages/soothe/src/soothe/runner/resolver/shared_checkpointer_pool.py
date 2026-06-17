"""Process-wide singleton LangGraph checkpointer pool (thread_pool / daemon).

Each ``SootheRunner`` in the same process reuses this pool instead of creating
``max_size`` connections per request (which exhausts PgBouncer under concurrency).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Any

from soothe.foundation.persistence.postgres_pool_lifecycle import (
    apply_row_factory,
    close_async_pool,
    postgres_pool_timing_from_config,
    release_idle_pool_connections,
)

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_shared_checkpointer_pool: AsyncConnectionPool | None = None
_sync_lock = threading.Lock()
_async_lock = asyncio.Lock()


class SharedCheckpointerPool:
    """Singleton ``AsyncConnectionPool`` for LangGraph ``AsyncPostgresSaver``."""

    @classmethod
    def get_or_create_pool(cls, config: SootheConfig) -> AsyncConnectionPool | None:
        """Return the shared pool (``open=False`` until ``SootheRunner`` initializes it)."""
        global _shared_checkpointer_pool

        if config.persistence.default_backend != "postgresql":
            return None
        if config.resolve_checkpointer_backend() != "postgresql":
            return None

        with _sync_lock:
            if _shared_checkpointer_pool is not None:
                return _shared_checkpointer_pool

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

            dsn = config.resolve_postgres_dsn_for_database("checkpoints")
            max_size = config.persistence.checkpointer_pool_size
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
    def is_shared_pool(cls, pool: Any) -> bool:
        """Return whether *pool* is the process singleton (must not be closed per request)."""
        return pool is not None and pool is _shared_checkpointer_pool

    @classmethod
    async def release_idle(cls) -> None:
        """Drop idle checkpointer connections (daemon periodic maintenance)."""
        await release_idle_pool_connections(_shared_checkpointer_pool, label="checkpointer")

    @classmethod
    async def close_shared_instance(cls) -> None:
        """Close the singleton at daemon shutdown."""
        global _shared_checkpointer_pool

        async with _async_lock:
            await close_async_pool(_shared_checkpointer_pool, label="checkpointer")
            _shared_checkpointer_pool = None

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
        global _shared_checkpointer_pool

        async with _async_lock:
            # Close stale pool
            if _shared_checkpointer_pool is not None:
                try:
                    await _shared_checkpointer_pool.close()
                    logger.info("Closed stale shared checkpointer pool for reset")
                except Exception:
                    logger.debug(
                        "Error closing stale checkpointer pool during reset", exc_info=True
                    )
                _shared_checkpointer_pool = None

            # Create fresh pool
            new_pool = cls.get_or_create_pool(config)
            if new_pool is not None:
                logger.info("Created fresh shared checkpointer pool after reset")
            return new_pool


__all__ = ["SharedCheckpointerPool"]
