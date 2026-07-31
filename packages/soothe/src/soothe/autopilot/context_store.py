"""Daemon-owned storage for GoalDispatchContextContribution entries (RFC-222 revised).

Stores one ``GoalDispatchContextContribution`` per ``goal_id``. Used by the
``ContextProjector`` to merge a goal's parents' contributions into a single
``GoalDispatchContextBundle`` for hydration.

Production qualities of the in-memory implementation:

- **Concurrency-safe**: an ``asyncio.Lock`` guards every mutation and every
  composite read so that concurrent dispatch tasks observe a consistent view.
- **Bounded**: an LRU policy evicts the oldest entries (by write timestamp)
  when ``max_entries`` is exceeded, and time-based eviction removes entries
  older than ``context_retention_hours``. This keeps daemon memory bounded
  across long-running sessions with many goals.
- **Closable**: ``close()`` releases the in-memory state so the daemon can
  shut down cleanly.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from soothe.autopilot.engine_models import GoalDispatchContextContribution

logger = logging.getLogger(__name__)

# Default cap when no config is supplied (keeps backward-compatible tests working).
_DEFAULT_MAX_ENTRIES = 1000
# Default retention window (1 week), matching ContextProjectionConfig default.
_DEFAULT_RETENTION_HOURS = 168


@runtime_checkable
class GoalDispatchContextStoreProtocol(Protocol):
    """Public interface backends must satisfy."""

    async def put(self, goal_id: str, contribution: GoalDispatchContextContribution) -> None:
        """Store the contribution for ``goal_id`` (overwrites prior entry)."""
        ...

    async def get(self, goal_id: str) -> GoalDispatchContextContribution | None:
        """Return the contribution for ``goal_id``, or ``None`` if absent."""
        ...

    async def get_many(self, goal_ids: list[str]) -> dict[str, GoalDispatchContextContribution]:
        """Return a goal_id → contribution map for the requested ids that exist."""
        ...

    async def delete(self, goal_id: str) -> bool:
        """Delete one entry; return True if it existed."""
        ...

    async def delete_many(self, goal_ids: list[str]) -> int:
        """Delete all entries in ``goal_ids``; return the count actually removed."""
        ...

    async def all_goal_ids(self) -> set[str]:
        """Set of every goal_id currently held."""
        ...

    async def written_at(self, goal_id: str) -> datetime | None:
        """Wall-clock timestamp the contribution was written, or None if absent."""
        ...


class InMemoryGoalDispatchContextStore:
    """Bounded, concurrency-safe in-memory implementation.

    Suitable for daemon-resident use when no durability backend is configured.
    Not multi-process safe. A durability-backed implementation
    (``DurabilityGoalDispatchContextStore``) is used when crash recovery
    requires persistence across restarts.

    Args:
        max_entries: Hard cap on the number of contributions held. 0 means
            unbounded. When the cap is exceeded, the oldest entries (by write
            time) are evicted. Defaults to 1000.
        retention_hours: Entries older than this many hours are evicted on
            access. Defaults to 168 (1 week).
    """

    def __init__(
        self,
        *,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        retention_hours: int = _DEFAULT_RETENTION_HOURS,
    ) -> None:
        self._max_entries = max_entries
        self._retention = timedelta(hours=retention_hours)
        # OrderedDict preserves insertion order; move_to_end on access gives LRU.
        self._data: OrderedDict[str, GoalDispatchContextContribution] = OrderedDict()
        self._timestamps: dict[str, datetime] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def put(self, goal_id: str, contribution: GoalDispatchContextContribution) -> None:
        async with self._lock:
            self._ensure_open()
            now = datetime.now(UTC)
            # If key exists, this is an overwrite — update in place.
            if goal_id in self._data:
                self._data[goal_id] = contribution
                self._data.move_to_end(goal_id)  # most-recently-used
                self._timestamps[goal_id] = now
                return
            # New entry.
            self._data[goal_id] = contribution
            self._timestamps[goal_id] = now
            self._evict_if_needed_locked(now)

    async def get(self, goal_id: str) -> GoalDispatchContextContribution | None:
        async with self._lock:
            self._ensure_open()
            self._evict_expired_locked(datetime.now(UTC))
            if goal_id not in self._data:
                return None
            self._data.move_to_end(goal_id)  # mark as most-recently-used
            return self._data[goal_id]

    async def get_many(self, goal_ids: list[str]) -> dict[str, GoalDispatchContextContribution]:
        async with self._lock:
            self._ensure_open()
            now = datetime.now(UTC)
            self._evict_expired_locked(now)
            out: dict[str, GoalDispatchContextContribution] = {}
            for gid in goal_ids:
                entry = self._data.get(gid)
                if entry is not None:
                    out[gid] = entry
                    self._data.move_to_end(gid)  # LRU touch
            return out

    async def delete(self, goal_id: str) -> bool:
        async with self._lock:
            self._ensure_open()
            existed = goal_id in self._data
            self._data.pop(goal_id, None)
            self._timestamps.pop(goal_id, None)
            return existed

    async def delete_many(self, goal_ids: list[str]) -> int:
        async with self._lock:
            self._ensure_open()
            removed = 0
            for gid in goal_ids:
                if gid in self._data:
                    self._data.pop(gid, None)
                    self._timestamps.pop(gid, None)
                    removed += 1
            return removed

    async def all_goal_ids(self) -> set[str]:
        async with self._lock:
            self._ensure_open()
            self._evict_expired_locked(datetime.now(UTC))
            return set(self._data.keys())

    async def written_at(self, goal_id: str) -> datetime | None:
        async with self._lock:
            self._ensure_open()
            return self._timestamps.get(goal_id)

    async def close(self) -> None:
        """Release in-memory state. Subsequent operations raise."""
        async with self._lock:
            self._closed = True
            self._data.clear()
            self._timestamps.clear()

    # ---- locked helpers (caller must hold self._lock) -------------------

    def _ensure_open(self) -> None:
        if self._closed:
            msg = "InMemoryGoalDispatchContextStore is closed"
            raise RuntimeError(msg)

    def _evict_if_needed_locked(self, now: datetime) -> None:
        """Evict by time first, then by LRU if still over quota."""
        self._evict_expired_locked(now)
        if self._max_entries <= 0:
            return
        while len(self._data) > self._max_entries:
            # OrderedDict popitem(last=False) = oldest (first inserted / least recent).
            gid, _ = self._data.popitem(last=False)
            self._timestamps.pop(gid, None)
            logger.debug(
                "Evicted oldest context contribution for goal %s (LRU, cap=%d)",
                gid,
                self._max_entries,
            )

    def _evict_expired_locked(self, now: datetime) -> None:
        """Drop entries whose write timestamp is older than the retention window."""
        if self._retention <= timedelta(0):
            return
        cutoff = now - self._retention
        # Iterate over a snapshot so we can mutate during iteration.
        expired = [gid for gid, ts in self._timestamps.items() if ts < cutoff]
        for gid in expired:
            self._data.pop(gid, None)
            self._timestamps.pop(gid, None)
            logger.debug(
                "Evicted expired context contribution for goal %s (retention=%dh)",
                gid,
                int(self._retention.total_seconds() // 3600),
            )

    # Convenience for tests / observability — not part of the protocol.
    def size(self) -> int:
        """Return current entry count. Not async for test convenience."""
        return len(self._data)
