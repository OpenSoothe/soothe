"""PostgreSQL persistence backend for the Context Engine (RFC-624 Phase 4).

Stores CE DAG and ledger in a PostgreSQL database keyed by ``loop_id``.
Uses JSONB columns for queryability and compression. Natively async via
asyncpg — no ``asyncio.to_thread`` needed.

Requires the ``asyncpg`` package (optional dependency).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from soothe.context.models import GoalStepDAG, GoalStepDAGSnapshot

logger = logging.getLogger(__name__)

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS ce_dag (
    loop_id TEXT PRIMARY KEY,
    dag_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS ce_ledger (
    loop_id TEXT PRIMARY KEY,
    ledger_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_UPSERT_DAG_SQL = """
INSERT INTO ce_dag (loop_id, dag_json, updated_at)
VALUES ($1, $2::jsonb, NOW())
ON CONFLICT (loop_id) DO UPDATE SET
    dag_json = excluded.dag_json,
    updated_at = excluded.updated_at
"""

_UPSERT_LEDGER_SQL = """
INSERT INTO ce_ledger (loop_id, ledger_json, updated_at)
VALUES ($1, $2::jsonb, NOW())
ON CONFLICT (loop_id) DO UPDATE SET
    ledger_json = excluded.ledger_json,
    updated_at = excluded.updated_at
"""

_SELECT_DAG_SQL = "SELECT dag_json FROM ce_dag WHERE loop_id = $1"
_SELECT_LEDGER_SQL = "SELECT ledger_json FROM ce_ledger WHERE loop_id = $1"
_DELETE_DAG_SQL = "DELETE FROM ce_dag WHERE loop_id = $1"
_DELETE_LEDGER_SQL = "DELETE FROM ce_ledger WHERE loop_id = $1"


class PgsqlContextPersistence:
    """PostgreSQL-backed persistence for ContextEngine.

    Two tables in a single database:
    - ``ce_dag`` — serialized GoalStepDAG (one row per loop_id)
    - ``ce_ledger`` — serialized message ledger (one row per loop_id)

    Args:
        loop_id: Loop identifier used as primary key.
        dsn: PostgreSQL connection string (e.g. ``postgresql://user:pass@host/db``).
        pool_min_size: Minimum connection pool size.
        pool_max_size: Maximum connection pool size.
    """

    def __init__(
        self,
        loop_id: str,
        dsn: str,
        *,
        pool_min_size: int = 2,
        pool_max_size: int = 10,
    ) -> None:
        self._loop_id = loop_id
        self._dsn = dsn
        self._pool_min_size = pool_min_size
        self._pool_max_size = pool_max_size
        self._pool: Any = None

    async def _ensure_pool(self) -> Any:
        if self._pool is not None:
            return self._pool
        try:
            import asyncpg
        except ImportError:
            msg = "asyncpg is required for PgsqlContextPersistence"
            raise ImportError(msg) from None

        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._pool_min_size,
            max_size=self._pool_max_size,
        )
        async with self._pool.acquire() as conn:
            await conn.execute(_CREATE_TABLES_SQL)
        return self._pool

    async def save_dag(self, dag: GoalStepDAG) -> None:
        snapshot = dag.snapshot()
        data = snapshot.model_dump(mode="json")
        json_str = json.dumps(data, default=str)
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                await conn.execute(_UPSERT_DAG_SQL, self._loop_id, json_str)
        except Exception:
            logger.warning("[CE] Failed to save DAG to PostgreSQL", exc_info=True)

    async def load_dag(self) -> GoalStepDAG | None:
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(_SELECT_DAG_SQL, self._loop_id)
        except Exception:
            logger.warning("[CE] Failed to load DAG from PostgreSQL", exc_info=True)
            return None

        if row is None:
            return None

        try:
            data = (
                row["dag_json"]
                if isinstance(row["dag_json"], dict)
                else json.loads(row["dag_json"])
            )
            snapshot = GoalStepDAGSnapshot.model_validate(data)
            dag = GoalStepDAG()
            dag.restore_from_snapshot(snapshot)
            return dag
        except Exception:
            logger.warning("[CE] Failed to parse DAG snapshot", exc_info=True)
            return None

    async def save_ledger(self, messages: list[dict[str, Any]]) -> None:
        json_str = json.dumps(messages, default=str)
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                await conn.execute(_UPSERT_LEDGER_SQL, self._loop_id, json_str)
        except Exception:
            logger.warning("[CE] Failed to save ledger to PostgreSQL", exc_info=True)

    async def load_ledger(self) -> list[dict[str, Any]]:
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(_SELECT_LEDGER_SQL, self._loop_id)
        except Exception:
            logger.warning("[CE] Failed to load ledger from PostgreSQL", exc_info=True)
            return []

        if row is None:
            return []

        try:
            data = row["ledger_json"]
            if isinstance(data, list):
                return data
            return json.loads(data) if isinstance(data, str) else list(data)
        except Exception:
            logger.warning("[CE] Failed to parse ledger JSON", exc_info=True)
            return []

    async def clear(self) -> None:
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                await conn.execute(_DELETE_DAG_SQL, self._loop_id)
                await conn.execute(_DELETE_LEDGER_SQL, self._loop_id)
        except Exception:
            logger.warning("[CE] Failed to clear CE tables in PostgreSQL", exc_info=True)

    async def close(self) -> None:
        if self._pool is not None:
            try:
                await self._pool.close()
            except Exception:
                pass
            self._pool = None
