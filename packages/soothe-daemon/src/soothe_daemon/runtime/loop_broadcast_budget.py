"""Per-loop in-flight broadcast budget (IG-534 Phase 2.2).

Limits how many stream frames one loop may push toward the EventBus concurrently.
Excess producers block only that loop's stream consumer, not other loops.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class LoopBroadcastBudget:
    """Semaphore-backed budget keyed by ``loop_id``.

    Args:
        max_in_flight_per_loop: Max concurrent in-flight broadcasts per loop.
            ``0`` disables limiting.
    """

    def __init__(self, max_in_flight_per_loop: int) -> None:
        self._limit = max(0, int(max_in_flight_per_loop))
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._guard = asyncio.Lock()

    @property
    def limit(self) -> int:
        """Configured per-loop in-flight cap (``0`` = unlimited)."""
        return self._limit

    async def _semaphore_for(self, loop_id: str) -> asyncio.Semaphore | None:
        if self._limit <= 0:
            return None
        key = str(loop_id or "").strip()
        if not key:
            return None
        async with self._guard:
            sem = self._semaphores.get(key)
            if sem is None:
                sem = asyncio.Semaphore(self._limit)
                self._semaphores[key] = sem
            return sem

    @asynccontextmanager
    async def slot(self, loop_id: str) -> AsyncIterator[None]:
        """Acquire one in-flight slot for ``loop_id`` until the broadcast completes."""
        sem = await self._semaphore_for(loop_id)
        if sem is None:
            yield
            return
        await sem.acquire()
        try:
            yield
        finally:
            sem.release()

    def drop_loop(self, loop_id: str) -> None:
        """Drop cached semaphore state when a loop is garbage-collected."""
        key = str(loop_id or "").strip()
        if key:
            self._semaphores.pop(key, None)


__all__ = ["LoopBroadcastBudget"]
