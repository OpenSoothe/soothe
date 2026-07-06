"""Background reconciler for checkpoints marked persist_status=degraded."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

_DEGRADED_QUERY = """
SELECT loop_id, checkpoint_data
FROM agentloop_checkpoints
WHERE checkpoint_data->'execution_checkpoint'->>'persist_status' = 'degraded'
   OR checkpoint_index->'execution_checkpoint'->>'persist_status' = 'degraded'
LIMIT %s
"""


async def reconcile_degraded_checkpoints(
    pool: AsyncConnectionPool,
    *,
    limit: int = 20,
) -> int:
    """Retry durable flush for checkpoints marked degraded.

    Args:
        pool: Open pool for soothe_checkpoints.
        limit: Max rows to process per invocation.

    Returns:
        Number of checkpoints successfully reconciled.
    """
    from soothe.foundation.persistence.checkpoint_split import clear_persist_degraded
    from soothe.foundation.sloop.state.checkpoint import (
        StrangeLoopCheckpoint,
        normalize_checkpoint_data,
    )
    from soothe.foundation.sloop.state.persistence.postgres_backend import (
        PostgreSQLPersistenceBackend,
    )

    reconciled = 0
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(_DEGRADED_QUERY, (limit,))
            rows = await cur.fetchall()

    if not rows:
        return 0

    backend = PostgreSQLPersistenceBackend(dsn="", pool_size=0)
    backend._pool = pool  # noqa: SLF001

    for row in rows:
        loop_id = row["loop_id"]
        try:
            raw = dict(row["checkpoint_data"])
            checkpoint_data = normalize_checkpoint_data(raw, loop_id=loop_id)
            checkpoint = StrangeLoopCheckpoint.model_validate(checkpoint_data)
            clear_persist_degraded(checkpoint)
            await backend.save_checkpoint(checkpoint, write_mode="full")
            reconciled += 1
            logger.info("Reconciled degraded checkpoint for loop %s", loop_id)
        except Exception:
            logger.warning(
                "Failed to reconcile degraded checkpoint loop=%s",
                loop_id,
                exc_info=True,
            )

    return reconciled


async def find_stale_running_goals(
    pool: AsyncConnectionPool,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Find loops whose last goal_history entry is running but CE may show completed.

    Returns lightweight rows for daemon maintenance logging (no auto-fix).
    """
    query = """
    SELECT loop_id, checkpoint_data->'goal_history' AS goal_history
    FROM agentloop_checkpoints
    WHERE jsonb_array_length(COALESCE(checkpoint_data->'goal_history', '[]'::jsonb)) > 0
      AND (checkpoint_data->'goal_history'->-1->>'status') = 'running'
    LIMIT %s
    """
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, (limit,))
            rows = await cur.fetchall()
    return [dict(r) for r in rows]
