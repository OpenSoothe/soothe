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
    """Pre-open shared AgentLoop and checkpointer pools in thread_pool mode."""
    if not uses_postgresql_persistence(config) or not daemon_config.thread_pool.enabled:
        return

    from soothe.foundation.loop.state.persistence.shared_pool import SharedPostgreSQLPool
    from soothe.runner.resolver.shared_checkpointer_pool import SharedCheckpointerPool

    await SharedPostgreSQLPool.get_shared_instance(config)
    cp_pool = SharedCheckpointerPool.get_or_create_pool(config)
    if cp_pool is not None:
        await cp_pool.open()


async def release_idle_shared_postgres_pools() -> None:
    """Release idle connections on process-wide shared PostgreSQL pools."""
    from soothe.foundation.loop.state.persistence.shared_pool import SharedPostgreSQLPool
    from soothe.runner.resolver.shared_checkpointer_pool import SharedCheckpointerPool

    await SharedPostgreSQLPool.release_idle_shared()
    await SharedCheckpointerPool.release_idle()


async def close_shared_postgres_pools() -> None:
    """Close shared AgentLoop and checkpointer pools at daemon shutdown."""
    try:
        from soothe.foundation.loop.state.persistence.shared_pool import SharedPostgreSQLPool
        from soothe.runner.resolver.shared_checkpointer_pool import SharedCheckpointerPool

        await SharedPostgreSQLPool.close_shared_instance()
        logger.info("Shared AgentLoop PostgreSQL pool closed")
        await SharedCheckpointerPool.close_shared_instance()
        logger.info("Shared checkpointer PostgreSQL pool closed")
    except ImportError:
        pass
    except Exception:
        logger.debug("Failed to close shared PostgreSQL pools", exc_info=True)


async def periodic_postgres_pool_maintenance(
    *,
    is_running: Callable[[], bool],
    interval_s: int = POSTGRES_POOL_MAINTENANCE_INTERVAL_S,
) -> None:
    """Release idle connections on shared pools on a fixed interval."""
    while is_running():
        await asyncio.sleep(interval_s)
        try:
            await release_idle_shared_postgres_pools()
        except Exception:
            logger.debug("PostgreSQL pool maintenance failed", exc_info=True)
