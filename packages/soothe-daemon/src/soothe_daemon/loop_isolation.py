"""Loop-scoped isolation for the daemon client plane (IG-408).

Minimal API for other modules:
    - ``loop_event_topic``: event-bus topic string for a loop
    - ``bind_execution_thread_for_loop``: align runner + registry with loop metadata
    - ``LoopInputDispatcher``: per-loop asyncio queues and workers
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.core.workspace import resolve_loop_daemon_workspace
from uuid_utils import uuid7

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def loop_event_topic(loop_id: str) -> str:
    """Return the event-bus topic for loop-scoped delivery."""
    return f"loop:{loop_id}"


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
    # Check loop exists in DB
    metadata = await daemon._persistence_manager.get_loop_metadata(loop_id)
    if metadata is None:
        msg = f"Loop {loop_id} not found"
        raise RuntimeError(msg)

    thread_id = metadata.get("current_thread_id")
    if not thread_id:
        thread_id = str(uuid7())
        thread_ids = list(metadata.get("thread_ids") or [])
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

    # Workspace resolution — two tiers only:
    #   1. client_workspace from loop metadata (IG-409): the user's CWD passed via loop_new.
    #   2. per-loop daemon scratch dir: $SOOTHE_HOME/data/loops/<loop_id>/workspace/ (IG-300).
    loop_workspace: Path | None = None
    raw_client_ws = metadata.get("client_workspace")
    if isinstance(raw_client_ws, str) and raw_client_ws.strip():
        candidate = Path(raw_client_ws).expanduser()
        if candidate.is_dir():
            loop_workspace = candidate.resolve()
        else:
            logger.warning(
                "Loop %s client_workspace %r is not a directory; falling back to per-loop dir",
                loop_id[:16],
                raw_client_ws,
            )

    if loop_workspace is None:
        loop_workspace = resolve_loop_daemon_workspace(loop_id)

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
                    loop_id[:16],
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
        logger.debug("Cleaned up input dispatcher state for loop %s", loop_id[:16])

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
                logger.exception("Loop worker failed for loop_id=%s", loop_id[:16])

    async def drain_for_tests(self) -> None:
        """Cancel workers and clear queues (unit/integration tests only)."""
        await self.shutdown()


__all__ = [
    "LoopInputDispatcher",
    "bind_execution_thread_for_loop",
    "loop_event_topic",
]
