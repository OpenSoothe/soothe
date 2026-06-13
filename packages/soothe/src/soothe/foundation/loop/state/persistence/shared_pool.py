"""Shared PostgreSQL connection pool for StrangeLoop persistence (IG-406).

Provides a singleton pool at daemon level for high-concurrency scenarios
(200+ threads). Each StrangeLoopStateManager reuses this shared pool instead
of creating its own, preventing connection exhaustion.

Architecture:
    Daemon → SootheRunner → SharedPostgreSQLPool
                      ↓
    StrangeLoopStateManager (receives pool reference)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from psycopg_pool import AsyncConnectionPool

from soothe.foundation.loop.state.persistence.postgres_schema import (
    initialize_sloop_postgres_schema,
)
from soothe.foundation.persistence.postgres_pool_lifecycle import (
    apply_row_factory,
    close_async_pool,
    postgres_pool_timing_from_config,
    release_idle_pool_connections,
)

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

# Singleton instance for daemon-level shared pool
_shared_pool: SharedPostgreSQLPool | None = None
_pool_lock = asyncio.Lock()


class SharedPostgreSQLPool:
    """Shared PostgreSQL connection pool for StrangeLoop state persistence.

    IG-406: High-concurrency architecture with 200+ thread support.
    Pool size is config-driven (``persistence.sloop_pool_size``); default suits
    one active run per process (e.g. pool workers) without multiplying connections by 30×N workers.

    Usage:
        # Initialize at daemon startup
        pool = SharedPostgreSQLPool(dsn, pool_size=24)
        await pool.open()

        # Pass to StrangeLoopStateManager
        state_manager = StrangeLoopStateManager(config=config, shared_pool=pool)

        # Close at daemon shutdown
        await pool.close()
    """

    def __init__(
        self,
        dsn: str,
        pool_size: int = 24,
        *,
        pool_timing: dict[str, Any] | None = None,
    ) -> None:
        """Initialize shared pool configuration.

        Args:
            dsn: PostgreSQL DSN for soothe_checkpoints database.
            pool_size: Shared pool ``max_size`` (default matches ``PersistenceConfig``).
            pool_timing: Optional psycopg pool options (timeout, max_idle, max_lifetime).
        """
        self.dsn = dsn
        self.pool_size = pool_size
        self._pool_timing = pool_timing
        self._pool: AsyncConnectionPool | None = None
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def open(self) -> AsyncConnectionPool:
        """Open the shared connection pool with schema initialization.

        Returns:
            Opened AsyncConnectionPool instance.
        """
        if self._pool is not None and self._initialized:
            return self._pool

        async with self._init_lock:
            if self._pool is not None and self._initialized:
                return self._pool

            pool_kwargs: dict[str, Any] = {
                "max_size": self.pool_size,
                "open": False,
            }
            if self._pool_timing:
                pool_kwargs.update(self._pool_timing)
            else:
                pool_kwargs["min_size"] = min(4, self.pool_size)
            self._pool = AsyncConnectionPool(self.dsn, **apply_row_factory(pool_kwargs))

            # Open pool
            await self._pool.open()

            # Initialize schema (sloop_checkpoints, checkpoint_anchors, etc.)
            await self._initialize_schema(self._pool)

            self._initialized = True
            logger.info(
                "Shared PostgreSQL pool opened for StrangeLoop persistence (size=%d, DSN masked)",
                self.pool_size,
            )

            return self._pool

    async def _initialize_schema(self, pool: AsyncConnectionPool) -> None:
        """Recreate StrangeLoop tables using the canonical PostgreSQL schema."""
        await initialize_sloop_postgres_schema(pool)

    async def release_idle_connections(self) -> None:
        """Return idle connections to PgBouncer (``Pool.check``)."""
        await release_idle_pool_connections(self._pool, label="StrangeLoop")

    async def close(self) -> None:
        """Close the shared connection pool."""
        if self._pool is not None:
            await close_async_pool(self._pool, label="StrangeLoop")
            self._pool = None
            self._initialized = False

    def get_pool(self) -> AsyncConnectionPool | None:
        """Get the underlying pool instance (for direct access).

        Returns:
            AsyncConnectionPool if initialized, None otherwise.
        """
        return self._pool

    @classmethod
    async def get_shared_instance(cls, config: SootheConfig) -> SharedPostgreSQLPool | None:
        """Get or create the singleton shared pool instance.

        IG-406: Daemon-level singleton for high-concurrency support.
        Creates pool only if PostgreSQL backend is configured.

        Args:
            config: SootheConfig for backend detection and DSN resolution.

        Returns:
            SharedPostgreSQLPool instance if PostgreSQL configured, None for SQLite.
        """
        global _shared_pool

        if config.persistence.default_backend != "postgresql":
            return None

        async with _pool_lock:
            if _shared_pool is None:
                dsn = config.resolve_postgres_dsn_for_database("checkpoints")
                pool_size = config.persistence.sloop_pool_size
                timing = postgres_pool_timing_from_config(config, max_size=pool_size)
                _shared_pool = SharedPostgreSQLPool(
                    dsn,
                    pool_size=pool_size,
                    pool_timing=timing,
                )
                await _shared_pool.open()
                logger.info("Created singleton shared PostgreSQL pool (size=%d)", pool_size)

            return _shared_pool

    @classmethod
    async def release_idle_shared(cls) -> None:
        """Release idle connections on the daemon singleton (if open)."""
        global _shared_pool

        if _shared_pool is not None:
            await _shared_pool.release_idle_connections()

    @classmethod
    async def close_shared_instance(cls) -> None:
        """Close the singleton shared pool (daemon shutdown)."""
        global _shared_pool

        async with _pool_lock:
            if _shared_pool is not None:
                await _shared_pool.close()
                _shared_pool = None


__all__ = ["SharedPostgreSQLPool"]
