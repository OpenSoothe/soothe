"""Durability-backed GoalDispatchContextStore (RFC-222 revised).

Persists per-goal ``GoalDispatchContextContribution`` entries through
``AsyncPersistStore`` so parent context survives daemon restarts.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.foundation.autopilot.engine.models import GoalDispatchContextContribution
    from soothe.protocols.persistence import AsyncPersistStore

logger = logging.getLogger(__name__)

_KEY_PREFIX = "autopilot:context:"


class DurabilityGoalDispatchContextStore:
    """Persist contributions via ``AsyncPersistStore``.

    Args:
        store: Async key-value backend (SQLite/PostgreSQL).
    """

    def __init__(self, store: AsyncPersistStore) -> None:
        self._store = store

    def _key(self, goal_id: str) -> str:
        return f"{_KEY_PREFIX}{goal_id}"

    async def put(self, goal_id: str, contribution: GoalDispatchContextContribution) -> None:
        payload = {
            "contribution": contribution.model_dump(mode="json"),
            "written_at": datetime.now(UTC).isoformat(),
        }
        await self._store.save(self._key(goal_id), payload)

    async def get(self, goal_id: str) -> GoalDispatchContextContribution | None:
        from soothe.foundation.autopilot.engine.models import GoalDispatchContextContribution

        raw = await self._store.load(self._key(goal_id))
        if not raw or not isinstance(raw, dict):
            return None
        contrib = raw.get("contribution")
        if not isinstance(contrib, dict):
            return None
        try:
            return GoalDispatchContextContribution.model_validate(contrib)
        except Exception:
            logger.debug("Invalid stored contribution for goal %s", goal_id, exc_info=True)
            return None

    async def get_many(self, goal_ids: list[str]) -> dict[str, GoalDispatchContextContribution]:
        out: dict[str, GoalDispatchContextContribution] = {}
        for gid in goal_ids:
            entry = await self.get(gid)
            if entry is not None:
                out[gid] = entry
        return out

    async def delete(self, goal_id: str) -> bool:
        existing = await self.get(goal_id)
        if existing is None:
            return False
        await self._store.delete(self._key(goal_id))
        return True

    async def delete_many(self, goal_ids: list[str]) -> int:
        removed = 0
        for gid in goal_ids:
            if await self.delete(gid):
                removed += 1
        return removed

    async def all_goal_ids(self) -> set[str]:
        keys = await self._store.list_keys()
        prefix_len = len(_KEY_PREFIX)
        return {k[prefix_len:] for k in keys if k.startswith(_KEY_PREFIX)}

    async def written_at(self, goal_id: str) -> datetime | None:
        raw = await self._store.load(self._key(goal_id))
        if not raw or not isinstance(raw, dict):
            return None
        ts = raw.get("written_at")
        if not isinstance(ts, str):
            return None
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None
