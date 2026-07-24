"""Shared PostgreSQL connection pool for StrangeLoop persistence (IG-406).

Provides a singleton pool at daemon level for high-concurrency scenarios
(200+ threads). Each StrangeLoopStateManager reuses this shared pool instead
of creating its own, preventing connection exhaustion.

SQLite mode uses a ref-counted singleton ``SQLitePersistenceBackend`` so each
loop's anchor manager shares the process ``SqliteStoreRuntime`` for
``databases/checkpoints.db``.

Architecture:
    Daemon → SootheRunner → SharedPostgreSQLPool
                      ↓
    StrangeLoopStateManager (receives pool reference)
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Any

from psycopg_pool import AsyncConnectionPool

from soothe.persistence.postgres_pool_lifecycle import (
    apply_row_factory,
    close_async_pool,
    postgres_pool_timing_from_config,
    release_idle_pool_connections,
)
from soothe.persistence.postgres_pool_registry import PostgresPoolRegistry
from soothe.sloop.checkpoints.directory_manager import (
    PersistenceDirectoryManager,
)
from soothe.sloop.checkpoints.postgres_schema import (
    initialize_agentloop_postgres_schema,
)
from soothe.sloop.checkpoints.sqlite_backend import (
    SQLitePersistenceBackend,
)

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

# SQLite singleton (ref-counted; closed when last manager releases)
_shared_sqlite_backend: SQLitePersistenceBackend | None = None
_shared_sqlite_refcount: int = 0
_sqlite_thread_lock = threading.Lock()

# Cap SQLite reader pool size — file DB does not benefit from large pools.
_SQLITE_POOL_SIZE = 3

# Singleton instance for daemon-level shared pool
_shared_pool: SharedPostgreSQLPool | None = None
_pool_lock = asyncio.Lock()


class SharedPostgreSQLPool:
    """Shared PostgreSQL connection pool for StrangeLoop state persistence.

    IG-406: High-concurrency architecture with 200+ thread support.
    Pool size is config-driven (``persistence.postgres.checkpoints_pool_size``); default suits
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
        self._registry_backed = False

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

            # Initialize schema (agentloop_checkpoints, checkpoint_anchors, etc.)
            await self._initialize_schema(self._pool)

            self._initialized = True
            logger.info(
                "Shared PostgreSQL pool opened for StrangeLoop persistence (size=%d, DSN masked)",
                self.pool_size,
            )

            return self._pool

    async def _initialize_schema(self, pool: AsyncConnectionPool) -> None:
        """Recreate StrangeLoop tables using the canonical PostgreSQL schema."""
        await initialize_agentloop_postgres_schema(pool)

    async def release_idle_connections(self) -> None:
        """Return idle connections to PgBouncer (``Pool.check``)."""
        await release_idle_pool_connections(self._pool, label="StrangeLoop")

    async def close(self) -> None:
        """Close the shared connection pool (skipped when registry-backed)."""
        if self._registry_backed:
            self._pool = None
            self._initialized = False
            return
        if self._pool is not None:
            await close_async_pool(self._pool, label="StrangeLoop")
            self._pool = None
            self._initialized = False

    async def reset_pool(self) -> None:
        """Reset the shared pool after connection error.

        Closes existing pool and reopens with fresh connections.
        Called when PostgreSQL restarts or connection is lost.
        """
        from soothe.persistence.loop_writer import LoopPersistenceWriter

        writer = LoopPersistenceWriter.existing_instance()
        if writer is not None:
            await writer.pause_for_pool_reset()

        async with self._init_lock:
            old_pool = self._pool
            self._pool = None
            self._initialized = False

            if old_pool is not None:
                try:
                    await old_pool.close()
                    logger.info("Closed stale shared PostgreSQL pool for reset")
                except Exception:
                    logger.debug("Error closing stale pool during reset", exc_info=True)

            # Reopen pool with fresh connections
            await self.open()
            logger.info("Shared PostgreSQL pool reset complete (fresh connections)")

        if writer is not None:
            writer.resume_after_pool_reset()

    def get_pool(self) -> AsyncConnectionPool | None:
        """Get the underlying pool instance (for direct access).

        Returns:
            AsyncConnectionPool if initialized, None otherwise.
        """
        return self._pool

    @classmethod
    async def bind_registry_pool(
        cls,
        config: SootheConfig,
        pool: AsyncConnectionPool,
    ) -> SharedPostgreSQLPool:
        """Wrap the registry checkpoints pool for StrangeLoop consumers."""
        global _shared_pool

        async with _pool_lock:
            if _shared_pool is None:
                dsn = config.resolve_postgres_dsn_for_database("checkpoints")
                wrapper = cls(dsn, pool_size=0, pool_timing=None)
                wrapper._pool = pool
                wrapper._initialized = True
                wrapper._registry_backed = True
                _shared_pool = wrapper
            return _shared_pool

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
            if _shared_pool is not None:
                return _shared_pool

            try:
                registry = PostgresPoolRegistry.get_instance(config)
                reg_pool = registry.try_get_pool("checkpoints")
                if reg_pool is not None:
                    return await cls.bind_registry_pool(config, reg_pool)
            except RuntimeError:
                pass

            from soothe_nano.persistence.postgres_provisioning import (
                ensure_postgres_databases_async,
            )

            await ensure_postgres_databases_async(config)
            dsn = config.resolve_postgres_dsn_for_database("checkpoints")
            pool_size = PostgresPoolRegistry.resolve_checkpoints_pool_size(config)
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

    @classmethod
    async def reset_shared_instance(cls) -> None:
        """Reset the singleton shared pool after connection error.

        Called by PostgreSQLPersistenceBackend when recoverable
        connection errors occur (e.g., AdminShutdown during DB restart).
        """
        global _shared_pool

        async with _pool_lock:
            if _shared_pool is not None:
                await _shared_pool.reset_pool()
                logger.info("Reset singleton shared PostgreSQL pool for recovery")


def acquire_shared_sqlite_backend_sync() -> SQLitePersistenceBackend:
    """Return the process-wide SQLite backend; increment ref count (sync).

    Safe in ``__init__`` because ``SQLitePersistenceBackend`` opens connections lazily.
    Recreates the singleton if a prior ``SqliteRuntimeRegistry.close_all`` left a
    closed Runtime attached to a stale backend.
    """
    global _shared_sqlite_backend, _shared_sqlite_refcount

    with _sqlite_thread_lock:
        if _shared_sqlite_backend is not None:
            runtime = getattr(_shared_sqlite_backend, "_runtime", None)
            if runtime is not None and getattr(runtime, "_closed", False):
                logger.warning("Shared SQLite backend held a closed Runtime; recreating singleton")
                _shared_sqlite_backend = None
                _shared_sqlite_refcount = 0

        if _shared_sqlite_backend is None:
            db_path = PersistenceDirectoryManager.get_loop_checkpoint_path()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            SQLitePersistenceBackend.initialize_database_sync(db_path)
            _shared_sqlite_backend = SQLitePersistenceBackend(
                db_path=db_path,
                pool_size=_SQLITE_POOL_SIZE,
            )
            logger.info(
                "Shared SQLite persistence backend opened at %s (pool=%d)",
                db_path,
                _SQLITE_POOL_SIZE,
            )
        _shared_sqlite_refcount += 1
        return _shared_sqlite_backend


async def release_shared_sqlite_backend() -> None:
    """Release one reference; close the shared backend when the last ref drops."""
    global _shared_sqlite_backend, _shared_sqlite_refcount

    backend_to_close: SQLitePersistenceBackend | None = None
    with _sqlite_thread_lock:
        if _shared_sqlite_refcount <= 0:
            return
        _shared_sqlite_refcount -= 1
        if _shared_sqlite_refcount == 0 and _shared_sqlite_backend is not None:
            backend_to_close = _shared_sqlite_backend
            _shared_sqlite_backend = None
    if backend_to_close is not None:
        await backend_to_close.close()
        logger.info("Shared SQLite persistence backend closed")


async def close_shared_sqlite_backend_instance() -> None:
    """Force-close the shared SQLite backend (daemon shutdown)."""
    global _shared_sqlite_backend, _shared_sqlite_refcount

    backend_to_close: SQLitePersistenceBackend | None = None
    with _sqlite_thread_lock:
        _shared_sqlite_refcount = 0
        if _shared_sqlite_backend is not None:
            backend_to_close = _shared_sqlite_backend
            _shared_sqlite_backend = None
    if backend_to_close is not None:
        await backend_to_close.close()
        logger.info("Shared SQLite persistence backend closed (shutdown)")


__all__ = [
    "SharedPostgreSQLPool",
    "acquire_shared_sqlite_backend_sync",
    "close_shared_sqlite_backend_instance",
    "release_shared_sqlite_backend",
]
