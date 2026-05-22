"""PostgreSQL schema initialization for AgentLoop persistence.

Schema is defined as ordered SQL scripts under
``soothe/core/persistence/sql/soothe_checkpoints/`` and applied on pool open
via the shared SQL migration runner (idempotent, version-tracked upgrades).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe.core.persistence.sql_migrations import run_database_migrations

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

AGENTLOOP_POSTGRES_DATABASE = "soothe_checkpoints"


async def initialize_agentloop_postgres_schema(pool: AsyncConnectionPool) -> None:
    """Apply pending SQL migrations for AgentLoop persistence tables.

    Called when the shared pool or dedicated backend pool opens (daemon start,
    process restart, or first backend use).

    Args:
        pool: Open ``AsyncConnectionPool`` for the soothe_checkpoints database.
    """
    applied = await run_database_migrations(pool, AGENTLOOP_POSTGRES_DATABASE)
    if applied:
        logger.info(
            "AgentLoop PostgreSQL schema upgraded (applied migrations: %s)",
            ", ".join(applied),
        )
    else:
        logger.debug("AgentLoop PostgreSQL schema already up to date")


__all__ = ["AGENTLOOP_POSTGRES_DATABASE", "initialize_agentloop_postgres_schema"]
