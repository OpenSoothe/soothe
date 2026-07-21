"""PostgreSQL schema initialization for StrangeLoop persistence.

Schema is defined in ``soothe/foundation/persistence/sql/soothe_checkpoints/``
(``init.sql`` plus optional versioned ``NNN_name.sql`` scripts) and applied
idempotently on pool open via :func:`initialize_database`.

IG-678 PR-3: the host owns the StrangeLoop/CE schema; ``sql_root`` is pinned to
the host sql dir so the schema no longer lives in ``soothe_nano``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from soothe.foundation.persistence.db_init import initialize_database

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
        pool: Open ``AsyncConnectionPool`` for the soothe_checkpoints database.
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
