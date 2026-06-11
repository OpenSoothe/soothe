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
WORKER_MSG_ERROR = "error"
WORKER_MSG_CANCELLED = "cancelled"
WORKER_MSG_TIMEOUT = "timeout"

# IG-477: Backpressure timeout for queue.put() when queue is full
_QUEUE_PUT_TIMEOUT_SECONDS = 0.5

# IG-477: Limit in-flight chunk deliveries (blocks worker thread when full)
_MAX_PENDING_CALLBACKS = 100

# Semaphore slots == max in-flight chunk deliveries. Worker thread blocks on
# acquire() so LangGraph astream cannot outrun the main-loop consumer.
_pending_slots = threading.Semaphore(_MAX_PENDING_CALLBACKS)


@dataclass(frozen=True)
class ResponsePusher:
    """Push stream responses from a worker thread into the main asyncio.Queue.

    Uses ``call_soon_threadsafe`` so chunks are delivered without the 50ms poll
    throttle in ``_poll_worker_responses``.

    IG-477: Semaphore backpressure blocks the worker thread when too many chunks
    are in flight, preventing LangGraph state from growing without bound when
    downstream delivery is slow.
    """

    _loop: asyncio.AbstractEventLoop
    _queue: asyncio.Queue[Any]

    def push_from_worker(self, msg_type: str, payload: Any = None) -> None:
        """Schedule delivery of one worker message onto the main event loop.

        Args:
            msg_type: Worker message kind (``chunk``, ``done``, ``error``, etc.).
            payload: Chunk tuple or exception; ignored for ``done`` / ``cancelled``.

        For CHUNK messages, blocks the worker thread until a delivery slot is
        available (semaphore acquire). This applies backpressure to LangGraph
        ``astream`` so memory cannot grow unbounded when the consumer is slow.
        """
        if self._loop.is_closed():
            return

        acquired_slot = False
        if msg_type == WORKER_MSG_CHUNK:
            # Block worker thread until downstream catches up (backpressure)
            if not _pending_slots.acquire(timeout=_QUEUE_PUT_TIMEOUT_SECONDS):
                logger.warning(
                    "ResponsePusher: backpressure timeout (limit=%d), dropping chunk "
                    "(downstream consumer too slow)",
                    _MAX_PENDING_CALLBACKS,
                )
                return
            acquired_slot = True

        try:
            self._loop.call_soon_threadsafe(self._deliver, msg_type, payload, acquired_slot)
        except RuntimeError:
            logger.debug("ResponsePusher: loop closed, dropping %s", msg_type)
            if acquired_slot:
                _pending_slots.release()

    def _deliver(self, msg_type: str, payload: Any, release_slot: bool = False) -> None:
        """Run on the main loop thread; map worker types to asyncio.Queue tuples.

        IG-477: Use put() with timeout for chunks to apply backpressure.
        Terminal messages (done/error/cancelled) use put_nowait() to ensure delivery.
        """
        try:
            if msg_type == WORKER_MSG_TIMEOUT:
                self._queue.put_nowait((WORKER_MSG_ERROR, payload))
            elif msg_type == WORKER_MSG_CANCELLED:
                self._queue.put_nowait((WORKER_MSG_ERROR, asyncio.CancelledError()))
            elif msg_type == WORKER_MSG_CHUNK:

                async def _put_with_timeout() -> None:
                    try:
                        await asyncio.wait_for(
                            self._queue.put((WORKER_MSG_CHUNK, payload)),
                            timeout=_QUEUE_PUT_TIMEOUT_SECONDS,
                        )
                    except TimeoutError:
                        logger.warning(
                            "ResponsePusher: asyncio queue full (maxsize=100), dropping chunk"
                        )
                    finally:
                        if release_slot:
                            _pending_slots.release()

                asyncio.create_task(_put_with_timeout())
            elif msg_type == WORKER_MSG_DONE:
                self._queue.put_nowait((WORKER_MSG_DONE, None))
            elif msg_type == WORKER_MSG_ERROR:
                self._queue.put_nowait((WORKER_MSG_ERROR, payload))
            else:
                logger.warning("ResponsePusher: unknown worker msg_type=%s", msg_type)
                if release_slot:
                    _pending_slots.release()
        except Exception:
            logger.exception("ResponsePusher: failed to deliver msg_type=%s", msg_type)
            if release_slot:
                _pending_slots.release()


__all__ = [
    "ResponsePusher",
    "WORKER_MSG_CANCELLED",
    "WORKER_MSG_CHUNK",
    "WORKER_MSG_DONE",
    "WORKER_MSG_ERROR",
    "WORKER_MSG_TIMEOUT",
    "_QUEUE_PUT_TIMEOUT_SECONDS",
    "_MAX_PENDING_CALLBACKS",
]
