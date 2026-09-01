"""Debounced checkpoint trigger for workspace persistence.

Waits `debounce_seconds` after the last dirty event before triggering a
checkpoint.  A `max_interval_seconds` guarantees periodic checkpoints even
under continuous activity.  When pending checkpoint count exceeds
`max_pending`, the debounce window is doubled adaptively (backpressure).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_DEFAULT_DEBOUNCE = 5.0  # seconds
_DEFAULT_MAX_INTERVAL = 60.0  # seconds
_DEFAULT_MAX_PENDING = 20


class CheckpointDebouncer:
    """Debounced checkpoint trigger.

    When a dirty event arrives, the debounce timer is reset.  When the
    timer fires (no new events for `debounce_seconds`), the trigger is
    called.  A max-interval timer guarantees periodic checkpoints.

    Args:
        trigger: Callback invoked when a checkpoint should be created.
            Should be an async function.
        debounce_seconds: Seconds to wait after the last dirty event.
        max_interval_seconds: Maximum seconds between checkpoints.
        max_pending: Backpressure threshold.  If the pending checkpoint
            count exceeds this, the debounce window is doubled.
    """

    def __init__(
        self,
        *,
        trigger: Callable[[], object],
        debounce_seconds: float = _DEFAULT_DEBOUNCE,
        max_interval_seconds: float = _DEFAULT_MAX_INTERVAL,
        max_pending: int = _DEFAULT_MAX_PENDING,
    ) -> None:
        self._trigger = trigger
        self._debounce = debounce_seconds
        self._max_interval = max_interval_seconds
        self._max_pending = max_pending
        self._last_trigger = time.monotonic()
        self._dirty_since_last = False
        self._timer: asyncio.Task[None] | None = None
        self._max_timer: asyncio.Task[None] | None = None
        self._running = False
        self._pending_count = 0

    def start(self) -> None:
        """Start the debouncer (begins the max-interval timer)."""
        if self._running:
            return
        self._running = True
        self._last_trigger = time.monotonic()
        self._max_timer = asyncio.create_task(self._max_interval_loop())

    async def stop(self) -> None:
        """Stop the debouncer and cancel pending timers."""
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            try:
                await self._timer
            except asyncio.CancelledError:
                pass
            self._timer = None
        if self._max_timer is not None:
            self._max_timer.cancel()
            try:
                await self._max_timer
            except asyncio.CancelledError:
                pass
            self._max_timer = None

    def notify_dirty(self) -> None:
        """Notify the debouncer that a dirty event arrived.

        Resets the debounce timer.
        """
        if not self._running:
            return
        self._dirty_since_last = True
        if self._timer is not None:
            self._timer.cancel()
        window = self._effective_debounce()
        self._timer = asyncio.create_task(self._debounce_wait(window))

    def set_pending_count(self, count: int) -> None:
        """Set the current pending checkpoint count (for backpressure).

        Args:
            count: Number of checkpoints pending upload.
        """
        self._pending_count = count

    async def flush(self) -> None:
        """Force an immediate checkpoint (bypass debounce).

        Used during workspace cleanup to ensure the final checkpoint
        is written before deletion.
        """
        if self._timer is not None:
            self._timer.cancel()
            try:
                await self._timer
            except asyncio.CancelledError:
                pass
            self._timer = None
        if self._dirty_since_last:
            await self._fire_trigger()
            self._dirty_since_last = False

    def _effective_debounce(self) -> float:
        """Return the effective debounce window.

        If pending count exceeds `max_pending`, the window is doubled
        to slow checkpoint creation.
        """
        if self._pending_count > self._max_pending:
            return self._debounce * 2
        return self._debounce

    async def _debounce_wait(self, window: float) -> None:
        """Wait for the debounce window, then fire the trigger."""
        try:
            await asyncio.sleep(window)
        except asyncio.CancelledError:
            return
        if self._dirty_since_last:
            await self._fire_trigger()
            self._dirty_since_last = False

    async def _max_interval_loop(self) -> None:
        """Guarantee periodic checkpoints even under continuous activity."""
        while self._running:
            await asyncio.sleep(0.05)
            elapsed = time.monotonic() - self._last_trigger
            if elapsed >= self._max_interval and self._dirty_since_last:
                logger.debug("Max-interval checkpoint trigger")
                if self._timer is not None:
                    self._timer.cancel()
                    try:
                        await self._timer
                    except asyncio.CancelledError:
                        pass
                    self._timer = None
                await self._fire_trigger()
                self._dirty_since_last = False

    async def _fire_trigger(self) -> None:
        """Fire the checkpoint trigger callback."""
        self._last_trigger = time.monotonic()
        try:
            result = self._trigger()
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.exception("Error in checkpoint trigger callback")
