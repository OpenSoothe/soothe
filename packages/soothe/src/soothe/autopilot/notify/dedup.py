"""Durable at-most-once keys for job notify intents (IG-713)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe_sdk.protocols.persistence import AsyncPersistStore

logger = logging.getLogger(__name__)

_DEDUP_PREFIX = "autopilot:notify_dedup:"


class NotifyDedupStore:
    """Remember delivered ``NotifyIntent.dedup_key`` values.

    Uses ``AsyncPersistStore`` when available; otherwise an in-memory set.
    """

    def __init__(self, store: AsyncPersistStore | None = None) -> None:
        self._store = store
        self._memory: set[str] = set()

    @staticmethod
    def _key(dedup_key: str) -> str:
        return f"{_DEDUP_PREFIX}{dedup_key}"

    async def already_sent(self, dedup_key: str) -> bool:
        """Return True when this intent was already dispatched."""
        if dedup_key in self._memory:
            return True
        if self._store is None:
            return False
        try:
            raw = await self._store.load(self._key(dedup_key))
        except Exception:
            logger.debug("Notify dedup read failed for %s", dedup_key, exc_info=True)
            return False
        if raw is None:
            return False
        self._memory.add(dedup_key)
        return True

    async def mark_sent(self, dedup_key: str) -> None:
        """Record a successful dispatch decision (before/after fan-out)."""
        self._memory.add(dedup_key)
        if self._store is None:
            return
        try:
            await self._store.save(self._key(dedup_key), {"sent": True})
        except Exception:
            logger.debug("Notify dedup write failed for %s", dedup_key, exc_info=True)
