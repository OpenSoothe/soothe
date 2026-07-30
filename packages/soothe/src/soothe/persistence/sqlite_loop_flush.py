"""Process-scoped SQLite checkpoint coalesce flush (IG-647 / RFC-803).

Mirrors ``LoopPersistenceWriter`` for SQLite: managers enqueue; one worker
drains onto the shared checkpoints ``SqliteStoreRuntime``.

Threading model (IG-571): asyncio primitives (``Event``, worker task) are bound
to the daemon main loop via ``bind_main_loop``. Worker threads running on their
own event loops call ``submit_*`` methods, which marshal work onto the bound
loop via ``asyncio.run_coroutine_threadsafe``. This prevents the
``RuntimeError: ... is bound to a different event loop`` that occurred when a
per-worker loop awaited a singleton ``asyncio.Event`` created on another loop.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.sloop.state.checkpoint import StrangeLoopCheckpoint

logger = logging.getLogger(__name__)

T = TypeVar("T")

SaveSyncFn = Callable[[sqlite3.Connection, "StrangeLoopCheckpoint"], None]


def _loop_is_running(loop: asyncio.AbstractEventLoop) -> bool:
    """Return True if ``loop`` is still accepting work.

    ``loop.is_closed()`` covers the common teardown case (e.g. a test loop that
    has been closed but still referenced by the class-level ``_bound_loop``).
    """
    try:
        return not loop.is_closed()
    except Exception:
        return False


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
        # asyncio.Event is created lazily on the bound loop (see _ensure_worker)
        # so it is never bound to a transient caller loop.
        self._durable_event: asyncio.Event | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._released_loops: set[str] = set()
        self._runtimes: dict[str, object] = {}

    @classmethod
    def bind_main_loop(cls, loop: asyncio.AbstractEventLoop) -> None:
        """Pin asyncio primitives to ``loop`` (daemon main loop)."""
        cls._bound_loop = loop
        logger.debug("SqliteLoopFlushCoordinator bound to event loop %s", loop)

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
    ) -> SqliteLoopFlushCoordinator | None:
        """Return process singleton for SQLite coalesce flush, or ``None`` if
        the process is not configured for SQLite.

        Mirrors ``LoopPersistenceWriter.get_shared_instance``, which self-gates
        on ``default_backend`` so a stray caller on a Postgres-configured
        process cannot construct a useless SQLite singleton (AGENTS.md §10:
        never mix backends in the same process). Callers must handle ``None``
        by falling back to a direct checkpoint write.
        """
        global _coordinator_singleton

        if config is not None and config.persistence.default_backend != "sqlite":
            return None

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

        await _coordinator_singleton._run_on_main(_coordinator_singleton._ensure_worker)
        return _coordinator_singleton

    @classmethod
    async def close_shared_instance(cls) -> None:
        """Stop shared flush worker at daemon / process shutdown."""
        global _coordinator_singleton
        with _coordinator_init_lock:
            inst = _coordinator_singleton
            _coordinator_singleton = None
        if inst is None:
            # Even with no live instance, clear a stale loop binding so the
            # next get_shared_instance rebinds to the current running loop.
            cls._bound_loop = None
            return
        await inst._run_on_main(inst.shutdown)
        # Clear the loop binding so a later instance (e.g. in tests or a
        # restarted daemon) rebinds to the then-current running loop instead
        # of reusing a now-closed loop from a prior process/test scope.
        cls._bound_loop = None

    async def _run_on_main(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, T]],
    ) -> T:
        """Run ``coro_factory`` on the bound loop; await from any caller loop.

        Mirrors ``LoopPersistenceWriter._run_on_main``: callers running on a
        per-worker event loop are marshalled onto the bound (daemon main) loop
        via ``asyncio.run_coroutine_threadsafe``, so that asyncio primitives
        shared by the singleton are never touched from a foreign loop.

        If the previously bound loop has been closed (e.g. between tests in the
        same process, or after a daemon restart), rebind to the caller's loop
        rather than scheduling onto a dead loop.
        """
        running = asyncio.get_running_loop()
        bound = type(self)._bound_loop
        if bound is not None and not _loop_is_running(bound):
            # Stale binding (closed loop) — drop it so we rebind below.
            type(self)._bound_loop = None
            bound = None
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
        save_fn: SaveSyncFn,
        *,
        runtime: object,
        durable: bool = False,
    ) -> None:
        """Thread-safe enqueue from any event loop."""
        await self._run_on_main(
            lambda: self.enqueue(
                loop_id,
                checkpoint,
                save_fn,
                runtime=runtime,
                durable=durable,
            )
        )

    async def submit_flush_loop(
        self,
        loop_id: str,
        *,
        timeout: float | None = None,
    ) -> None:
        """Thread-safe durable flush from any event loop."""
        await self._run_on_main(lambda: self.flush_loop(loop_id, timeout=timeout))

    async def submit_release_loop(
        self,
        loop_id: str,
        *,
        timeout: float | None = None,
    ) -> None:
        """Thread-safe bounded loop release from any event loop."""
        await self._run_on_main(lambda: self.release_loop(loop_id, timeout=timeout))

    async def _ensure_worker(self) -> None:
        """Create the durable Event on the bound loop and start the worker task.

        The ``asyncio.Event`` is constructed here (on the bound loop) rather
        than in ``__init__`` so it is never bound to a transient caller loop,
        which previously caused ``RuntimeError: ... bound to a different event
        loop`` when a worker thread awaited it.
        """
        if self._worker_task is not None and not self._worker_task.done():
            return
        if type(self)._bound_loop is None:
            type(self)._bound_loop = asyncio.get_running_loop()
        if self._durable_event is None:
            self._durable_event = asyncio.Event()
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
        """Enqueue or coalesce a checkpoint write (bound loop only).

        Callers on a different event loop must use ``submit_enqueue`` instead.
        """
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
                if self._durable_event is not None:
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
        # The durable Event is guaranteed to exist because _ensure_worker
        # creates it on the bound loop before starting this task.
        event = self._durable_event
        assert event is not None  # noqa: S101 - invariant under _ensure_worker
        while True:
            try:
                try:
                    await asyncio.wait_for(
                        event.wait(),
                        timeout=self._flush_interval,
                    )
                except TimeoutError:
                    pass
                event.clear()

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
