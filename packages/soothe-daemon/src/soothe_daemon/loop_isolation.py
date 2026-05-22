"""Loop-scoped isolation for the daemon client plane (IG-408).

Minimal API for other modules:
    - ``bind_execution_thread_for_loop``: align runner + registry with loop metadata
    - ``LoopInputDispatcher``: per-loop asyncio queues and workers
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.core.runner._types import generate_thread_id
from soothe.core.workspace import resolve_daemon_workspace, resolve_user_workspace

from soothe_daemon.logging import set_loop_id

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


async def bind_execution_thread_for_loop(daemon: Any, loop_id: str) -> str:
    """Ensure runner and thread registry match ``loop_id`` metadata; return CoreAgent thread id.

    Args:
        daemon: ``SootheDaemon`` instance.
        loop_id: AgentLoop identifier.

    Returns:
        Active durability thread id for this loop.

    Raises:
        RuntimeError: If loop metadata is missing or invalid.
    """
    # Set loop_id in logging context for full ID in daemon.log
    set_loop_id(loop_id)

    # Check loop exists in DB
    metadata = await daemon._persistence_manager.get_loop_metadata(loop_id)
    if metadata is None:
        msg = f"Loop {loop_id} not found"
        raise RuntimeError(msg)

    thread_id = str(metadata.get("current_thread_id") or "").strip()
    thread_ids = [str(t) for t in (metadata.get("thread_ids") or []) if str(t).strip()]
    # loop_id scopes AgentLoop persistence; thread_id is the LangGraph/durability conversation id.
    if not thread_id or thread_id == loop_id:
        if thread_id == loop_id:
            logger.info(
                "Loop %s: replacing legacy thread_id=loop_id alias with a new thread",
                loop_id,
            )
            thread_ids = [t for t in thread_ids if t != loop_id]
        thread_id = generate_thread_id()
        if thread_id not in thread_ids:
            thread_ids.append(thread_id)
        try:
            await daemon._persistence_manager.update_loop_metadata(
                loop_id,
                current_thread_id=thread_id,
                thread_ids=thread_ids,
                status="running",
            )
        except Exception as e:
            logger.warning("Failed to update loop metadata for %s: %s", loop_id, e)

    daemon._thread_registry.ensure(thread_id, is_draft=False)

    # Workspace resolution — user-scoped persistence:
    #   1. user + client_workspace → per-user workspace dir ($SOOTHE_HOME/workspaces/ws_<hash>/)
    #   2. client_workspace only → anonymous workspace ($SOOTHE_HOME/workspaces/anon_<hash>/)
    #   3. daemon fallback workspace (TEMP)
    loop_workspace: Path | None = None

    raw_user = metadata.get("user_id") or metadata.get("user")  # Support both field names
    raw_client_ws = metadata.get("client_workspace")

    user = str(raw_user).strip() if raw_user else None
    client_ws = str(raw_client_ws).strip() if raw_client_ws else None

    if client_ws:
        try:
            loop_workspace = resolve_user_workspace(user, client_ws)
        except ValueError as e:
            logger.warning(
                "Loop %s: invalid client_workspace %r: %s; falling back to daemon workspace",
                loop_id,
                client_ws,
                e,
            )

    if loop_workspace is None:
        loop_workspace = resolve_daemon_workspace()

    daemon._thread_registry.set_workspace(thread_id, loop_workspace)
    daemon._thread_registry.set_thread_loop(thread_id, loop_id)
    # RFC-221: set_current_thread_id() removed — thread binding is passed via LoopRunRequest
    # and applied inside the per-loop subprocess. The utility _runner singleton is no longer
    # mutated here, eliminating the data race under concurrent loop execution.
    return str(thread_id)


class LoopInputDispatcher:
    """Isolated input/command processing: one queue and worker task per ``loop_id``."""

    def __init__(self, daemon: Any, *, max_queue_size: int) -> None:
        self._daemon = daemon
        self._max_queue_size = max_queue_size if max_queue_size > 0 else 0
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._shutting_down: bool = False

    def total_queued(self) -> int:
        """Approximate sum of pending items across loop queues (for metrics)."""
        return sum(q.qsize() for q in self._queues.values())

    async def enqueue(self, loop_id: str, message: dict[str, Any]) -> None:
        """Enqueue a message for the given loop; starts a worker on first use.

        Silently drops the message if shutdown has already been initiated so that
        concurrent callers cannot create new orphan workers after the snapshot in
        ``shutdown()`` has been taken.
        """
        async with self._lock:
            if self._shutting_down:
                logger.debug(
                    "LoopInputDispatcher shutting down; dropping message for loop %s",
                    loop_id,
                )
                return
            if loop_id not in self._queues:
                q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
                    maxsize=self._max_queue_size if self._max_queue_size > 0 else 0
                )
                self._queues[loop_id] = q
                self._workers[loop_id] = asyncio.create_task(self._worker(loop_id, q))
            queue = self._queues[loop_id]
        await queue.put(message)

    async def shutdown(self) -> None:
        """Cancel all loop workers (daemon stop)."""
        async with self._lock:
            self._shutting_down = True  # prevent new enqueue() from spawning workers
            workers = list(self._workers.items())
            self._workers.clear()
            self._queues.clear()
        for _, task in workers:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def cleanup_loop(self, loop_id: str) -> None:
        """Remove queue and worker for a specific loop (loop deletion)."""
        async with self._lock:
            worker = self._workers.pop(loop_id, None)
            self._queues.pop(loop_id, None)
        if worker is not None and not worker.done():
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        logger.debug("Cleaned up input dispatcher state for loop %s", loop_id)

    async def _worker(self, loop_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        d = self._daemon
        while d._running and not self._shutting_down:
            try:
                msg = await queue.get()
            except asyncio.CancelledError:
                break
            try:
                await d._process_loop_input_message(loop_id, msg)
            except Exception:
                logger.exception("Loop worker failed for loop_id=%s", loop_id)

    async def drain_for_tests(self) -> None:
        """Cancel workers and clear queues (unit/integration tests only)."""
        await self.shutdown()


__all__ = [
    "LoopInputDispatcher",
    "bind_execution_thread_for_loop",
]
