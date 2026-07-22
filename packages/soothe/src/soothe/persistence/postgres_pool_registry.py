"""Host PostgreSQL pool registry — extends nano with checkpoints bootstrap.

Canonical pool lifecycle lives in
:mod:`soothe_nano.persistence.postgres_pool_registry`. The host subclass opens
the host-owned ``checkpoints`` database and applies its schema.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from soothe_nano.persistence.postgres_pool_registry import (
    DbKey,
)
from soothe_nano.persistence.postgres_pool_registry import (
    PostgresPoolRegistry as _NanoPostgresPoolRegistry,
)

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool


class PostgresPoolRegistry(_NanoPostgresPoolRegistry):
    """Host registry: metadata + vectors + checkpoints (host loop schema)."""

    def _databases_to_open(self) -> list[DbKey]:
        keys: list[DbKey] = ["checkpoints", "metadata"]
        if self._uses_pgvector():
            keys.append("vectors")
        return keys

    async def _initialize_pool_schema(self, db_key: DbKey, pool: AsyncConnectionPool) -> None:
        if db_key == "checkpoints":
            from soothe.sloop.checkpoints.postgres_schema import (
                initialize_agentloop_postgres_schema,
            )

            await initialize_agentloop_postgres_schema(pool)
            return
        await super()._initialize_pool_schema(db_key, pool)


__all__ = ["DbKey", "PostgresPoolRegistry"]
