"""Daemon-side persistence helpers (PostgreSQL pools, worker cleanup, health checks)."""

from soothe_daemon.persistence.health_check import check_persistence
from soothe_daemon.persistence.pool_sizing import (
    recommended_agentloop_pool_size,
    recommended_checkpointer_pool_size,
)
from soothe_daemon.persistence.pools import (
    POSTGRES_POOL_MAINTENANCE_INTERVAL_S,
    close_shared_postgres_pools,
    periodic_postgres_pool_maintenance,
    preopen_shared_postgres_pools,
    release_idle_shared_postgres_pools,
    uses_postgresql_persistence,
)
from soothe_daemon.persistence.process_cleanup import (
    reap_from_cli,
    reap_stale_soothe_worker_processes,
)

__all__ = [
    "POSTGRES_POOL_MAINTENANCE_INTERVAL_S",
    "check_persistence",
    "close_shared_postgres_pools",
    "periodic_postgres_pool_maintenance",
    "preopen_shared_postgres_pools",
    "recommended_agentloop_pool_size",
    "recommended_checkpointer_pool_size",
    "reap_from_cli",
    "reap_stale_soothe_worker_processes",
    "release_idle_shared_postgres_pools",
    "uses_postgresql_persistence",
]
