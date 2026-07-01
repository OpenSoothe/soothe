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

IG-535 Optimization 2: Added batched apply mode to reduce DOM mutations per chunk.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Generic, TypeVar

from soothe_sdk.ux.loop_stream import assistant_output_phase

from soothe_cli.runtime.state.session_stats import TurnLatencyStats

logger = logging.getLogger(__name__)

T = TypeVar("T")
_SENTINEL = object()

# Lower number = higher priority (matches asyncio.PriorityQueue ordering).
PRIORITY_HIGH = 0
PRIORITY_NORMAL = 1
PRIORITY_LOW = 2

# IG-535: Batching defaults for TUI apply path optimization
_DEFAULT_BATCH_SIZE = 10
_DEFAULT_BATCH_DELAY_MS = 50

# IG-535: Queue sizes tuned for 32 concurrent loops with dense streaming
# Inbound: daemon→TUI chunks; Outbound: processed→UI apply plans
_DEFAULT_INBOUND_MAXSIZE = 2048  # IG-535: Increased from 1024 for multi-loop throughput
_DEFAULT_OUTBOUND_MAXSIZE = 1024  # IG-535: Increased from 512 for batched apply backlog


class TurnApplyBatcher(Generic[T]):
    """IG-535 Optimization 2: Accumulate prepared chunks for batched apply.

    Reduces DOM mutations per chunk by batching up to N chunks before applying.
    HIGH priority items trigger immediate flush for responsiveness.

    Args:
        max_batch_size: Maximum chunks per batch (default 10).
        max_batch_delay_ms: Maximum delay before forced flush (default 50ms).
    """

    def __init__(
        self,
        *,
        max_batch_size: int = _DEFAULT_BATCH_SIZE,
        max_batch_delay_ms: int = _DEFAULT_BATCH_DELAY_MS,
    ) -> None:
        self._max_batch_size = max_batch_size
        self._max_batch_delay_s = max_batch_delay_ms / 1000.0
        self._pending: list[T] = []
        self._high_priority_count: int = 0
        self._last_flush_monotonic: float = time.monotonic()

    def add(self, prepared: T) -> bool:
        """Add chunk to batch. Returns True if batch should flush now.

        Flush triggers:
        1. Batch size threshold reached
        2. HIGH priority item present (immediate for responsiveness)
        3. Time threshold elapsed
        """
        self._pending.append(prepared)
        priority = getattr(prepared, "priority", PRIORITY_LOW)
        if priority == PRIORITY_HIGH:
            self._high_priority_count += 1

        now = time.monotonic()
        if len(self._pending) >= self._max_batch_size:
            return True
        if self._high_priority_count > 0:
            return True
        if now - self._last_flush_monotonic >= self._max_batch_delay_s:
            return True
        return False

    def flush(self) -> list[T]:
        """Return accumulated batch and reset state."""
        batch = list(self._pending)
        self._pending.clear()
        self._high_priority_count = 0
        self._last_flush_monotonic = time.monotonic()
        return batch

    def has_pending(self) -> bool:
        """Return True if there are pending items."""
        return bool(self._pending)

    @property
    def pending_count(self) -> int:
        """Return number of pending items."""
        return len(self._pending)


class TurnEventPipeline(Generic[T]):
    """Bridge daemon chunk ingestion, background processing, and UI application."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        inbound_maxsize: int = _DEFAULT_INBOUND_MAXSIZE,
        outbound_maxsize: int = _DEFAULT_OUTBOUND_MAXSIZE,
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


def _record_apply_latency(prepared: Any, latency: TurnLatencyStats | None) -> None:
    """IG-534 Phase 3: record first-chunk and synthesis-visible timings."""
    if latency is None or getattr(prepared, "skip", False):
        return
    latency.record_first_chunk()
    if getattr(prepared, "mode", None) == "messages":
        message = getattr(prepared, "normalized_message", None)
        if message is not None and assistant_output_phase(message) == "goal_completion":
            latency.record_goal_completion()


async def run_turn_pipeline(
    chunk_source: AsyncIterator[Any],
    process_fn: Callable[[Any], T],
    apply_fn: Callable[[T], Any],
    *,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    batch_delay_ms: int = _DEFAULT_BATCH_DELAY_MS,
    batching_enabled: bool = True,
    latency_stats: TurnLatencyStats | None = None,
) -> None:
    """Run reader, processor thread, and applier coroutine to completion.

    IG-535: Added batched apply mode to reduce DOM mutations per chunk.

    Args:
        chunk_source: Async iterator of daemon stream chunks.
        process_fn: Sync chunk processor (runs in background thread).
        apply_fn: Async callable applied on the main loop for each prepared plan.
        batch_size: Maximum chunks per batch when batching enabled (default 10).
        batch_delay_ms: Maximum delay before forced flush (default 50ms).
        batching_enabled: Enable batching for performance (default True; disable for debug).
        latency_stats: Optional per-turn latency recorder (IG-534 Phase 3).
    """
    loop = asyncio.get_running_loop()
    if latency_stats is not None and latency_stats.turn_start_monotonic <= 0:
        latency_stats.turn_start_monotonic = time.monotonic()
    pipeline: TurnEventPipeline[T] = TurnEventPipeline(loop)
    pipeline.start_processor(process_fn)

    async def _apply_with_latency(prepared: T) -> None:
        _record_apply_latency(prepared, latency_stats)
        await apply_fn(prepared)

    if batching_enabled:
        batcher: TurnApplyBatcher[T] = TurnApplyBatcher(
            max_batch_size=batch_size,
            max_batch_delay_ms=batch_delay_ms,
        )

        async def _apply_batched() -> None:
            """Apply chunks in batches with single yield per batch."""
            async for prepared in pipeline.iter_prepared():
                if batcher.add(prepared):
                    batch = batcher.flush()
                    # Apply all items in batch
                    for p in batch:
                        await _apply_with_latency(p)
                    # Single yield to event loop per batch (IG-535)
                    await asyncio.sleep(0)

            # Final flush for remaining items
            if batcher.has_pending():
                for p in batcher.flush():
                    await _apply_with_latency(p)

        try:
            await asyncio.gather(
                pipeline.feed_chunks(chunk_source),
                _apply_batched(),
            )
        finally:
            pipeline.shutdown()
    else:
        # Original non-batched path (for debugging or high-frequency streams)
        async def _apply_all() -> None:
            async for prepared in pipeline.iter_prepared():
                await _apply_with_latency(prepared)

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
    "TurnApplyBatcher",
    "TurnEventPipeline",
    "run_turn_pipeline",
    "_DEFAULT_BATCH_SIZE",
    "_DEFAULT_BATCH_DELAY_MS",
    "_DEFAULT_INBOUND_MAXSIZE",
    "_DEFAULT_OUTBOUND_MAXSIZE",
]
