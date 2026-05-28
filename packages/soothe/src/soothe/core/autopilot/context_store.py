"""Daemon-owned storage for GoalDispatchContextContribution entries (RFC-222 revised).

Stores one ``GoalDispatchContextContribution`` per ``goal_id``. Used by the
``ContextProjector`` to merge a goal's parents' contributions into a single
``GoalDispatchContextBundle`` for hydration.

Phase A scaffolding ships an in-memory implementation. Later phases can
swap in a backend that persists through ``DurabilityProtocol`` without
changing the public interface.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from soothe.core.goal_engine.models import GoalDispatchContextContribution


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
    """In-memory implementation (Phase A scaffolding).

    Thread-safe under single-event-loop asyncio. Suitable for daemon-resident
    use; not multi-process. Phase C will swap in a durability-backed
    implementation when crash recovery requires persistence across restarts.
    """

    def __init__(self) -> None:
        self._data: dict[str, GoalDispatchContextContribution] = {}
        self._timestamps: dict[str, datetime] = {}

    async def put(self, goal_id: str, contribution: GoalDispatchContextContribution) -> None:
        self._data[goal_id] = contribution
        self._timestamps[goal_id] = datetime.now(UTC)

    async def get(self, goal_id: str) -> GoalDispatchContextContribution | None:
        return self._data.get(goal_id)

    async def get_many(self, goal_ids: list[str]) -> dict[str, GoalDispatchContextContribution]:
        out: dict[str, GoalDispatchContextContribution] = {}
        for gid in goal_ids:
            entry = self._data.get(gid)
            if entry is not None:
                out[gid] = entry
        return out

    async def delete(self, goal_id: str) -> bool:
        existed = goal_id in self._data
        self._data.pop(goal_id, None)
        self._timestamps.pop(goal_id, None)
        return existed

    async def delete_many(self, goal_ids: list[str]) -> int:
        removed = 0
        for gid in goal_ids:
            if await self.delete(gid):
                removed += 1
        return removed

    async def all_goal_ids(self) -> set[str]:
        return set(self._data.keys())

    async def written_at(self, goal_id: str) -> datetime | None:
        return self._timestamps.get(goal_id)

    # Convenience for tests / observability — not part of the protocol.
    def size(self) -> int:
        return len(self._data)
