"""Unified high-performance loop persistence writer (IG-550).

Process-scoped singleton coalescing checkpoint and ContextEngine writes onto a
shared PostgreSQL pool with bounded shutdown and goal-boundary transactions.

IG-571: asyncio tasks and loop-bound locks run on a single bound event loop
(typically the daemon main loop). Worker threads call ``submit_*`` to schedule
work via ``asyncio.run_coroutine_threadsafe``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypeVar

from soothe.foundation.persistence.checkpoint_split import (
    clear_persist_degraded,
    extract_cold_blob,
    extract_hot_index,
    mark_persist_degraded,
)
from soothe.foundation.persistence.persist_metrics import log_pending_loops, persist_timer

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.foundation.context.models import GoalStepDAG
    from soothe.foundation.sloop.state.checkpoint import StrangeLoopCheckpoint
    from soothe.foundation.sloop.state.persistence.shared_pool import SharedPostgreSQLPool

logger = logging.getLogger(__name__)

T = TypeVar("T")

_writer_singleton: LoopPersistenceWriter | None = None
_writer_init_lock = threading.Lock()


class PersistWriteMode(StrEnum):
    """Checkpoint write granularity."""

    INDEX_ONLY = "index_only"
    FULL = "full"


@dataclass
class PersistResult:
    """Outcome of a durable goal-boundary persist."""

    ok: bool
    failures: list[str] = field(default_factory=list)
    duration_ms: int = 0


@dataclass
class _PendingEntry:
    checkpoint: StrangeLoopCheckpoint
    durable: bool = False
    write_mode: PersistWriteMode = PersistWriteMode.INDEX_ONLY


class LoopPersistenceWriter:
    """Coalescing persistence writer keyed by loop_id."""

    _bound_loop: asyncio.AbstractEventLoop | None = None

    def __init__(
        self,
        *,
        shared_pool: SharedPostgreSQLPool,
        flush_interval: float = 5.0,
        close_timeout_seconds: float = 30.0,
        durable_flush_timeout: float = 10.0,
    ) -> None:
        self._shared_pool = shared_pool
        self._flush_interval = flush_interval
        self._close_timeout_seconds = close_timeout_seconds
        self._durable_flush_timeout = durable_flush_timeout

        self._pending: dict[str, _PendingEntry] = {}
        self._pending_guard = threading.Lock()
        self._durable_event = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._paused = False
        self._inflight = 0
        self._inflight_done = asyncio.Event()
        self._inflight_done.set()
        self._write_lock = asyncio.Lock()
        self._released_loops: set[str] = set()

    @classmethod
    def bind_main_loop(cls, loop: asyncio.AbstractEventLoop) -> None:
        """Pin writer asyncio primitives to ``loop`` (daemon main loop in thread_pool)."""
        cls._bound_loop = loop
        logger.debug("LoopPersistenceWriter bound to event loop %s", loop)

    @classmethod
    def existing_instance(cls) -> LoopPersistenceWriter | None:
        """Return the process singleton if already initialized."""
        return _writer_singleton

    @classmethod
    async def get_shared_instance(
        cls,
        config: SootheConfig,
        *,
        shared_pool: SharedPostgreSQLPool | None = None,
    ) -> LoopPersistenceWriter | None:
        """Return process singleton when unified writer is enabled for PostgreSQL."""
        global _writer_singleton

        if config.persistence.default_backend != "postgresql":
            return None

        if _writer_singleton is not None:
            return _writer_singleton

        with _writer_init_lock:
            if _writer_singleton is not None:
                return _writer_singleton

            if shared_pool is None:
                from soothe.foundation.sloop.state.persistence.shared_pool import (
                    SharedPostgreSQLPool,
                )

                shared_pool = await SharedPostgreSQLPool.get_shared_instance(config)
            if shared_pool is None:
                return None

            checkpoint_cfg = config.agent.loop.concurrency.checkpoint
            _writer_singleton = cls(
                shared_pool=shared_pool,
                flush_interval=checkpoint_cfg.flush_interval,
                close_timeout_seconds=checkpoint_cfg.close_timeout_seconds,
                durable_flush_timeout=checkpoint_cfg.durable_flush_timeout,
            )

        await _writer_singleton._run_on_main(_writer_singleton._ensure_worker)
        return _writer_singleton

    @classmethod
    async def close_shared_instance(cls) -> None:
        """Stop shared writer worker at daemon shutdown."""
        global _writer_singleton
        with _writer_init_lock:
            inst = _writer_singleton
            _writer_singleton = None
        if inst is None:
            return
        await inst._run_on_main(inst.shutdown)

    async def _run_on_main(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, T]],
    ) -> T:
        """Run ``coro_factory`` on the bound writer loop; await from any caller loop."""
        running = asyncio.get_running_loop()
        bound = type(self)._bound_loop
        if bound is None:
            type(self)._bound_loop = running
            bound = running
        if bound is running:
            return await coro_factory()
        future = asyncio.run_coroutine_threadsafe(coro_factory(), bound)
        return await asyncio.wrap_future(future)

    async def submit_enqueue(
        self,
        loop_id: str,
        checkpoint: StrangeLoopCheckpoint,
        *,
        durable: bool = False,
        write_mode: PersistWriteMode = PersistWriteMode.INDEX_ONLY,
    ) -> None:
        """Thread-safe enqueue from any event loop."""
        await self._run_on_main(
            lambda: self.enqueue_checkpoint(
                loop_id,
                checkpoint,
                durable=durable,
                write_mode=write_mode,
            )
        )

    async def submit_flush_durable(self, loop_id: str, *, timeout: float) -> PersistResult:
        """Thread-safe durable flush from any event loop."""
        return await self._run_on_main(lambda: self.flush_durable(loop_id, timeout=timeout))

    async def submit_persist_goal_boundary(
        self,
        loop_id: str,
        *,
        checkpoint: StrangeLoopCheckpoint,
        dag: GoalStepDAG | None = None,
        ledger: list[dict[str, Any]] | None = None,
    ) -> PersistResult:
        """Thread-safe goal-boundary persist from any event loop."""
        return await self._run_on_main(
            lambda: self.persist_goal_boundary(
                loop_id,
                checkpoint=checkpoint,
                dag=dag,
                ledger=ledger,
            )
        )

    async def submit_release_loop(self, loop_id: str, *, timeout: float | None = None) -> None:
        """Thread-safe bounded loop release from any event loop."""
        await self._run_on_main(lambda: self.release_loop(loop_id, timeout=timeout))

    async def submit_save_ce_dag(self, loop_id: str, dag: GoalStepDAG) -> None:
        """Thread-safe CE DAG persist from any event loop."""
        await self._run_on_main(lambda: self.save_ce_dag(loop_id, dag))

    async def submit_save_ce_ledger(self, loop_id: str, messages: list[dict[str, Any]]) -> None:
        """Thread-safe CE ledger persist from any event loop."""
        await self._run_on_main(lambda: self.save_ce_ledger(loop_id, messages))

    async def _ensure_worker(self) -> None:
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(
            self._flush_worker_loop(),
            name="loop-persistence-writer",
        )

    async def shutdown(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def enqueue_checkpoint(
        self,
        loop_id: str,
        checkpoint: StrangeLoopCheckpoint,
        *,
        durable: bool = False,
        write_mode: PersistWriteMode = PersistWriteMode.INDEX_ONLY,
    ) -> None:
        """Enqueue or coalesce a checkpoint write (bound writer loop only)."""
        if loop_id in self._released_loops and not durable:
            return

        with self._pending_guard:
            existing = self._pending.get(loop_id)
            if existing is not None and not durable:
                existing.checkpoint = checkpoint
                if write_mode == PersistWriteMode.FULL:
                    existing.write_mode = PersistWriteMode.FULL
            else:
                self._pending[loop_id] = _PendingEntry(
                    checkpoint=checkpoint,
                    durable=durable,
                    write_mode=write_mode if durable else PersistWriteMode.INDEX_ONLY,
                )
            if durable:
                self._pending[loop_id].durable = True
                self._pending[loop_id].write_mode = PersistWriteMode.FULL
                self._durable_event.set()
            log_pending_loops(len(self._pending))

        if durable:
            await self.flush_durable(loop_id, timeout=self._durable_flush_timeout)

    async def flush_durable(self, loop_id: str, *, timeout: float) -> PersistResult:
        """Flush durable pending entry for one loop with timeout."""
        start = asyncio.get_event_loop().time()
        try:
            async with asyncio.timeout(timeout):
                await self._flush_loop(loop_id, force_full=True)
        except TimeoutError:
            return PersistResult(
                ok=False,
                failures=["durable_flush:TimeoutError"],
                duration_ms=int((asyncio.get_event_loop().time() - start) * 1000),
            )
        except Exception as exc:
            return PersistResult(
                ok=False,
                failures=[f"durable_flush:{type(exc).__name__}"],
                duration_ms=int((asyncio.get_event_loop().time() - start) * 1000),
            )
        return PersistResult(
            ok=True,
            duration_ms=int((asyncio.get_event_loop().time() - start) * 1000),
        )

    async def persist_goal_boundary(
        self,
        loop_id: str,
        *,
        checkpoint: StrangeLoopCheckpoint,
        dag: GoalStepDAG | None = None,
        ledger: list[dict[str, Any]] | None = None,
    ) -> PersistResult:
        """Single-transaction goal boundary persist (checkpoint + optional CE)."""
        failures: list[str] = []
        start = asyncio.get_event_loop().time()

        with persist_timer("goal_boundary", loop_id=loop_id):
            try:
                async with asyncio.timeout(self._durable_flush_timeout):
                    await self._persist_goal_boundary_tx(
                        loop_id,
                        checkpoint=checkpoint,
                        dag=dag,
                        ledger=ledger,
                    )
                clear_persist_degraded(checkpoint)
            except TimeoutError:
                mark_persist_degraded(checkpoint)
                failures.append("goal_boundary:TimeoutError")
            except Exception:
                mark_persist_degraded(checkpoint)
                failures.append("goal_boundary:Error")
                logger.warning(
                    "Goal boundary persist failed loop=%s",
                    loop_id,
                    exc_info=True,
                )

        duration_ms = int((asyncio.get_event_loop().time() - start) * 1000)
        return PersistResult(ok=not failures, failures=failures, duration_ms=duration_ms)

    async def save_ce_dag(self, loop_id: str, dag: GoalStepDAG) -> None:
        """Persist CE DAG via writer."""
        snapshot = dag.snapshot()
        data = snapshot.model_dump(mode="json")
        json_str = json.dumps(data, default=str)
        pool = self._shared_pool.get_pool()
        if pool is None:
            return
        async with self._write_lock:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO ce_dag (loop_id, dag_json, updated_at)
                        VALUES (%s, %s::jsonb, NOW())
                        ON CONFLICT (loop_id) DO UPDATE SET
                            dag_json = EXCLUDED.dag_json,
                            updated_at = NOW()
                        """,
                        (loop_id, json_str),
                    )

    async def save_ce_ledger(self, loop_id: str, messages: list[dict[str, Any]]) -> None:
        """Persist CE ledger via writer."""
        json_str = json.dumps(messages, default=str)
        pool = self._shared_pool.get_pool()
        if pool is None:
            return
        async with self._write_lock:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO ce_ledger (loop_id, ledger_json, updated_at)
                        VALUES (%s, %s::jsonb, NOW())
                        ON CONFLICT (loop_id) DO UPDATE SET
                            ledger_json = EXCLUDED.ledger_json,
                            updated_at = NOW()
                        """,
                        (loop_id, json_str),
                    )

    async def release_loop(self, loop_id: str, *, timeout: float | None = None) -> None:
        """Flush pending writes for loop and mark released (bounded)."""
        timeout = timeout if timeout is not None else self._close_timeout_seconds
        self._released_loops.add(loop_id)
        try:
            async with asyncio.timeout(timeout):
                await self._flush_loop(loop_id, force_full=True)
                with self._pending_guard:
                    self._pending.pop(loop_id, None)
        except TimeoutError:
            logger.warning(
                "Persist release_loop timed out after %.0fs loop=%s",
                timeout,
                loop_id,
            )

    async def pause_for_pool_reset(self, *, timeout: float = 15.0) -> None:
        """Pause accepts and drain in-flight writes before pool reset."""
        await self._run_on_main(lambda: self._pause_for_pool_reset_impl(timeout=timeout))

    async def _pause_for_pool_reset_impl(self, *, timeout: float = 15.0) -> None:
        self._paused = True
        self._durable_event.set()
        try:
            async with asyncio.timeout(timeout):
                while self._inflight > 0:
                    await self._inflight_done.wait()
                with self._pending_guard:
                    loop_ids = list(self._pending.keys())
                for loop_id in loop_ids:
                    await self._flush_loop(loop_id, force_full=True)
                with self._pending_guard:
                    self._pending.clear()
        except TimeoutError:
            logger.warning("Persist writer pause_for_pool_reset timed out")

    def resume_after_pool_reset(self) -> None:
        """Resume accepts after pool reset completes."""
        self._paused = False

    async def _persist_goal_boundary_tx(
        self,
        loop_id: str,
        *,
        checkpoint: StrangeLoopCheckpoint,
        dag: GoalStepDAG | None,
        ledger: list[dict[str, Any]] | None,
    ) -> None:
        pool = self._shared_pool.get_pool()
        if pool is None:
            msg = "Shared PostgreSQL pool unavailable for goal boundary persist"
            raise RuntimeError(msg)

        checkpoint_data = checkpoint.model_dump(mode="json")
        hot_json = json.dumps(extract_hot_index(checkpoint))
        cold_json = json.dumps(extract_cold_blob(checkpoint))

        from soothe.foundation.sloop.state.persistence.daemon_loop_metadata import (
            load_preserved_daemon_metadata,
            merge_daemon_loop_metadata,
        )

        async with self._write_lock:
            self._inflight += 1
            self._inflight_done.clear()
            try:
                async with pool.connection() as conn:
                    await conn.set_autocommit(False)
                    try:
                        async with conn.transaction():
                            async with conn.cursor() as cur:
                                preserved = await load_preserved_daemon_metadata(cur, loop_id)
                                merged_data = merge_daemon_loop_metadata(
                                    checkpoint_data, preserved
                                )
                                data_json = json.dumps(merged_data)
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
                                    (
                                        loop_id,
                                        checkpoint_data["current_thread_id"],
                                        checkpoint_data["status"],
                                        data_json,
                                        hot_json,
                                    ),
                                )
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
                                if dag is not None:
                                    dag_json = json.dumps(
                                        dag.snapshot().model_dump(mode="json"),
                                        default=str,
                                    )
                                    await cur.execute(
                                        """
                                        INSERT INTO ce_dag (loop_id, dag_json, updated_at)
                                        VALUES (%s, %s::jsonb, NOW())
                                        ON CONFLICT (loop_id) DO UPDATE SET
                                            dag_json = EXCLUDED.dag_json,
                                            updated_at = NOW()
                                        """,
                                        (loop_id, dag_json),
                                    )
                                if ledger is not None:
                                    ledger_json = json.dumps(ledger, default=str)
                                    await cur.execute(
                                        """
                                        INSERT INTO ce_ledger (loop_id, ledger_json, updated_at)
                                        VALUES (%s, %s::jsonb, NOW())
                                        ON CONFLICT (loop_id) DO UPDATE SET
                                            ledger_json = EXCLUDED.ledger_json,
                                            updated_at = NOW()
                                        """,
                                        (loop_id, ledger_json),
                                    )
                    finally:
                        await conn.set_autocommit(True)
            finally:
                self._inflight -= 1
                if self._inflight <= 0:
                    self._inflight = 0
                    self._inflight_done.set()

        with self._pending_guard:
            self._pending.pop(loop_id, None)

    async def _flush_loop(self, loop_id: str, *, force_full: bool) -> None:
        with self._pending_guard:
            entry = self._pending.pop(loop_id, None)
        if entry is None:
            return

        write_mode = (
            PersistWriteMode.FULL
            if force_full or entry.durable or entry.write_mode == PersistWriteMode.FULL
            else PersistWriteMode.INDEX_ONLY
        )
        await self._write_checkpoint(entry.checkpoint, write_mode=write_mode)

    async def _write_checkpoint(
        self,
        checkpoint: StrangeLoopCheckpoint,
        *,
        write_mode: PersistWriteMode,
    ) -> None:
        from soothe.foundation.sloop.state.persistence.postgres_backend import (
            PostgreSQLPersistenceBackend,
        )

        pool = self._shared_pool.get_pool()
        if pool is None:
            msg = "Shared PostgreSQL pool unavailable"
            raise RuntimeError(msg)

        backend = PostgreSQLPersistenceBackend(dsn="", pool_size=0, shared_pool=self._shared_pool)
        backend._pool = pool  # noqa: SLF001

        self._inflight += 1
        self._inflight_done.clear()
        try:
            with persist_timer(f"flush_{write_mode.value}", loop_id=checkpoint.loop_id):
                await backend.save_checkpoint(
                    checkpoint,
                    write_mode=write_mode.value,
                    hot_cold_enabled=True,
                )
        finally:
            self._inflight -= 1
            if self._inflight <= 0:
                self._inflight = 0
                self._inflight_done.set()

    async def _flush_worker_loop(self) -> None:
        while True:
            try:
                if self._paused:
                    await asyncio.sleep(0.1)
                    continue

                try:
                    await asyncio.wait_for(
                        self._durable_event.wait(),
                        timeout=self._flush_interval,
                    )
                except TimeoutError:
                    pass
                self._durable_event.clear()

                with self._pending_guard:
                    loop_ids = list(self._pending.keys())

                for loop_id in loop_ids:
                    if loop_id in self._released_loops:
                        continue
                    with self._pending_guard:
                        entry = self._pending.get(loop_id)
                    if entry is None:
                        continue
                    if entry.durable:
                        await self._flush_loop(loop_id, force_full=True)
                    else:
                        await self._flush_loop(loop_id, force_full=False)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Loop persistence writer flush failed")
                await asyncio.sleep(1.0)


__all__ = [
    "LoopPersistenceWriter",
    "PersistResult",
    "PersistWriteMode",
]
