"""PostgreSQL schema initialization for StrangeLoop persistence."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from soothe.persistence.db_init import initialize_database

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

AGENTLOOP_POSTGRES_DATABASE = "soothe_checkpoints"

_HOST_SQL_ROOT = Path(__file__).resolve().parent / "sql"


async def initialize_agentloop_postgres_schema(pool: AsyncConnectionPool) -> None:
    """Apply soothe_checkpoints init script and pending migrations.

    Called when the shared pool or dedicated backend pool opens (daemon start,
    process restart, or first backend use).

    Args:
        pool: Open `AsyncConnectionPool` for the soothe_checkpoints database.
    """
    result = await initialize_database(pool, AGENTLOOP_POSTGRES_DATABASE, sql_root=_HOST_SQL_ROOT)
    if result.init_applied or result.migrations_applied:
        logger.debug(
            "StrangeLoop PostgreSQL schema initialized (migrations=%s)",
            ", ".join(result.migrations_applied) if result.migrations_applied else "none",
        )
    else:
        logger.debug("StrangeLoop PostgreSQL init script not found")


__all__ = ["AGENTLOOP_POSTGRES_DATABASE", "initialize_agentloop_postgres_schema"]
