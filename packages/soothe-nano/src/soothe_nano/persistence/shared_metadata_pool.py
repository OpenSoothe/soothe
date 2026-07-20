"""Process-wide singleton PostgreSQL pool for metadata / durability stores."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from soothe_nano.persistence.postgres_pool_lifecycle import (
    apply_row_factory,
    postgres_pool_timing_from_config,
    release_idle_pool_connections,
)
from soothe_nano.persistence.postgres_pool_registry import PostgresPoolRegistry

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)

_shared_metadata_pool: AsyncConnectionPool | None = None
_sync_lock = threading.Lock()


class SharedMetadataPool:
    """Singleton ``AsyncConnectionPool`` for ``soothe_metadata`` durability stores."""

    @classmethod
    def _register_pool(cls, pool: AsyncConnectionPool) -> None:
        """Bind the registry metadata pool to this shim (daemon pre-open)."""
        global _shared_metadata_pool

        with _sync_lock:
            _shared_metadata_pool = pool

    @classmethod
    def get_or_create_pool(cls, config: SootheConfig) -> AsyncConnectionPool | None:
        """Return the shared metadata pool (registry-backed when pre-opened)."""
        global _shared_metadata_pool

        if config.persistence.default_backend != "postgresql":
            return None
        if config.resolve_durability_backend() != "postgresql":
            return None

        with _sync_lock:
            if _shared_metadata_pool is not None:
                return _shared_metadata_pool

            try:
                registry = PostgresPoolRegistry.get_instance(config)
                reg_pool = registry.try_get_pool("metadata")
                if reg_pool is not None:
                    _shared_metadata_pool = reg_pool
                    return reg_pool
            except RuntimeError:
                pass

            try:
                from psycopg_pool import AsyncConnectionPool
            except ImportError:
                logger.warning("psycopg-pool not installed; shared metadata pool unavailable")
                return None

            from soothe_nano.persistence.postgres_provisioning import (
                ensure_postgres_databases,
            )

            ensure_postgres_databases(config)
            dsn = config.resolve_postgres_dsn_for_database("metadata")
            max_size = PostgresPoolRegistry.resolve_metadata_pool_size(config)
            timing = postgres_pool_timing_from_config(config, max_size=max_size)
            pool_kwargs: dict[str, Any] = {
                "max_size": max_size,
                "open": False,
                **timing,
            }
            pool = AsyncConnectionPool(dsn, **apply_row_factory(pool_kwargs))
            _shared_metadata_pool = pool
            logger.info(
                "Created singleton shared PostgreSQL metadata pool (max_size=%d)",
                max_size,
            )
            return pool

    @classmethod
    def is_shared_pool(cls, pool: Any) -> bool:
        """Return whether *pool* is the process singleton."""
        return pool is not None and pool is _shared_metadata_pool

    @classmethod
    async def release_idle(cls) -> None:
        """Drop idle metadata connections (daemon periodic maintenance)."""
        await release_idle_pool_connections(_shared_metadata_pool, label="metadata")

    @classmethod
    async def close_shared_instance(cls) -> None:
        """Clear shim reference (registry owns pool lifecycle)."""
        global _shared_metadata_pool

        with _sync_lock:
            _shared_metadata_pool = None


__all__ = ["SharedMetadataPool"]
