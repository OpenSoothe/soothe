"""PostgreSQL backend for StrangeLoop persistence."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from psycopg_pool import AsyncConnectionPool

from soothe.sloop.checkpoints.base_backend import StrangeLoopPersistenceBackend
from soothe.sloop.checkpoints.postgres_schema import (
    initialize_agentloop_postgres_schema,
)
from soothe.sloop.checkpoints.retry_utils import (
    run_with_connection_retry,
)

if TYPE_CHECKING:
    from soothe.sloop.checkpoints.shared_pool import SharedPostgreSQLPool
    from soothe.sloop.state.checkpoint import StrangeLoopCheckpoint

logger = logging.getLogger(__name__)


def _is_missing_hot_cold_schema(exc: BaseException) -> bool:
    """Return True when PostgreSQL lacks hot/cold checkpoint columns or tables."""
    msg = str(exc).casefold()
    markers = (
        "checkpoint_index",
        "agentloop_checkpoint_blobs",
        "undefined column",
        "undefined table",
        "does not exist",
    )
    return any(marker in msg for marker in markers)


class PostgreSQLPersistenceBackend(StrangeLoopPersistenceBackend):
    """PostgreSQL backend for StrangeLoop persistence.

    Backend-agnostic implementation using shared soothe_checkpoints database
    with separate tables for checkpoints, anchors, branches, and goals.

    Supports shared pool mode for high-concurrency scenarios.
    """

    def __init__(
        self,
        dsn: str,
        pool_size: int = 10,
        shared_pool: SharedPostgreSQLPool | None = None,
        *,
        pool_timing: dict[str, Any] | None = None,
    ) -> None:
        """Initialize PostgreSQL backend with DSN and pool configuration.

        pool_size=0 indicates externally provided (shared) pool.

        Args:
            dsn: PostgreSQL DSN for soothe_checkpoints database.
            pool_size: Connection pool size (default: 10). Use 0 for shared pool mode.
            shared_pool: Shared pool instance for reset capability.
            pool_timing: Optional psycopg pool options (timeout, max_idle, max_lifetime).
        """
        self.dsn = dsn
        self.pool_size = pool_size
        self._pool: AsyncConnectionPool | None = None
        self._init_lock = asyncio.Lock()
        # pool_size=0 = externally injected shared pool; never close it here.
        self._owns_pool = pool_size != 0
        self._shared_pool = shared_pool
        self._pool_timing = pool_timing

    async def _ensure_pool(self) -> AsyncConnectionPool:
        """Lazy connection pool initialization with schema setup.

        If pool is already set (shared mode), skip creation.

        Returns:
            Active AsyncConnectionPool instance.
        """
        if self._pool is not None and not self._pool.closed:
            return self._pool

        if self._pool is not None and self._pool.closed:
            if self._owns_pool:
                self._pool = None
            else:
                msg = (
                    "StrangeLoop PostgreSQL backend: shared connection pool is closed "
                    "(daemon shutdown or pool closed elsewhere)."
                )
                raise RuntimeError(msg)

        # pool_size=0 means pool will be set externally (shared pool mode)
        if self.pool_size == 0:
            logger.debug("PostgreSQL backend in shared pool mode (awaiting external pool)")
            # Wait for pool to be set externally - raise error if not set
            raise RuntimeError("PostgreSQL backend in shared pool mode but pool not set")

        async with self._init_lock:
            if self._pool is not None:
                return self._pool

            # psycopg defaults min_size=4; cap min_size to max_size (e.g. reader_pool_size=2).
            from soothe.persistence.postgres_pool_lifecycle import apply_row_factory

            pool_kwargs: dict[str, Any] = {
                "max_size": self.pool_size,
                "open": False,
            }
            if self._pool_timing:
                pool_kwargs.update(self._pool_timing)
            else:
                pool_kwargs["min_size"] = min(4, self.pool_size)
                pool_kwargs["kwargs"] = {
                    "autocommit": True,
                    "prepare_threshold": 0,
                }
            pool = AsyncConnectionPool(self.dsn, **apply_row_factory(pool_kwargs))

            # Open pool and initialize schema
            await pool.open()
            await self._initialize_schema(pool)

            self._pool = pool
            logger.info(
                "StrangeLoop PostgreSQL backend initialized (soothe_checkpoints database, table=agentloop_checkpoints, pool=%d)",
                self.pool_size,
            )

            return self._pool

    async def _initialize_schema(self, pool: AsyncConnectionPool) -> None:
        """Recreate StrangeLoop tables using the canonical PostgreSQL schema."""
        await initialize_agentloop_postgres_schema(pool)

    async def _reset_pool_for_recovery(self) -> None:
        """Reset pool after connection error for retry.

        Called when recoverable connection errors occur (AdminShutdown, etc).
        """
        if self._shared_pool is not None:
            # Shared pool: reset via singleton
            from soothe.sloop.checkpoints.shared_pool import (
                SharedPostgreSQLPool,
            )

            await SharedPostgreSQLPool.reset_shared_instance()
            # Update our reference to the new pool
            self._pool = self._shared_pool.get_pool()
            logger.info("Reset shared pool for PostgreSQL recovery")
        elif self._owns_pool:
            # Owned pool: close and clear, will be recreated by _ensure_pool
            if self._pool is not None:
                try:
                    await self._pool.close()
                except Exception:
                    logger.debug("Error closing owned pool during reset", exc_info=True)
                self._pool = None
            logger.info("Reset owned pool for PostgreSQL recovery")
        else:
            # Shared pool mode but no shared_pool reference - cannot reset
            logger.error("Cannot reset pool: shared pool reference not available")

    async def _run_with_retry(
        self,
        action: str,
        op: Callable[[AsyncConnectionPool], Awaitable[Any]],
    ) -> Any:
        """Wrap operation with connection retry logic.

        Args:
            action: Action name for logging.
            op: Async operation that takes pool.

        Returns:
            Result from successful operation.
        """
        return await run_with_connection_retry(
            action=action,
            op=op,
            pool_getter=self._ensure_pool,
            pool_resetter=self._reset_pool_for_recovery,
        )

    async def save_checkpoint(
        self,
        checkpoint: StrangeLoopCheckpoint,
        *,
        write_mode: str = "full",
        hot_cold_enabled: bool = False,
    ) -> None:
        """Save StrangeLoop checkpoint to PostgreSQL with retry.

        Args:
            checkpoint: StrangeLoopCheckpoint to save.
            write_mode: `index_only` updates hot index only; `full` writes complete row.
            hot_cold_enabled: When True, also upsert cold blob table on full writes.
        """
        checkpoint_data = checkpoint.model_dump(mode="json")
        loop_id = checkpoint_data["loop_id"]
        thread_id = checkpoint_data["current_thread_id"]
        status = checkpoint_data["status"]

        from soothe.sloop.checkpoints.daemon_loop_metadata import (
            merge_checkpoint_with_preserved_metadata,
        )

        async def _checkpoint_data_with_daemon_metadata(
            cur: Any,
            data: dict[str, Any],
        ) -> dict[str, Any]:
            return await merge_checkpoint_with_preserved_metadata(cur, loop_id, data)

        if write_mode == "index_only" and hot_cold_enabled:
            from soothe.persistence.checkpoint_split import extract_hot_index

            hot_json = json.dumps(extract_hot_index(checkpoint))

            async def _do_save_index(pool: AsyncConnectionPool) -> None:
                async with pool.connection() as conn:
                    async with conn.cursor() as cur:
                        try:
                            await cur.execute(
                                """
                                UPDATE agentloop_checkpoints
                                SET thread_id = %s,
                                    status = %s,
                                    checkpoint_index = %s::jsonb,
                                    updated_at = NOW()
                                WHERE loop_id = %s
                                """,
                                (thread_id, status, hot_json, loop_id),
                            )
                            if cur.rowcount == 0:
                                merged = await merge_checkpoint_with_preserved_metadata(
                                    cur, loop_id, checkpoint_data
                                )
                                data_json = json.dumps(merged)
                                await cur.execute(
                                    """
                                    INSERT INTO agentloop_checkpoints
                                        (loop_id, thread_id, status, checkpoint_data,
                                         checkpoint_index, updated_at)
                                    VALUES (%s, %s, %s, %s, %s::jsonb, NOW())
                                    ON CONFLICT (loop_id) DO UPDATE SET
                                        thread_id = EXCLUDED.thread_id,
                                        status = EXCLUDED.status,
                                        checkpoint_index = EXCLUDED.checkpoint_index,
                                        updated_at = NOW()
                                    """,
                                    (loop_id, thread_id, status, data_json, hot_json),
                                )
                        except Exception as exc:
                            if not _is_missing_hot_cold_schema(exc):
                                raise
                            data_json = json.dumps(
                                await _checkpoint_data_with_daemon_metadata(cur, checkpoint_data)
                            )
                            await cur.execute(
                                """
                                INSERT INTO agentloop_checkpoints
                                    (loop_id, thread_id, status, checkpoint_data, updated_at)
                                VALUES (%s, %s, %s, %s, NOW())
                                ON CONFLICT (loop_id) DO UPDATE SET
                                    thread_id = EXCLUDED.thread_id,
                                    status = EXCLUDED.status,
                                    checkpoint_data = EXCLUDED.checkpoint_data,
                                    updated_at = NOW()
                                """,
                                (loop_id, thread_id, status, data_json),
                            )

            try:
                await self._run_with_retry("save_checkpoint_index", _do_save_index)
            except Exception as exc:
                if _is_missing_hot_cold_schema(exc):
                    hot_cold_enabled = False
                else:
                    raise
            if hot_cold_enabled:
                return

        hot_json = None
        cold_json = None
        if hot_cold_enabled:
            from soothe.persistence.checkpoint_split import (
                extract_cold_blob,
                extract_hot_index,
            )

            hot_json = json.dumps(extract_hot_index(checkpoint))
            cold_json = json.dumps(extract_cold_blob(checkpoint))

        async def _do_save(pool: AsyncConnectionPool) -> None:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    merged_checkpoint_data = await _checkpoint_data_with_daemon_metadata(
                        cur, checkpoint_data
                    )
                    data_json = json.dumps(merged_checkpoint_data)
                    if hot_json is not None:
                        await cur.execute(
                            """
                            INSERT INTO agentloop_checkpoints
                                (loop_id, thread_id, status, checkpoint_data,
                                 checkpoint_index, updated_at)
                            VALUES (%s, %s, %s, %s, %s::jsonb, NOW())
                            ON CONFLICT (loop_id) DO UPDATE SET
                                thread_id = EXCLUDED.thread_id,
                                status = EXCLUDED.status,
                                checkpoint_data = EXCLUDED.checkpoint_data,
                                checkpoint_index = EXCLUDED.checkpoint_index,
                                updated_at = NOW()
                            """,
                            (loop_id, thread_id, status, data_json, hot_json),
                        )
                        if cold_json is not None:
                            await cur.execute(
                                """
                                INSERT INTO agentloop_checkpoint_blobs
                                    (loop_id, cold_json, updated_at)
                                VALUES (%s, %s::jsonb, NOW())
                                ON CONFLICT (loop_id) DO UPDATE SET
                                    cold_json = EXCLUDED.cold_json,
                                    updated_at = NOW()
                                """,
                                (loop_id, cold_json),
                            )
                    else:
                        await cur.execute(
                            """
                            INSERT INTO agentloop_checkpoints (loop_id, thread_id, status, checkpoint_data, updated_at)
                            VALUES (%s, %s, %s, %s, NOW())
                            ON CONFLICT (loop_id)
                            DO UPDATE SET
                                thread_id = EXCLUDED.thread_id,
                                status = EXCLUDED.status,
                                checkpoint_data = EXCLUDED.checkpoint_data,
                                updated_at = NOW()
                        """,
                            (loop_id, thread_id, status, data_json),
                        )

        await self._run_with_retry("save_checkpoint", _do_save)

    async def load_checkpoint(self, loop_id: str) -> StrangeLoopCheckpoint | None:
        """Load StrangeLoop checkpoint from PostgreSQL.

        Args:
            loop_id: Loop identifier to load.

        Returns:
            StrangeLoopCheckpoint if found, None otherwise.
        """
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                row = None
                try:
                    await cur.execute(
                        """
                        SELECT checkpoint_data, checkpoint_index
                        FROM agentloop_checkpoints WHERE loop_id = %s
                    """,
                        (loop_id,),
                    )
                    row = await cur.fetchone()
                except Exception as exc:
                    if not _is_missing_hot_cold_schema(exc):
                        raise
                    await cur.execute(
                        """
                        SELECT checkpoint_data
                        FROM agentloop_checkpoints WHERE loop_id = %s
                    """,
                        (loop_id,),
                    )
                    row = await cur.fetchone()

                if not row:
                    return None

                from soothe.persistence.checkpoint_split import merge_hot_into_checkpoint
                from soothe.sloop.state.checkpoint import (
                    StrangeLoopCheckpoint,
                    normalize_checkpoint_data,
                )

                checkpoint_data = normalize_checkpoint_data(
                    dict(row["checkpoint_data"]),
                    loop_id=loop_id,
                )
                hot_index = row.get("checkpoint_index")
                if hot_index is not None:
                    if not isinstance(hot_index, dict):
                        hot_index = dict(hot_index)
                    checkpoint_data = merge_hot_into_checkpoint(checkpoint_data, hot_index)

                cold_row = None
                try:
                    await cur.execute(
                        """
                        SELECT cold_json FROM agentloop_checkpoint_blobs
                        WHERE loop_id = %s
                        """,
                        (loop_id,),
                    )
                    cold_row = await cur.fetchone()
                except Exception:
                    cold_row = None

                if cold_row is not None:
                    cold = cold_row["cold_json"]
                    if not isinstance(cold, dict):
                        cold = dict(cold)
                    checkpoint_data.update(cold)

                return StrangeLoopCheckpoint.model_validate(checkpoint_data)

    async def close(self) -> None:
        """Close connection pool.

        Only closes pool if this backend owns it (not shared).
        Shared pools are closed at daemon shutdown level.
        """
        if self._pool and self._owns_pool:
            await self._pool.close()
            self._pool = None
            logger.debug("Closed PostgreSQL backend pool (owned)")
            self._pool = None
            logger.info("StrangeLoop PostgreSQL backend closed")

    # Implement abstract interface methods

    async def register_loop(
        self,
        loop_id: str,
        current_thread_id: str,
        status: str = "running",
    ) -> None:
        """Register new StrangeLoop in database with retry.

        Args:
            loop_id: StrangeLoop identifier.
            current_thread_id: Current active thread ID (== loop_id).
            status: Loop status (default: "running").
        """
        checkpoint_data = {
            "loop_id": loop_id,
            "current_thread_id": current_thread_id,
            "status": status,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        data_json = json.dumps(checkpoint_data)

        async def _do_register(pool: AsyncConnectionPool) -> None:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO agentloop_checkpoints (loop_id, thread_id, status, checkpoint_data, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, NOW(), NOW())
                        ON CONFLICT (loop_id)
                        DO UPDATE SET
                            thread_id = EXCLUDED.thread_id,
                            status = EXCLUDED.status,
                            checkpoint_data = EXCLUDED.checkpoint_data,
                            updated_at = NOW()
                    """,
                        (loop_id, current_thread_id, status, data_json),
                    )
                    logger.debug("Registered loop: loop=%s thread=%s", loop_id, current_thread_id)

        await self._run_with_retry("register_loop", _do_register)

    async def get_loop_metadata(self, loop_id: str) -> dict | None:
        """Get loop metadata for daemon reconstruction.

        Args:
            loop_id: Loop identifier.

        Returns:
            Loop metadata dict if found, None otherwise.
        """
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT checkpoint_data, client_workspace, detached_at,
                           created_at, updated_at
                    FROM agentloop_checkpoints WHERE loop_id = %s
                """,
                    (loop_id,),
                )

                result = await cur.fetchone()
                if not result:
                    return None

                data = dict(result["checkpoint_data"]) if result["checkpoint_data"] else {}
                data["loop_id"] = loop_id
                # Top-level columns take precedence over JSONB blob values
                if result["client_workspace"] is not None:
                    data["client_workspace"] = result["client_workspace"]
                if result["detached_at"] is not None:
                    data["detached_at"] = (
                        result["detached_at"].isoformat()
                        if hasattr(result["detached_at"], "isoformat")
                        else result["detached_at"]
                    )
                if result["created_at"] is not None:
                    data["created_at"] = (
                        result["created_at"].isoformat()
                        if hasattr(result["created_at"], "isoformat")
                        else result["created_at"]
                    )
                if result["updated_at"] is not None:
                    data["updated_at"] = (
                        result["updated_at"].isoformat()
                        if hasattr(result["updated_at"], "isoformat")
                        else result["updated_at"]
                    )
                return data

    async def update_loop_metadata(
        self, loop_id: str, *, force_status: bool = False, **fields: Any
    ) -> None:
        """Partially update loop metadata fields with retry.

        `status` is owned by `StrangeLoop` once the loop has any
        `goal_history`. Status writes from the daemon path (pre-query
        bookkeeping) are silently dropped for established loops to avoid
        clobbering `finalize_goal`'s `"idle"` back to `"running"`,
        which would cause StrangeLoop to take the invalid-index re-init path
        and lose prior goal context. Status writes are honored only when
        the loop has no goals yet (initial registration / bind).

        Args:
            loop_id: Loop identifier.
            force_status: When True, bypass the goal-count guard so
                the stale-loop reconciler can demote a confirmed-dead zombie
                loop to `idle` even when it already has goals.
            **fields: Column names and values to update.
        """
        _allowed = {
            "status",
            "current_thread_id",
            "client_workspace",
            "client_workspace_id",
            "user_id",
            "detached_at",
            "total_goals_completed",
            "total_thread_switches",
            "total_duration_ms",
            "total_tokens_used",
            "is_ephemeral",
            "last_message_at",
            "current_workspace",
            "resume_topic",
            "workspace_mapping",
        }
        updates = {k: v for k, v in fields.items() if k in _allowed}
        if not updates:
            return

        async def _do_update(pool: AsyncConnectionPool) -> None:
            # RFC-225: drop ``status`` from external metadata writes when the loop
            # already has goals. StrangeLoop is the authoritative writer in that case.
            # ``force_status`` bypasses this for the stale-loop reconciler, which
            # must demote confirmed-dead zombies that would otherwise linger.
            local_updates = updates.copy()
            if "status" in local_updates and not force_status:
                async with pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            SELECT jsonb_array_length(
                                       COALESCE(checkpoint_data->'goal_history', '[]'::jsonb)
                                   ) AS history_len
                            FROM agentloop_checkpoints
                            WHERE loop_id = %s
                            """,
                            (loop_id,),
                        )
                        row = await cur.fetchone()
                        history_len = (
                            int(row["history_len"])
                            if row and row.get("history_len") is not None
                            else 0
                        )
                if history_len > 0:
                    local_updates.pop("status", None)
                    if not local_updates:
                        return

            # Merge scalar fields into checkpoint_data JSONB blob and update top-level columns
            jsonb_updates = {k: v for k, v in local_updates.items()}

            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE agentloop_checkpoints
                        SET checkpoint_data = checkpoint_data || %s::jsonb,
                            thread_id = COALESCE(%s, thread_id),
                            status = COALESCE(%s, status),
                            client_workspace = COALESCE(%s::text, client_workspace),
                            detached_at = COALESCE(%s::timestamptz, detached_at),
                            updated_at = NOW()
                        WHERE loop_id = %s
                        """,
                        (
                            json.dumps(jsonb_updates),
                            local_updates.get("current_thread_id"),
                            local_updates.get("status"),
                            local_updates.get("client_workspace"),
                            local_updates.get("detached_at"),
                            loop_id,
                        ),
                    )

        await self._run_with_retry("update_loop_metadata", _do_update)

    async def mark_running_goals_failed(self, loop_id: str) -> int:
        """Mark a loop's still-`running` goal_records as `failed`.

        Called by the stale-loop reconciler alongside a force-demote of the
        loop row to `idle`. A crashed loop may leave goals stuck in the
        `running` state with no `completed_at`; this closes them so the
        goal DAG reflects reality instead of lingering forever.

        Returns the count of goal rows updated.
        """

        async def _do_mark(pool: AsyncConnectionPool) -> int:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE goal_records
                        SET status = 'failed', completed_at = NOW()
                        WHERE loop_id = %s AND status = 'running'
                        """,
                        (loop_id,),
                    )
                    return int(cur.rowcount or 0)

        return await self._run_with_retry("mark_running_goals_failed", _do_mark)

    async def set_resume_topic_once(self, loop_id: str, topic: str) -> bool:
        """Write resume topic only when checkpoint_data has no topic yet."""
        cleaned = topic.strip()

        async def _do_set(pool: AsyncConnectionPool) -> bool:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE agentloop_checkpoints
                        SET checkpoint_data = checkpoint_data || %s::jsonb,
                            updated_at = NOW()
                        WHERE loop_id = %s
                          AND COALESCE(checkpoint_data->>'resume_topic', '') = ''
                        """,
                        (json.dumps({"resume_topic": cleaned}), loop_id),
                    )
                    return bool(cur.rowcount)

        return await self._run_with_retry("set_resume_topic_once", _do_set)

    async def list_loops(
        self,
        status_filter: str | None = None,
        limit: int = 100,
        exclude_empty: bool = False,
        workspace_filter: str | None = None,
    ) -> list[dict]:
        """Return summary rows for all loops, ordered by created_at DESC.

        Args:
            status_filter: Optional status value to filter by.
            limit: Maximum rows to return.
            exclude_empty: When True, hide loops with zero human and zero AI
                messages (bootstrap-only loops with no real exchange).
            workspace_filter: Optional client_workspace path to filter by.
        """
        pool = await self._ensure_pool()

        clauses: list[str] = []
        params: list[Any] = []
        if status_filter:
            clauses.append("status = %s")
            params.append(status_filter)
        if workspace_filter:
            clauses.append("client_workspace = %s")
            params.append(workspace_filter)
        if exclude_empty:
            clauses.append(
                "(COALESCE((checkpoint_data->>'human_message_count')::int, 0) > 0"
                " OR COALESCE((checkpoint_data->>'ai_message_count')::int, 0) > 0)"
            )
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        sql = f"""
            SELECT loop_id, status,
                   thread_id AS current_thread_id,
                   COALESCE((checkpoint_data->>'total_goals_completed')::int, 0)
                       AS total_goals_completed,
                   COALESCE((checkpoint_data->>'total_thread_switches')::int, 0)
                       AS total_thread_switches,
                   COALESCE((checkpoint_data->>'human_message_count')::int, 0)
                       AS human_message_count,
                   COALESCE((checkpoint_data->>'ai_message_count')::int, 0)
                       AS ai_message_count,
                   checkpoint_data->>'last_message_at' AS last_message_at,
                   checkpoint_data->>'resume_topic' AS resume_topic,
                   created_at, updated_at, client_workspace, detached_at
            FROM agentloop_checkpoints
            {where_sql}
            ORDER BY created_at DESC
            LIMIT %s
        """  # noqa: S608 — only static SQL fragments interpolated.

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                rows = await cur.fetchall()

        result = []
        for row in rows:
            created = row.get("created_at")
            updated = row.get("updated_at")
            detached = row.get("detached_at")
            result.append(
                {
                    "loop_id": row["loop_id"],
                    "status": row["status"],
                    "current_thread_id": row["current_thread_id"],
                    "total_goals_completed": row["total_goals_completed"],
                    "total_thread_switches": row["total_thread_switches"],
                    "human_message_count": row["human_message_count"],
                    "ai_message_count": row["ai_message_count"],
                    "last_message_at": row.get("last_message_at"),
                    "resume_topic": row.get("resume_topic"),
                    "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
                    "updated_at": updated.isoformat() if hasattr(updated, "isoformat") else updated,
                    "client_workspace": row.get("client_workspace"),
                    "detached_at": detached.isoformat()
                    if hasattr(detached, "isoformat")
                    else detached,
                }
            )
        return result

    async def touch_loop_last_message(self, loop_id: str) -> None:
        """Record user turn activity for ephemeral loop TTL."""
        now = datetime.now(UTC).isoformat()
        await self.update_loop_metadata(loop_id, last_message_at=now)

    async def heartbeat_loop(self, loop_id: str) -> None:
        """Bump `updated_at` so periodic status reconciliation can trust freshness."""

        async def _do_heartbeat(pool: AsyncConnectionPool) -> None:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE agentloop_checkpoints SET updated_at = NOW() WHERE loop_id = %s",
                        (loop_id,),
                    )

        await self._run_with_retry("heartbeat_loop", _do_heartbeat)

    async def increment_loop_message_count(
        self,
        loop_id: str,
        human: int = 0,
        ai: int = 0,
    ) -> None:
        """Atomically increment counters inside `checkpoint_data` JSONB with retry.

        Counters live in the JSONB blob for parity with other per-loop scalars
        (`is_ephemeral`, `last_message_at`, `total_goals_completed`). Single
        UPDATE per call; no read-modify-write.
        """
        if human == 0 and ai == 0:
            return
        now = datetime.now(UTC).isoformat()

        async def _do_increment(pool: AsyncConnectionPool) -> None:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE agentloop_checkpoints
                        SET checkpoint_data = checkpoint_data
                            || jsonb_build_object(
                                'human_message_count',
                                COALESCE((checkpoint_data->>'human_message_count')::int, 0) + %s,
                                'ai_message_count',
                                COALESCE((checkpoint_data->>'ai_message_count')::int, 0) + %s,
                                'last_message_at', %s::text
                            ),
                            updated_at = NOW()
                        WHERE loop_id = %s
                        """,
                        (human, ai, now, loop_id),
                    )

        await self._run_with_retry("increment_loop_message_count", _do_increment)

    async def list_expired_ephemeral_loops(
        self,
        idle_before: datetime,
        limit: int = 50,
    ) -> list[dict]:
        """Return ephemeral loops idle since `idle_before`.

        Includes rows still marked `status="running"`: the GC purge gate
        performs a live-runner check (`_loop_has_active_runner`), so a
        stale `running` status (zombie) is reclaimable.
        """
        idle_iso = idle_before.isoformat()
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT loop_id, status, thread_id AS current_thread_id,
                           checkpoint_data, client_workspace, created_at, updated_at
                    FROM agentloop_checkpoints
                    WHERE COALESCE((checkpoint_data->>'is_ephemeral')::boolean, false) = true
                      AND COALESCE(
                            checkpoint_data->>'last_message_at',
                            checkpoint_data->>'created_at',
                            created_at::text
                          ) < %s
                    ORDER BY COALESCE(
                        checkpoint_data->>'last_message_at',
                        checkpoint_data->>'created_at',
                        created_at::text
                    ) ASC
                    LIMIT %s
                    """,
                    (idle_iso, limit),
                )
                rows = await cur.fetchall()

        result: list[dict] = []
        for row in rows:
            data = dict(row["checkpoint_data"]) if row.get("checkpoint_data") else {}
            result.append(
                {
                    "loop_id": row["loop_id"],
                    "current_thread_id": row.get("current_thread_id")
                    or data.get("current_thread_id"),
                    "status": row["status"],
                    "client_workspace": row.get("client_workspace") or data.get("client_workspace"),
                    "current_workspace": data.get("current_workspace"),
                    "user_id": data.get("user_id"),
                    "client_workspace_id": data.get("client_workspace_id"),
                    "last_message_at": data.get("last_message_at"),
                    "created_at": data.get("created_at"),
                    "is_ephemeral": True,
                }
            )
        return result

    async def list_empty_loops(
        self,
        idle_before: datetime,
        limit: int = 50,
    ) -> list[dict]:
        """Return loops with zero human/AI messages idle since `idle_before`.

        Includes rows still marked `status="running"`: the GC purge gate
        performs a live-runner check (`_loop_has_active_runner`), so a
        stale `running` status (zombie) is reclaimable.
        """
        idle_iso = idle_before.isoformat()
        pool = await self._ensure_pool()

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT loop_id, status, thread_id AS current_thread_id,
                           checkpoint_data, client_workspace, created_at, updated_at
                    FROM agentloop_checkpoints
                    WHERE COALESCE((checkpoint_data->>'human_message_count')::int, 0) = 0
                      AND COALESCE((checkpoint_data->>'ai_message_count')::int, 0) = 0
                      AND COALESCE(
                            checkpoint_data->>'last_message_at',
                            checkpoint_data->>'created_at',
                            created_at::text
                          ) < %s
                    ORDER BY COALESCE(
                        checkpoint_data->>'last_message_at',
                        checkpoint_data->>'created_at',
                        created_at::text
                    ) ASC
                    LIMIT %s
                    """,
                    (idle_iso, limit),
                )
                rows = await cur.fetchall()

        result: list[dict] = []
        for row in rows:
            data = dict(row["checkpoint_data"]) if row.get("checkpoint_data") else {}
            result.append(
                {
                    "loop_id": row["loop_id"],
                    "current_thread_id": row.get("current_thread_id")
                    or data.get("current_thread_id"),
                    "status": row["status"],
                    "client_workspace": row.get("client_workspace") or data.get("client_workspace"),
                    "current_workspace": data.get("current_workspace"),
                    "user_id": data.get("user_id"),
                    "client_workspace_id": data.get("client_workspace_id"),
                    "last_message_at": data.get("last_message_at"),
                    "created_at": data.get("created_at"),
                    "is_ephemeral": bool(data.get("is_ephemeral", False)),
                }
            )
        return result

    async def purge_loop_execution_data(self, loop_id: str) -> None:
        """Delete loop row and related execution tables with retry."""

        async def _do_purge(pool: AsyncConnectionPool) -> None:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("DELETE FROM goal_records WHERE loop_id = %s", (loop_id,))
                    await cur.execute(
                        "DELETE FROM agentloop_checkpoints WHERE loop_id = %s", (loop_id,)
                    )
            logger.info("Purged loop execution data from PostgreSQL: loop=%s", loop_id)

        await self._run_with_retry("purge_loop_execution_data", _do_purge)

    async def save_goal_record(
        self,
        goal_id: str,
        loop_id: str,
        thread_id: str,
        status: str,
        started_at: str,
    ) -> None:
        """Save goal index entry with retry."""
        started_dt = datetime.fromisoformat(started_at)

        async def _do_save_goal(pool: AsyncConnectionPool) -> None:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO goal_records
                        (goal_id, loop_id, thread_id, status, started_at)
                        VALUES (%s, %s, %s, %s, %s)
                    """,
                        (goal_id, loop_id, thread_id, status, started_dt),
                    )
                    logger.debug(
                        "Saved goal: id=%s loop=%s thread=%s status=%s",
                        goal_id,
                        loop_id,
                        thread_id,
                        status,
                    )

        await self._run_with_retry("save_goal_record", _do_save_goal)

    async def update_goal_record(
        self,
        goal_id: str,
        loop_id: str,
        status: str,
        duration_ms: int,
        tokens_used: int,
        completed_at: str | None,
    ) -> None:
        """Update goal index entry with retry."""
        completed_dt = datetime.fromisoformat(completed_at) if completed_at else None

        async def _do_update_goal(pool: AsyncConnectionPool) -> None:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE goal_records
                        SET status = %s,
                            duration_ms = %s,
                            tokens_used = %s,
                            completed_at = %s
                        WHERE goal_id = %s AND loop_id = %s
                    """,
                        (
                            status,
                            duration_ms,
                            tokens_used,
                            completed_dt,
                            goal_id,
                            loop_id,
                        ),
                    )
                    logger.debug(
                        "Updated goal: id=%s loop=%s status=%s dur=%dms",
                        goal_id,
                        loop_id,
                        status,
                        duration_ms,
                    )

        await self._run_with_retry("update_goal_record", _do_update_goal)
