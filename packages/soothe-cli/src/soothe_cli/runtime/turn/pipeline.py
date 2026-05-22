"""Decouple daemon stream ingestion from chunk processing and UI application.

Three stages run concurrently during a TUI turn:

1. **Reader** (async, main event loop): pulls ``(namespace, mode, data)`` tuples from the
   daemon and enqueues them.
2. **Processor** (dedicated thread): runs CPU-heavy parsing / routing without blocking
   Textual rendering.
3. **Applier** (async, main event loop): consumes prepared plans and performs widget
   updates.

The websocket client stays on the main asyncio loop; only synchronous work moves off it.
High-priority chunks (tool wire, loop step events) are applied before low-priority text.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any, Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
_SENTINEL = object()

# Lower number = higher priority (matches asyncio.PriorityQueue ordering).
PRIORITY_HIGH = 0
PRIORITY_NORMAL = 1
PRIORITY_LOW = 2


class TurnEventPipeline(Generic[T]):
    """Bridge daemon chunk ingestion, background processing, and UI application."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        inbound_maxsize: int = 1024,
        outbound_maxsize: int = 512,
    ) -> None:
        self._loop = loop
        self._inbound: queue.Queue[Any] = queue.Queue(maxsize=inbound_maxsize)
        # Thread-safe outbound bridge: processor puts without blocking the event loop.
        self._outbound: queue.PriorityQueue[tuple[int, int, Any]] = queue.PriorityQueue(
            maxsize=outbound_maxsize
        )
        self._outbound_seq = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._processor_error: BaseException | None = None

    async def feed_chunks(self, chunk_source: AsyncIterator[Any]) -> None:
        """Read all chunks from *chunk_source* into the inbound queue."""
        try:
            async for chunk in chunk_source:
                if self._stop.is_set():
                    break
                await asyncio.to_thread(self._inbound.put, chunk)
        finally:
            await asyncio.to_thread(self._inbound.put, _SENTINEL)

    def start_processor(
        self,
        process_fn: Callable[[Any], T],
    ) -> None:
        """Start the background processor thread.

        Args:
            process_fn: Synchronous function mapping one raw chunk to a prepared plan.
        """

        def _worker() -> None:
            while not self._stop.is_set():
                try:
                    item = self._inbound.get(timeout=0.25)
                except queue.Empty:
                    continue
                if item is _SENTINEL:
                    self._put_outbound(PRIORITY_LOW, _SENTINEL)
                    break
                try:
                    prepared = process_fn(item)
                except Exception as exc:
                    logger.exception("Turn chunk processor failed")
                    self._processor_error = exc
                    self._put_outbound(PRIORITY_LOW, _SENTINEL)
                    break
                if prepared is None:
                    continue
                priority = getattr(prepared, "priority", PRIORITY_LOW)
                self._put_outbound(int(priority), prepared)

        self._thread = threading.Thread(
            target=_worker,
            name="soothe-tui-turn-processor",
            daemon=True,
        )
        self._thread.start()

    def _put_outbound(self, priority: int, item: Any) -> None:
        """Enqueue a prepared chunk from the processor thread (thread-safe, non-blocking)."""
        seq = self._outbound_seq
        self._outbound_seq += 1
        try:
            self._outbound.put_nowait((priority, seq, item))
        except queue.Full:
            logger.warning("Turn outbound queue full; dropping prepared chunk")

    async def iter_prepared(self) -> AsyncIterator[T]:
        """Yield prepared chunk plans until the stream ends."""
        while True:
            _priority, _seq, item = await asyncio.to_thread(self._outbound.get)
            if item is _SENTINEL:
                if self._processor_error is not None:
                    raise self._processor_error
                break
            yield item

    def shutdown(self) -> None:
        """Signal the processor thread to stop (best-effort)."""
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)


async def run_turn_pipeline(
    chunk_source: AsyncIterator[Any],
    process_fn: Callable[[Any], T],
    apply_fn: Callable[[T], Any],
) -> None:
    """Run reader, processor thread, and applier coroutine to completion.

    Args:
        chunk_source: Async iterator of daemon stream chunks.
        process_fn: Sync chunk processor (runs in background thread).
        apply_fn: Async callable applied on the main loop for each prepared plan.
    """
    loop = asyncio.get_running_loop()
    pipeline: TurnEventPipeline[T] = TurnEventPipeline(loop)
    pipeline.start_processor(process_fn)

    async def _apply_all() -> None:
        async for prepared in pipeline.iter_prepared():
            await apply_fn(prepared)

    try:
        await asyncio.gather(
            pipeline.feed_chunks(chunk_source),
            _apply_all(),
        )
    finally:
        pipeline.shutdown()


__all__ = [
    "PRIORITY_HIGH",
    "PRIORITY_LOW",
    "PRIORITY_NORMAL",
    "TurnEventPipeline",
    "run_turn_pipeline",
]
