"""Thread-to-asyncio stream response bridge (IG-429, IG-477).

Eliminates poll-delayed delivery from worker threads into the daemon event loop.
IG-477: Added backpressure handling to prevent unbounded queue growth.

NOTE: The semaphore backpressure here is a defensive optimization, not the root
fix for IG-477 OOM. The root cause was LangGraph checkpointer channel history
loaded on every astream tick (see IG-477 for details). Backpressure helps bound
in-flight chunks but alone did not resolve the memory leak.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Message types workers emit (threading/mp queue convention uses 3-tuples with request_id).
WORKER_MSG_CHUNK = "chunk"
WORKER_MSG_DONE = "done"
WORKER_MSG_READY = "ready"
WORKER_MSG_ERROR = "error"
WORKER_MSG_CANCELLED = "cancelled"
WORKER_MSG_TIMEOUT = "timeout"

# Backpressure: block worker thread until a delivery slot is available.
_DEFAULT_SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS = 5.0
_GOAL_COMPLETION_SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS = 60.0
# IG-549: Execute phase can run for minutes (browser_use, long searches); use longer timeout
_EXECUTE_PHASE_SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS = 30.0

# IG-477: Limit in-flight chunk deliveries (blocks worker thread when full)
# IG-535: Tuned for 32 concurrent loops - 100 slots per worker allows heavier per-loop streams
_MAX_PENDING_CALLBACKS = 200  # Slot count for the shared default pool (no worker_id)
_DEFAULT_SLOTS_PER_WORKER = 100  # IG-535: Increased from 50 for dense streaming workloads

# Semaphore slots per worker thread — isolates backpressure across pool workers.
_worker_pending_slots: dict[str, threading.Semaphore] = {}
_worker_slots_lock = threading.Lock()


def _pending_slots_for(worker_id: str | None) -> threading.Semaphore:
    """Return the in-flight delivery semaphore for one worker (or shared default)."""
    key = (worker_id or "").strip() or "__default__"
    with _worker_slots_lock:
        sem = _worker_pending_slots.get(key)
        if sem is None:
            limit = _MAX_PENDING_CALLBACKS if key == "__default__" else _DEFAULT_SLOTS_PER_WORKER
            sem = threading.Semaphore(limit)
            _worker_pending_slots[key] = sem
        return sem


def _chunk_is_goal_completion(payload: Any) -> bool:
    """Return True when a worker chunk carries goal_completion synthesis."""
    if not isinstance(payload, tuple) or len(payload) < 3:
        return False
    data = payload[2]
    if not isinstance(data, tuple) or not data:
        return False
    msg = data[0]
    return isinstance(msg, dict) and msg.get("phase") == "goal_completion"


def _chunk_is_execute_phase(payload: Any) -> bool:
    """Return True when a worker chunk carries execute phase content.

    IG-549: Execute phase can run for minutes during tool execution (browser_use,
    long searches). These chunks should use longer timeout to avoid being dropped.
    """
    if not isinstance(payload, tuple) or len(payload) < 3:
        return False
    data = payload[2]
    if not isinstance(data, tuple) or not data:
        return False
    msg = data[0]
    if not isinstance(msg, dict):
        return False
    phase = msg.get("phase", "")
    # Execute phase includes: tool streaming, step execution, subagent wire events
    return phase in ("execute", "tool_result", "stream_event") or phase.startswith("execute:")


@dataclass(frozen=True)
class ResponsePusher:
    """Push stream responses from a worker thread into the main asyncio.Queue.

    Uses ``call_soon_threadsafe`` so chunks are delivered without polling the
    worker response queue on a fixed interval.

    IG-477: Semaphore backpressure blocks the worker thread when too many chunks
    are in flight, preventing LangGraph state from growing without bound when
    downstream delivery is slow.

    Per-worker semaphores (IG-534) prevent one loop from exhausting the global
    in-flight budget shared across unrelated workers.
    """

    _loop: asyncio.AbstractEventLoop
    _queue: asyncio.Queue[Any]
    worker_id: str | None = None

    def _pending_slots(self) -> threading.Semaphore:
        return _pending_slots_for(self.worker_id)

    def push_from_worker(self, msg_type: str, payload: Any = None) -> None:
        """Schedule delivery of one worker message onto the main event loop.

        Args:
            msg_type: Worker message kind (``chunk``, ``done``, ``error``, etc.).
            payload: Chunk tuple or exception; ignored for ``done`` / ``cancelled``.

        For CHUNK messages, blocks the worker thread until a delivery slot is
        available (semaphore acquire). This applies backpressure to LangGraph
        ``astream`` so memory cannot grow unbounded when the consumer is slow.

        IG-549: Uses longer timeout for execute-phase and goal_completion chunks
        since these can run for minutes during long tool execution (browser_use,
        web searches).
        """
        if self._loop.is_closed():
            return

        acquired_slot = False
        if msg_type == WORKER_MSG_CHUNK:
            # IG-549: Tiered timeout based on chunk phase
            if _chunk_is_goal_completion(payload):
                acquire_timeout = _GOAL_COMPLETION_SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS
            elif _chunk_is_execute_phase(payload):
                acquire_timeout = _EXECUTE_PHASE_SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS
            else:
                acquire_timeout = _DEFAULT_SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS
            # Block worker thread until downstream catches up (backpressure).
            slots = self._pending_slots()
            if not slots.acquire(timeout=acquire_timeout):
                logger.warning(
                    "ResponsePusher: backpressure timeout (limit=%d, goal_completion=%s); "
                    "retrying chunk delivery",
                    _DEFAULT_SLOTS_PER_WORKER,
                    _chunk_is_goal_completion(payload),
                )
                if not slots.acquire(timeout=acquire_timeout):
                    logger.error(
                        "ResponsePusher: dropping chunk after backpressure retry "
                        "(goal_completion=%s)",
                        _chunk_is_goal_completion(payload),
                    )
                    return
            acquired_slot = True

        try:
            self._loop.call_soon_threadsafe(self._deliver, msg_type, payload, acquired_slot)
        except RuntimeError:
            logger.debug("ResponsePusher: loop closed, dropping %s", msg_type)
            if acquired_slot:
                self._pending_slots().release()

    def _schedule_queue_put(
        self,
        item: tuple[str, Any],
        *,
        release_slot: bool = False,
    ) -> None:
        """Enqueue onto the asyncio queue, waiting for capacity when full."""

        async def _put() -> None:
            try:
                await self._queue.put(item)
            except Exception:
                logger.exception(
                    "ResponsePusher: failed to deliver msg_type=%s",
                    item[0],
                )
            finally:
                if release_slot:
                    self._pending_slots().release()

        asyncio.create_task(_put())

    def _deliver(self, msg_type: str, payload: Any, release_slot: bool = False) -> None:
        """Run on the main loop thread; map worker types to asyncio.Queue tuples.

        All deliveries use blocking ``queue.put`` so terminal frames (especially
        ``done``) are never dropped when the asyncio queue is momentarily full.
        """
        if msg_type == WORKER_MSG_TIMEOUT:
            self._schedule_queue_put((WORKER_MSG_ERROR, payload))
        elif msg_type == WORKER_MSG_CANCELLED:
            self._schedule_queue_put((WORKER_MSG_ERROR, asyncio.CancelledError()))
        elif msg_type == WORKER_MSG_CHUNK:
            self._schedule_queue_put((WORKER_MSG_CHUNK, payload), release_slot=release_slot)
        elif msg_type == WORKER_MSG_DONE:
            self._schedule_queue_put((WORKER_MSG_DONE, None))
        elif msg_type == WORKER_MSG_READY:
            self._schedule_queue_put((WORKER_MSG_READY, None))
        elif msg_type == WORKER_MSG_ERROR:
            self._schedule_queue_put((WORKER_MSG_ERROR, payload))
        else:
            logger.warning("ResponsePusher: unknown worker msg_type=%s", msg_type)
            if release_slot:
                self._pending_slots().release()


__all__ = [
    "ResponsePusher",
    "WORKER_MSG_CANCELLED",
    "WORKER_MSG_CHUNK",
    "WORKER_MSG_DONE",
    "WORKER_MSG_READY",
    "WORKER_MSG_ERROR",
    "WORKER_MSG_TIMEOUT",
    "_DEFAULT_SLOTS_PER_WORKER",
    "_pending_slots_for",
    "_chunk_is_goal_completion",
    "_chunk_is_execute_phase",
    "_EXECUTE_PHASE_SEMAPHORE_ACQUIRE_TIMEOUT_SECONDS",
]
