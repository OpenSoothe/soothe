"""StrangeLoop checkpoint persistence manager."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from soothe.sloop.checkpoints.shared_pool import (
    acquire_shared_sqlite_backend_sync,
    release_shared_sqlite_backend,
)

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class StrangeLoopCheckpointPersistenceManager:
    """Manager for StrangeLoop checkpoint persistence.

    Backend-agnostic delegation pattern.
    Respects persistence.default_backend configuration (PostgreSQL or SQLite).
    """

    def __init__(
        self,
        config: SootheConfig | None = None,
        *,
        display_loop_purger: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize persistence manager with backend selection.

        Args:
            config: SootheConfig for backend selection. If None, uses SQLite.
            display_loop_purger: Optional callable that purges a loop's display
                card data (`delete_loop(loop_id)`). Injected by the daemon,
                which owns the display card store (PR-2). No-op when None
                (keeps the host free of daemon imports).
        """
        self._display_loop_purger = display_loop_purger
        # Determine backend type
        backend_type = "sqlite"
        if config and config.persistence.default_backend == "postgresql":
            backend_type = "postgresql"

        # Initialize backend instance
        self._uses_shared_sqlite = False
        self._uses_shared_postgres = False
        if backend_type == "postgresql":
            try:
                from soothe.persistence.postgres_pool_lifecycle import (
                    postgres_pool_timing_from_config,
                )
                from soothe.sloop.checkpoints.postgres_backend import (
                    PostgreSQLPersistenceBackend,
                )
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "PostgreSQL persistence backend requires `psycopg`. "
                    "Install with: pip install -U soothe"
                ) from exc
            dsn = config.resolve_postgres_dsn_for_database("checkpoints")
            pool_size = config.persistence.postgres.metadata_pool_size
            pool_timing = postgres_pool_timing_from_config(config, max_size=pool_size)
            self._backend = PostgreSQLPersistenceBackend(
                dsn=dsn,
                pool_size=pool_size,
                pool_timing=pool_timing,
            )
        else:
            self._backend = acquire_shared_sqlite_backend_sync()
            self._uses_shared_sqlite = True

        logger.debug("StrangeLoop persistence manager initialized: backend=%s", backend_type)

    @classmethod
    async def for_shared_checkpoint_pool(
        cls,
        config: SootheConfig,
        *,
        display_loop_purger: Callable[[str], None] | None = None,
    ) -> StrangeLoopCheckpointPersistenceManager:
        """Build a manager backed by the process-wide checkpoint pool.

        Ephemeral callers (heartbeat ticks, deferred counters, resume topic)
        must use this instead of constructing an owned `AsyncConnectionPool`
        per call.
        """
        if config.persistence.default_backend != "postgresql":
            return cls(config=config, display_loop_purger=display_loop_purger)

        from soothe.sloop.checkpoints.postgres_backend import (
            PostgreSQLPersistenceBackend,
        )
        from soothe.sloop.checkpoints.shared_pool import (
            SharedPostgreSQLPool,
        )

        shared = await SharedPostgreSQLPool.get_shared_instance(config)
        if shared is None:
            return cls(config=config)

        # IG-706: Wait for any in-flight reset_pool reopen to finish. reset_pool
        # nulls _pool before reopening (close + open + schema), so a snapshot via
        # get_pool() can transiently observe None mid-recovery — the original
        # "Shared checkpoint pool not initialized" failure (loop 0041).
        pool = await shared.await_pool()
        if pool is None:
            msg = "Shared checkpoint pool not initialized"
            raise RuntimeError(msg)

        dsn = config.resolve_postgres_dsn_for_database("checkpoints")
        manager = cls.__new__(cls)
        manager._uses_shared_sqlite = False
        manager._uses_shared_postgres = True
        manager._display_loop_purger = display_loop_purger
        manager._backend = PostgreSQLPersistenceBackend(
            dsn=dsn,
            pool_size=0,
            shared_pool=shared,
        )
        manager._backend._pool = pool
        return manager

    async def register_loop(
        self,
        loop_id: str,
        current_thread_id: str,
        status: str = "running",
    ) -> None:
        """Register a new StrangeLoop in the database.

        Args:
            loop_id: StrangeLoop identifier.
            current_thread_id: Current active thread ID (== loop_id).
            status: Loop status (default: "running").
        """
        await self._backend.register_loop(loop_id, current_thread_id, status)
        logger.debug("Registered loop: loop=%s current=%s", loop_id, current_thread_id)

    async def get_loop_metadata(self, loop_id: str) -> dict | None:
        """Get loop metadata from database.

        Args:
            loop_id: Loop identifier.

        Returns:
            Loop metadata dict if found, None otherwise.
        """
        return await self._backend.get_loop_metadata(loop_id)

    async def update_loop_metadata(
        self, loop_id: str, *, force_status: bool = False, **fields: Any
    ) -> None:
        """Partially update loop metadata fields.

        Args:
            loop_id: Loop identifier.
            force_status: When True, bypass the goal-count guard so
                an authoritative caller (stale-loop reconciler) can demote a
                confirmed-dead zombie loop's `status` even when it has goals.
            **fields: Column names and values to update.
        """
        await self._backend.update_loop_metadata(loop_id, force_status=force_status, **fields)

    async def mark_running_goals_failed(self, loop_id: str) -> int:
        """Mark a loop's still-`running` goal_records as `failed`.

        Returns the count of goal rows updated. Used by the stale-loop
        reconciler to close goals orphaned by a crashed runner.
        """
        return await self._backend.mark_running_goals_failed(loop_id)

    async def set_resume_topic_once(self, loop_id: str, topic: str) -> bool:
        """Persist resume topic only when the loop has no stored topic yet.

        Args:
            loop_id: Loop identifier.
            topic: Generated topic label.

        Returns:
            True when the topic was written, False when one already existed.
        """
        setter = getattr(self._backend, "set_resume_topic_once", None)
        if setter is None:
            metadata = await self.get_loop_metadata(loop_id)
            existing = (metadata or {}).get("resume_topic")
            if isinstance(existing, str) and existing.strip():
                return False
            await self.update_loop_metadata(loop_id, resume_topic=topic.strip())
            return True
        return await setter(loop_id, topic)

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

        Returns:
            List of loop metadata dicts.
        """
        return await self._backend.list_loops(
            status_filter=status_filter,
            limit=limit,
            exclude_empty=exclude_empty,
            workspace_filter=workspace_filter,
        )

    async def touch_loop_last_message(self, loop_id: str) -> None:
        """Record user turn activity for ephemeral loop TTL."""
        await self._backend.touch_loop_last_message(loop_id)

    async def heartbeat_loop(self, loop_id: str) -> None:
        """Bump `updated_at` for periodic status reconciliation."""
        await self._backend.heartbeat_loop(loop_id)

    async def increment_loop_message_count(
        self,
        loop_id: str,
        human: int = 0,
        ai: int = 0,
    ) -> None:
        """Atomically bump human/AI message counters and refresh activity timestamp."""
        await self._backend.increment_loop_message_count(loop_id, human=human, ai=ai)

    async def list_expired_ephemeral_loops(
        self,
        idle_before: datetime,
        limit: int = 50,
    ) -> list[dict]:
        """Return ephemeral loops idle since `idle_before`.

        Includes stale `running` rows; the GC purge gate performs a
        live-runner check to protect truly active loops.
        """
        return await self._backend.list_expired_ephemeral_loops(idle_before, limit)

    async def list_empty_loops(
        self,
        idle_before: datetime,
        limit: int = 50,
    ) -> list[dict]:
        """Return loops with zero human/AI messages idle since `idle_before`.

        Includes stale `running` rows; the GC purge gate performs a
        live-runner check to protect truly active loops.
        """
        return await self._backend.list_empty_loops(idle_before, limit)

    async def purge_loop_execution_data(self, loop_id: str) -> None:
        """Delete loop row and related execution tables (keeps workspace dirs)."""
        import asyncio

        from soothe.context.store_sqlite import (
            purge_loop_context_engine_state,
        )

        await self._backend.purge_loop_execution_data(loop_id)
        if self._display_loop_purger is not None:
            await asyncio.to_thread(self._display_loop_purger, loop_id)
        await asyncio.to_thread(purge_loop_context_engine_state, loop_id)
        logger.info("Purged loop execution data: loop=%s", loop_id)

    async def save_goal_record(
        self,
        goal_id: str,
        loop_id: str,
        thread_id: str,
        status: str = "running",
        started_at: datetime | None = None,
    ) -> None:
        """Save goal index entry."""
        started_at_iso = (started_at or datetime.now(UTC)).isoformat()
        await self._backend.save_goal_record(goal_id, loop_id, thread_id, status, started_at_iso)
        logger.debug(
            "Saved goal: id=%s loop=%s thread=%s status=%s",
            goal_id,
            loop_id,
            thread_id,
            status,
        )

    async def update_goal_record(
        self,
        goal_id: str,
        loop_id: str,
        status: str = "completed",
        duration_ms: int = 0,
        tokens_used: int = 0,
        completed_at: datetime | None = None,
    ) -> None:
        """Update goal index entry with execution metrics."""
        completed_at_iso = (completed_at or datetime.now(UTC)).isoformat()
        await self._backend.update_goal_record(
            goal_id,
            loop_id,
            status,
            duration_ms,
            tokens_used,
            completed_at_iso,
        )
        logger.debug(
            "Updated goal: id=%s loop=%s status=%s dur=%dms",
            goal_id,
            loop_id,
            status,
            duration_ms,
        )

    async def close(self) -> None:
        """Close backend connection pools (prevent pool exhaustion).

        Must be called when manager is no longer needed to release database connections.
        Critical for concurrent execution where multiple managers may exist.
        """
        if self._uses_shared_sqlite:
            await release_shared_sqlite_backend()
            logger.debug("Released shared SQLite persistence backend reference")
            return
        if self._uses_shared_postgres:
            self._backend = None
            logger.debug("Released shared PostgreSQL persistence backend reference")
            return
        if hasattr(self._backend, "close"):
            await self._backend.close()
            logger.debug("Closed persistence backend pool")


__all__ = ["StrangeLoopCheckpointPersistenceManager"]
