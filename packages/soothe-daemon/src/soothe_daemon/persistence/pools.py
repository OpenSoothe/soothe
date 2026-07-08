"""Shared PostgreSQL pool lifecycle for the daemon process."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.config import SootheConfig

    from soothe_daemon.config.models import DaemonConfig

logger = logging.getLogger(__name__)

POSTGRES_POOL_MAINTENANCE_INTERVAL_S = 300


def uses_postgresql_persistence(config: SootheConfig) -> bool:
    """Return whether the daemon should manage shared PostgreSQL pools."""
    return config.persistence.default_backend == "postgresql"


async def preopen_shared_postgres_pools(
    config: SootheConfig,
    daemon_config: DaemonConfig,
) -> None:
    """Pre-open shared PostgreSQL pools via PostgresPoolRegistry (thread_pool mode)."""
    if not uses_postgresql_persistence(config):
        return

    if not daemon_config.thread_pool.enabled:
        return

    from soothe.foundation.persistence.loop_writer import LoopPersistenceWriter
    from soothe.foundation.persistence.postgres_pool_registry import PostgresPoolRegistry
    from soothe.foundation.persistence.shared_metadata_pool import SharedMetadataPool
    from soothe.foundation.sloop.state.persistence.shared_pool import SharedPostgreSQLPool
    from soothe.runner.resolver.shared_checkpointer_pool import SharedCheckpointerPool

    registry = PostgresPoolRegistry.get_instance(config)
    await registry.open_all()

    checkpoints_pool = registry.get_pool("checkpoints")
    SharedCheckpointerPool._register_pool(checkpoints_pool)
    await SharedPostgreSQLPool.bind_registry_pool(config, checkpoints_pool)

    metadata_pool = registry.get_pool("metadata")
    SharedMetadataPool._register_pool(metadata_pool)

    LoopPersistenceWriter.bind_main_loop(asyncio.get_running_loop())
    await LoopPersistenceWriter.get_shared_instance(config)

    logger.info("PostgresPoolRegistry pre-open complete")


async def release_idle_shared_postgres_pools() -> None:
    """Release idle connections on process-wide shared PostgreSQL pools."""
    from soothe.foundation.persistence.postgres_pool_registry import PostgresPoolRegistry
    from soothe.foundation.persistence.shared_metadata_pool import SharedMetadataPool
    from soothe.foundation.sloop.state.persistence.shared_pool import SharedPostgreSQLPool
    from soothe.runner.resolver.shared_checkpointer_pool import SharedCheckpointerPool

    registry = PostgresPoolRegistry.try_get_instance()
    if registry is not None:
        await registry.release_idle_all()
        return

    await SharedPostgreSQLPool.release_idle_shared()
    await SharedCheckpointerPool.release_idle()
    await SharedMetadataPool.release_idle()


async def close_shared_postgres_pools() -> None:
    """Close shared PostgreSQL pools at daemon shutdown."""
    try:
        from soothe.foundation.persistence.loop_writer import LoopPersistenceWriter
        from soothe.foundation.persistence.postgres_pool_registry import PostgresPoolRegistry
        from soothe.foundation.persistence.shared_metadata_pool import SharedMetadataPool
        from soothe.foundation.sloop.state.persistence.shared_pool import (
            SharedPostgreSQLPool,
            close_shared_sqlite_backend_instance,
        )
        from soothe.runner.resolver.shared_checkpointer_pool import SharedCheckpointerPool

        try:
            await LoopPersistenceWriter.close_shared_instance()
            logger.info("Shared loop persistence writer closed")
        except ImportError:
            pass

        await SharedPostgreSQLPool.close_shared_instance()
        await SharedCheckpointerPool.close_shared_instance()
        await SharedMetadataPool.close_shared_instance()

        registry = PostgresPoolRegistry.try_get_instance()
        if registry is not None:
            await registry.close_all()
            logger.info("PostgresPoolRegistry closed")

        await close_shared_sqlite_backend_instance()
        logger.info("Shared persistence pools closed")
    except ImportError:
        pass
    except Exception:
        logger.debug("Failed to close shared persistence pools", exc_info=True)


async def periodic_postgres_pool_maintenance(
    *,
    is_running: Callable[[], bool],
    interval_s: int = POSTGRES_POOL_MAINTENANCE_INTERVAL_S,
    config: SootheConfig | None = None,
) -> None:
    """Release idle connections on shared pools on a fixed interval."""
    while is_running():
        await asyncio.sleep(interval_s)
        try:
            await release_idle_shared_postgres_pools()
            if config is not None and uses_postgresql_persistence(config):
                _log_pool_stats(config)
            await _reconcile_degraded_checkpoints_if_configured(config)
        except Exception:
            logger.debug("PostgreSQL pool maintenance failed", exc_info=True)


def _log_pool_stats(config: SootheConfig) -> None:
    """Log pool utilization from the registry when available."""
    try:
        from soothe.foundation.persistence.postgres_pool_registry import PostgresPoolRegistry

        registry = PostgresPoolRegistry.try_get_instance()
        if registry is None:
            return
        stats = registry.pool_stats()
        if stats:
            logger.info("PostgreSQL pool stats: %s", stats)
    except Exception:
        logger.debug("Pool stats unavailable", exc_info=True)


async def _reconcile_degraded_checkpoints_if_configured(
    config: SootheConfig | None,
) -> None:
    """Run degraded-checkpoint reconciler when unified writer is enabled."""
    if config is None or config.persistence.default_backend != "postgresql":
        return
    try:
        from soothe.foundation.persistence.persist_reconciler import (
            reconcile_degraded_checkpoints,
        )
        from soothe.foundation.sloop.state.persistence.shared_pool import (
            SharedPostgreSQLPool,
        )

        pool_wrapper = await SharedPostgreSQLPool.get_shared_instance(config)
        if pool_wrapper is None:
            return
        pg_pool = pool_wrapper.get_pool()
        if pg_pool is None:
            return
        count = await reconcile_degraded_checkpoints(pg_pool, limit=10)
        if count:
            logger.info("Reconciled %d degraded checkpoint(s)", count)
    except Exception:
        logger.debug("Degraded checkpoint reconciliation failed", exc_info=True)
