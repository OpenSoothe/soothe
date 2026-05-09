"""Loop-scoped isolation for the daemon client plane (IG-408).

Minimal API for other modules:
    - ``loop_event_topic``: event-bus topic string for a loop
    - ``bind_execution_thread_for_loop``: align runner + registry with loop metadata
    - ``LoopInputDispatcher``: per-loop asyncio queues and workers
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from uuid_utils import uuid7

from soothe.core.workspace import resolve_loop_daemon_workspace

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
    loop_dir = await daemon._message_router._ensure_loop_metadata(loop_id)
    if loop_dir is None:
        msg = f"Loop {loop_id} not found"
        raise RuntimeError(msg)

    metadata_file = loop_dir / "metadata.json"
    try:
        metadata = json.loads(metadata_file.read_text())
    except Exception as e:
        msg = f"Failed to read loop metadata: {e}"
        raise RuntimeError(msg) from e

    thread_id = metadata.get("current_thread_id")
    if not thread_id:
        thread_id = str(uuid7())
        metadata["current_thread_id"] = thread_id
        if thread_id not in metadata.get("thread_ids", []):
            metadata.setdefault("thread_ids", []).append(thread_id)
        metadata["status"] = "running"
        metadata["updated_at"] = datetime.now(UTC).isoformat()
        try:
            metadata_file.write_text(json.dumps(metadata, indent=2))
        except OSError as e:
            logger.warning("Failed to update loop metadata for %s: %s", loop_id, e)

    daemon._thread_registry.ensure(thread_id, is_draft=False)

    # Prefer client-provided workspace (IG-409): when the CLI/SDK passes the user's
    # CWD via loop_new, the agent's filesystem tools should default to the user's
    # project directory rather than the per-loop daemon scratch dir (IG-300 fallback).
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
        try:
            loop_workspace = resolve_loop_daemon_workspace(loop_id)
        except (OSError, ValueError) as e:
            logger.warning(
                "Falling back to daemon workspace for loop %s thread %s: %s",
                loop_id,
                thread_id,
                e,
            )
            loop_workspace = Path(daemon._daemon_workspace)

    daemon._thread_registry.set_workspace(thread_id, loop_workspace)
    daemon._thread_registry.set_thread_loop(thread_id, loop_id)
    daemon._runner.set_current_thread_id(thread_id)
    return str(thread_id)


class LoopInputDispatcher:
    """Isolated input/command processing: one queue and worker task per ``loop_id``."""

    def __init__(self, daemon: Any, *, max_queue_size: int) -> None:
        self._daemon = daemon
        self._max_queue_size = max_queue_size if max_queue_size > 0 else 0
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    def total_queued(self) -> int:
        """Approximate sum of pending items across loop queues (for metrics)."""
        return sum(q.qsize() for q in self._queues.values())

    async def enqueue(self, loop_id: str, message: dict[str, Any]) -> None:
        """Enqueue a message for the given loop; starts a worker on first use."""
        async with self._lock:
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
            workers = list(self._workers.items())
            self._workers.clear()
            self._queues.clear()
        for _, task in workers:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _worker(self, loop_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        d = self._daemon
        while d._running:
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
