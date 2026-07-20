"""Process-wide PostgreSQL pool registry — one AsyncConnectionPool per database."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Any, Literal

from soothe_nano.persistence.postgres_pool_lifecycle import (
    apply_row_factory,
    close_async_pool,
    postgres_pool_timing_from_config,
    release_idle_pool_connections,
)

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)

DbKey = Literal["checkpoints", "metadata", "vectors"]

_registry: PostgresPoolRegistry | None = None
_registry_lock = threading.Lock()
_async_lock = asyncio.Lock()

# Warn when configured pool max sizes exceed this budget (dev PG default 200 minus headroom).
_DEFAULT_BUDGET_WARN_THRESHOLD = 120


class PostgresPoolRegistry:
    """Singleton registry: one ``AsyncConnectionPool`` per PostgreSQL database."""

    def __init__(self, config: SootheConfig) -> None:
        self._config = config
        self._pools: dict[DbKey, AsyncConnectionPool] = {}
        self._opened = False

    @classmethod
    def get_instance(cls, config: SootheConfig) -> PostgresPoolRegistry:
        """Return the process-wide registry, creating it on first access."""
        global _registry

        if config.persistence.default_backend != "postgresql":
            msg = "PostgresPoolRegistry requires persistence.default_backend=postgresql"
            raise RuntimeError(msg)

        with _registry_lock:
            if _registry is None:
                _registry = cls(config)
            return _registry

    @classmethod
    def try_get_instance(cls) -> PostgresPoolRegistry | None:
        """Return the registry if already created, else None."""
        return _registry

    @classmethod
    def reset_instance(cls) -> PostgresPoolRegistry | None:
        """Clear the singleton without closing pools (tests). Returns previous instance."""
        global _registry

        previous = _registry
        with _registry_lock:
            _registry = None
        return previous

    @staticmethod
    def resolve_checkpoints_pool_size(config: SootheConfig) -> int:
        """Effective max_size for the checkpoints database pool."""
        p = config.persistence
        return p.checkpoints_pool_size

    @staticmethod
    def resolve_metadata_pool_size(config: SootheConfig) -> int:
        """Effective max_size for the metadata database pool."""
        return config.persistence.metadata_pool_size

    @staticmethod
    def resolve_vectors_pool_size(config: SootheConfig) -> int:
        """Effective max_size for the vectors database pool."""
        return config.persistence.vectors_pool_size

    @classmethod
    def validate_budget(cls, config: SootheConfig) -> None:
        """Log a warning when configured pool ceilings exceed the budget threshold."""
        total = (
            cls.resolve_checkpoints_pool_size(config)
            + cls.resolve_metadata_pool_size(config)
            + cls.resolve_vectors_pool_size(config)
        )
        threshold = config.persistence.postgres_connection_budget_warn
        if total > threshold:
            logger.warning(
                "PostgreSQL pool budget high: checkpoints=%d metadata=%d vectors=%d "
                "total=%d (warn threshold=%d). Reduce pool sizes or raise PG max_connections.",
                cls.resolve_checkpoints_pool_size(config),
                cls.resolve_metadata_pool_size(config),
                cls.resolve_vectors_pool_size(config),
                total,
                threshold,
            )

    def get_pool(self, db_key: DbKey) -> AsyncConnectionPool:
        """Return an opened pool for *db_key*."""
        pool = self._pools.get(db_key)
        if pool is None or getattr(pool, "closed", False):
            msg = f"PostgreSQL pool for {db_key!r} is not open"
            raise RuntimeError(msg)
        return pool

    def try_get_pool(self, db_key: DbKey) -> AsyncConnectionPool | None:
        """Return pool if open, else None."""
        pool = self._pools.get(db_key)
        if pool is None or getattr(pool, "closed", False):
            return None
        return pool

    async def open_all(self) -> None:
        """Open all database pools and run schema initialization."""
        async with _async_lock:
            if self._opened and all(
                p is not None and not getattr(p, "closed", True) for p in self._pools.values()
            ):
                return

            from soothe_nano.persistence.postgres_provisioning import (
                ensure_postgres_databases_async,
            )

            await ensure_postgres_databases_async(self._config)
            self.validate_budget(self._config)

            await self._open_pool("checkpoints")
            await self._open_pool("metadata")
            if self._uses_pgvector():
                await self._open_pool("vectors")

            self._opened = True
            logger.info(
                "PostgresPoolRegistry opened (checkpoints=%d metadata=%d vectors=%d)",
                self.resolve_checkpoints_pool_size(self._config),
                self.resolve_metadata_pool_size(self._config),
                self.resolve_vectors_pool_size(self._config) if self._uses_pgvector() else 0,
            )

    def _uses_pgvector(self) -> bool:
        for provider in self._config.vector_stores:
            if provider.provider_type == "pgvector":
                return True
        return False

    async def _open_pool(self, db_key: DbKey) -> AsyncConnectionPool:
        existing = self._pools.get(db_key)
        if existing is not None and not getattr(existing, "closed", False):
            return existing

        from psycopg_pool import AsyncConnectionPool

        dsn = self._config.resolve_postgres_dsn_for_database(db_key)
        max_size = self._max_size_for(db_key)
        timing = postgres_pool_timing_from_config(self._config, max_size=max_size)
        pool_kwargs: dict[str, Any] = {
            "max_size": max_size,
            "open": False,
            **timing,
        }
        pool = AsyncConnectionPool(dsn, **apply_row_factory(pool_kwargs))
        await pool.open()

        if db_key == "checkpoints":
            from soothe_nano.persistence.postgres_schema import (
                initialize_agentloop_postgres_schema,
            )

            await initialize_agentloop_postgres_schema(pool)
        elif db_key == "metadata":
            from soothe_nano.persistence.db_init import initialize_database

            await initialize_database(pool, "soothe_metadata")

        self._pools[db_key] = pool
        logger.info(
            "Opened PostgreSQL pool for %s (max_size=%d)",
            db_key,
            max_size,
        )
        return pool

    def _max_size_for(self, db_key: DbKey) -> int:
        if db_key == "checkpoints":
            return self.resolve_checkpoints_pool_size(self._config)
        if db_key == "metadata":
            return self.resolve_metadata_pool_size(self._config)
        return self.resolve_vectors_pool_size(self._config)

    async def release_idle_all(self) -> None:
        """Return idle connections on all open pools."""
        for db_key, pool in self._pools.items():
            await release_idle_pool_connections(pool, label=db_key)

    async def close_all(self) -> None:
        """Close all pools and reset the registry singleton."""
        async with _async_lock:
            for db_key, pool in list(self._pools.items()):
                await close_async_pool(pool, label=db_key)
            self._pools.clear()
            self._opened = False
        global _registry
        with _registry_lock:
            if _registry is self:
                _registry = None

    def pool_stats(self) -> dict[str, dict[str, Any]]:
        """Return psycopg pool statistics keyed by database."""
        stats: dict[str, dict[str, Any]] = {}
        for db_key, pool in self._pools.items():
            if pool is None or getattr(pool, "closed", False):
                continue
            try:
                raw = pool.get_stats()
                stats[db_key] = {
                    "pool_size": raw.get("pool_size"),
                    "pool_available": raw.get("pool_available"),
                    "requests_waiting": raw.get("requests_waiting"),
                    "max_size": self._max_size_for(db_key),
                }
            except Exception:
                logger.debug("Failed to read pool stats for %s", db_key, exc_info=True)
        return stats


__all__ = ["DbKey", "PostgresPoolRegistry"]
