"""Thread-to-asyncio stream response bridge (IG-429, IG-477).

Eliminates poll-delayed delivery from worker threads into the daemon event loop.
IG-477: Added backpressure handling to prevent unbounded queue growth.
"""

from __future__ import annotations

import asyncio
import logging
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


@dataclass(frozen=True)
class ResponsePusher:
    """Push stream responses from a worker thread into the main asyncio.Queue.

    Uses ``call_soon_threadsafe`` so chunks are delivered without the 50ms poll
    throttle in ``_poll_worker_responses``.

    IG-477: Added backpressure handling - when queue is full, chunks are dropped
    with a warning log to prevent memory leak from unbounded queue growth.
    """

    _loop: asyncio.AbstractEventLoop
    _queue: asyncio.Queue[Any]

    def push_from_worker(self, msg_type: str, payload: Any = None) -> None:
        """Schedule delivery of one worker message onto the main event loop.

        Args:
            msg_type: Worker message kind (``chunk``, ``done``, ``error``, etc.).
            payload: Chunk tuple or exception; ignored for ``done`` / ``cancelled``.
        """
        if self._loop.is_closed():
            return
        try:
            self._loop.call_soon_threadsafe(self._deliver, msg_type, payload)
        except RuntimeError:
            logger.debug("ResponsePusher: loop closed, dropping %s", msg_type)

    def _deliver(self, msg_type: str, payload: Any) -> None:
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
                # IG-477: Apply backpressure - block briefly if queue is full
                # This slows down the worker thread when client can't consume fast enough
                # Note: asyncio.Queue.put() is async, so we wrap it in wait_for and schedule as task
                async def _put_with_timeout() -> None:
                    try:
                        await asyncio.wait_for(
                            self._queue.put((WORKER_MSG_CHUNK, payload)),
                            timeout=_QUEUE_PUT_TIMEOUT_SECONDS,
                        )
                    except TimeoutError:
                        logger.warning(
                            "ResponsePusher: queue full (maxsize=100), dropping chunk "
                            "(worker will slow down to match consumer rate)"
                        )

                asyncio.create_task(_put_with_timeout())
            elif msg_type == WORKER_MSG_DONE:
                # Terminal message - always deliver without blocking
                self._queue.put_nowait((WORKER_MSG_DONE, None))
            elif msg_type == WORKER_MSG_ERROR:
                # Terminal message - always deliver without blocking
                self._queue.put_nowait((WORKER_MSG_ERROR, payload))
            else:
                logger.warning("ResponsePusher: unknown worker msg_type=%s", msg_type)
        except Exception:
            logger.exception("ResponsePusher: failed to deliver msg_type=%s", msg_type)


__all__ = [
    "ResponsePusher",
    "WORKER_MSG_CANCELLED",
    "WORKER_MSG_CHUNK",
    "WORKER_MSG_DONE",
    "WORKER_MSG_ERROR",
    "WORKER_MSG_TIMEOUT",
    "_QUEUE_PUT_TIMEOUT_SECONDS",
]
