"""PostgreSQL persistence backend for the Context Engine (RFC-624 Phase 4).

Stores CE DAG and ledger in PostgreSQL keyed by ``loop_id``. Writes go through
the process-scoped persistence writer; reads use the shared soothe_checkpoints pool.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from soothe.context.models import GoalStepDAG, GoalStepDAGSnapshot

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_SELECT_DAG_SQL = "SELECT dag_json FROM ce_dag WHERE loop_id = %s"
_SELECT_LEDGER_SQL = "SELECT ledger_json FROM ce_ledger WHERE loop_id = %s"
_DELETE_DAG_SQL = "DELETE FROM ce_dag WHERE loop_id = %s"
_DELETE_LEDGER_SQL = "DELETE FROM ce_ledger WHERE loop_id = %s"


class PgsqlContextPersistence:
    """PostgreSQL-backed persistence for ContextEngine.

    Two tables in a single database:
    - ``ce_dag`` — serialized GoalStepDAG (one row per loop_id)
    - ``ce_ledger`` — serialized message ledger (one row per loop_id)

    Args:
        loop_id: Loop identifier used as primary key.
        dsn: PostgreSQL connection string (legacy; reads use shared pool).
        config: SootheConfig for shared pool and persistence writer access.
    """

    def __init__(
        self,
        loop_id: str,
        dsn: str,
        *,
        config: SootheConfig | None = None,
    ) -> None:
        self._loop_id = loop_id
        self._dsn = dsn
        self._config = config
        self._loop_writer: Any = None

    async def _ensure_loop_writer(self) -> Any:
        if self._loop_writer is not None:
            return self._loop_writer
        if self._config is None:
            msg = "PgsqlContextPersistence requires SootheConfig"
            raise RuntimeError(msg)
        from soothe.persistence.loop_writer import LoopPersistenceWriter

        writer = await LoopPersistenceWriter.get_shared_instance(self._config)
        if writer is None:
            msg = "Loop persistence writer unavailable for PostgreSQL CE backend"
            raise RuntimeError(msg)
        self._loop_writer = writer
        return self._loop_writer

    async def _shared_pool(self) -> Any:
        if self._config is None:
            msg = "PgsqlContextPersistence requires SootheConfig"
            raise RuntimeError(msg)
        from soothe.sloop.checkpoints.shared_pool import SharedPostgreSQLPool

        wrapper = await SharedPostgreSQLPool.get_shared_instance(self._config)
        if wrapper is None:
            msg = "Shared PostgreSQL pool unavailable for CE reads"
            raise RuntimeError(msg)
        pool = wrapper.get_pool()
        if pool is None:
            msg = "Shared PostgreSQL pool is not open"
            raise RuntimeError(msg)
        return pool

    async def save_dag(self, dag: GoalStepDAG) -> None:
        writer = await self._ensure_loop_writer()
        try:
            await writer.submit_save_ce_dag(self._loop_id, dag)
        except Exception:
            logger.warning("[CE] Failed to save DAG via persistence writer", exc_info=True)

    async def load_dag(self) -> GoalStepDAG | None:
        try:
            pool = await self._shared_pool()
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(_SELECT_DAG_SQL, (self._loop_id,))
                    row = await cur.fetchone()
        except Exception:
            logger.warning("[CE] Failed to load DAG from PostgreSQL", exc_info=True)
            return None

        if row is None:
            return None

        try:
            data = row["dag_json"]
            if not isinstance(data, dict):
                data = json.loads(data)
            snapshot = GoalStepDAGSnapshot.model_validate(data)
            dag = GoalStepDAG()
            dag.restore_from_snapshot(snapshot)
            return dag
        except Exception:
            logger.warning("[CE] Failed to parse DAG snapshot", exc_info=True)
            return None

    async def save_ledger(self, messages: list[dict[str, Any]]) -> None:
        writer = await self._ensure_loop_writer()
        try:
            await writer.submit_save_ce_ledger(self._loop_id, messages)
        except Exception:
            logger.warning("[CE] Failed to save ledger via persistence writer", exc_info=True)

    async def load_ledger(self) -> list[dict[str, Any]]:
        try:
            pool = await self._shared_pool()
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(_SELECT_LEDGER_SQL, (self._loop_id,))
                    row = await cur.fetchone()
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
            pool = await self._shared_pool()
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(_DELETE_DAG_SQL, (self._loop_id,))
                    await cur.execute(_DELETE_LEDGER_SQL, (self._loop_id,))
        except Exception:
            logger.warning("[CE] Failed to clear CE tables in PostgreSQL", exc_info=True)

    async def close(self) -> None:
        """No per-loop pool; shared resources are daemon-scoped."""
