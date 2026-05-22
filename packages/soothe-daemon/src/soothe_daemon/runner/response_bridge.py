"""Thread-to-asyncio stream response bridge (IG-429).

Eliminates poll-delayed delivery from worker threads into the daemon event loop.
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


@dataclass(frozen=True)
class ResponsePusher:
    """Push stream responses from a worker thread into the main asyncio.Queue.

    Uses ``call_soon_threadsafe`` so chunks are delivered without the 50ms poll
    throttle in ``_poll_worker_responses``.
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
        """Run on the main loop thread; map worker types to asyncio.Queue tuples."""
        if msg_type == WORKER_MSG_TIMEOUT:
            self._queue.put_nowait((WORKER_MSG_ERROR, payload))
        elif msg_type == WORKER_MSG_CANCELLED:
            self._queue.put_nowait((WORKER_MSG_ERROR, asyncio.CancelledError()))
        elif msg_type == WORKER_MSG_CHUNK:
            self._queue.put_nowait((WORKER_MSG_CHUNK, payload))
        elif msg_type == WORKER_MSG_DONE:
            self._queue.put_nowait((WORKER_MSG_DONE, None))
        elif msg_type == WORKER_MSG_ERROR:
            self._queue.put_nowait((WORKER_MSG_ERROR, payload))
        else:
            logger.warning("ResponsePusher: unknown worker msg_type=%s", msg_type)


__all__ = [
    "ResponsePusher",
    "WORKER_MSG_CANCELLED",
    "WORKER_MSG_CHUNK",
    "WORKER_MSG_DONE",
    "WORKER_MSG_ERROR",
    "WORKER_MSG_TIMEOUT",
]
