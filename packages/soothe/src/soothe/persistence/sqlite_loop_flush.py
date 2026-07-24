"""Process-scoped SQLite checkpoint coalesce flush (IG-647 / RFC-803).

Mirrors ``LoopPersistenceWriter`` for SQLite: managers enqueue; one worker
drains onto the shared checkpoints ``SqliteStoreRuntime``.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.sloop.state.checkpoint import StrangeLoopCheckpoint

logger = logging.getLogger(__name__)

SaveSyncFn = Callable[[sqlite3.Connection, "StrangeLoopCheckpoint"], None]

_coordinator_singleton: SqliteLoopFlushCoordinator | None = None
_coordinator_init_lock = threading.Lock()


@dataclass
class _PendingEntry:
    checkpoint: StrangeLoopCheckpoint
    save_fn: SaveSyncFn
    durable: bool = False


class SqliteLoopFlushCoordinator:
    """Coalescing SQLite checkpoint flush keyed by loop_id."""

    _bound_loop: asyncio.AbstractEventLoop | None = None

    def __init__(
        self,
        *,
        flush_interval: float = 5.0,
        close_timeout_seconds: float = 30.0,
        durable_flush_timeout: float = 10.0,
    ) -> None:
        self._flush_interval = flush_interval
        self._close_timeout_seconds = close_timeout_seconds
        self._durable_flush_timeout = durable_flush_timeout

        self._pending: dict[str, _PendingEntry] = {}
        self._pending_guard = threading.Lock()
        self._durable_event = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._released_loops: set[str] = set()
        self._runtimes: dict[str, object] = {}

    @classmethod
    def bind_main_loop(cls, loop: asyncio.AbstractEventLoop) -> None:
        """Pin asyncio primitives to ``loop`` (daemon main loop)."""
        cls._bound_loop = loop

    @classmethod
    def existing_instance(cls) -> SqliteLoopFlushCoordinator | None:
        return _coordinator_singleton

    @classmethod
    async def get_shared_instance(
        cls,
        config: SootheConfig | None = None,
        *,
        flush_interval: float | None = None,
        close_timeout_seconds: float | None = None,
        durable_flush_timeout: float | None = None,
    ) -> SqliteLoopFlushCoordinator:
        """Return process singleton for SQLite coalesce flush."""
        global _coordinator_singleton

        if _coordinator_singleton is not None:
            return _coordinator_singleton

        with _coordinator_init_lock:
            if _coordinator_singleton is not None:
                return _coordinator_singleton

            interval = 5.0
            close_to = 30.0
            durable_to = 10.0
            if config is not None:
                checkpoint_cfg = config.agent.loop.concurrency.checkpoint
                interval = float(checkpoint_cfg.flush_interval)
                close_to = float(checkpoint_cfg.close_timeout_seconds)
                durable_to = float(checkpoint_cfg.durable_flush_timeout)
            if flush_interval is not None:
                interval = flush_interval
            if close_timeout_seconds is not None:
                close_to = close_timeout_seconds
            if durable_flush_timeout is not None:
                durable_to = durable_flush_timeout

            _coordinator_singleton = cls(
                flush_interval=interval,
                close_timeout_seconds=close_to,
                durable_flush_timeout=durable_to,
            )

        await _coordinator_singleton._ensure_worker()
        return _coordinator_singleton

    @classmethod
    async def close_shared_instance(cls) -> None:
        """Stop shared flush worker at daemon / process shutdown."""
        global _coordinator_singleton
        with _coordinator_init_lock:
            inst = _coordinator_singleton
            _coordinator_singleton = None
        if inst is None:
            return
        await inst.shutdown()

    async def _ensure_worker(self) -> None:
        if self._worker_task is not None and not self._worker_task.done():
            return
        if type(self)._bound_loop is None:
            type(self)._bound_loop = asyncio.get_running_loop()
        self._worker_task = asyncio.create_task(
            self._flush_worker_loop(),
            name="sqlite-loop-flush-coordinator",
        )
        logger.info(
            "SQLite loop flush coordinator started flush_interval=%ss",
            self._flush_interval,
        )

    async def enqueue(
        self,
        loop_id: str,
        checkpoint: StrangeLoopCheckpoint,
        save_fn: SaveSyncFn,
        *,
        runtime: object,
        durable: bool = False,
    ) -> None:
        """Enqueue or coalesce a checkpoint write."""
        if loop_id in self._released_loops and not durable:
            return

        await self._ensure_worker()
        with self._pending_guard:
            existing = self._pending.get(loop_id)
            if existing is not None and not durable:
                existing.checkpoint = checkpoint
                existing.save_fn = save_fn
            else:
                self._pending[loop_id] = _PendingEntry(
                    checkpoint=checkpoint,
                    save_fn=save_fn,
                    durable=durable,
                )
            self._runtimes[loop_id] = runtime
            if durable:
                self._pending[loop_id].durable = True
                self._durable_event.set()

        if durable:
            await self.flush_loop(loop_id, timeout=self._durable_flush_timeout)

    async def flush_loop(self, loop_id: str, *, timeout: float | None = None) -> None:
        """Flush pending entry for one loop."""
        timeout = self._durable_flush_timeout if timeout is None else timeout
        try:
            async with asyncio.timeout(timeout):
                await self._flush_loop(loop_id)
        except TimeoutError:
            logger.warning(
                "SQLite coalesce flush timed out after %.0fs loop=%s",
                timeout,
                loop_id,
            )
            raise

    async def release_loop(self, loop_id: str, *, timeout: float | None = None) -> None:
        """Flush pending writes for loop and mark released."""
        timeout = self._close_timeout_seconds if timeout is None else timeout
        self._released_loops.add(loop_id)
        try:
            async with asyncio.timeout(timeout):
                await self._flush_loop(loop_id)
                with self._pending_guard:
                    self._pending.pop(loop_id, None)
                    self._runtimes.pop(loop_id, None)
        except TimeoutError:
            logger.warning(
                "SQLite coalesce release timed out after %.0fs loop=%s",
                timeout,
                loop_id,
            )

    async def shutdown(self) -> None:
        """Cancel worker and drain remaining pending writes."""
        with self._pending_guard:
            loop_ids = list(self._pending.keys())
        for loop_id in loop_ids:
            try:
                await self._flush_loop(loop_id)
            except Exception:
                logger.warning(
                    "SQLite coalesce shutdown flush failed loop=%s",
                    loop_id,
                    exc_info=True,
                )
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        with self._pending_guard:
            self._pending.clear()
            self._runtimes.clear()

    async def _flush_loop(self, loop_id: str) -> None:
        with self._pending_guard:
            entry = self._pending.pop(loop_id, None)
            runtime = self._runtimes.get(loop_id)
        if entry is None:
            return
        if runtime is None:
            logger.warning("SQLite coalesce flush missing runtime loop=%s", loop_id)
            return

        checkpoint = entry.checkpoint
        save_fn = entry.save_fn

        def _write(conn: sqlite3.Connection) -> None:
            save_fn(conn, checkpoint)

        await runtime.run_write(_write)  # type: ignore[attr-defined]
        logger.debug("SQLite coalesce flushed loop=%s status=%s", loop_id, checkpoint.status)

    async def _flush_worker_loop(self) -> None:
        while True:
            try:
                try:
                    await asyncio.wait_for(
                        self._durable_event.wait(),
                        timeout=self._flush_interval,
                    )
                except TimeoutError:
                    pass
                self._durable_event.clear()

                with self._pending_guard:
                    loop_ids = [lid for lid in self._pending if lid not in self._released_loops]

                for loop_id in loop_ids:
                    try:
                        await self._flush_loop(loop_id)
                    except Exception:
                        logger.exception("SQLite coalesce flush failed loop=%s", loop_id)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("SQLite loop flush coordinator worker failed")
                await asyncio.sleep(1.0)


__all__ = [
    "SqliteLoopFlushCoordinator",
]
