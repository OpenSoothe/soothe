"""Durable at-most-once keys for job notify intents (IG-713)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe_sdk.protocols.persistence import AsyncPersistStore

logger = logging.getLogger(__name__)

_DEDUP_PREFIX = "autopilot:notify_dedup:"


class NotifyDedupStore:
    """Remember delivered ``NotifyIntent.dedup_key`` values.

    Uses ``AsyncPersistStore`` when available; otherwise an in-memory set.
    Keys expire after ``ttl_seconds`` (default 86400s = 24h) so that
    long-running jobs can re-notify when state changes after the TTL window.
    Set ``ttl_seconds=0`` to disable expiry (keys persist indefinitely).
    """

    def __init__(
        self,
        store: AsyncPersistStore | None = None,
        *,
        ttl_seconds: int = 86400,
    ) -> None:
        self._store = store
        self._ttl_seconds = max(0, int(ttl_seconds))
        self._memory: dict[str, float] = {}  # dedup_key -> timestamp

    @staticmethod
    def _key(dedup_key: str) -> str:
        return f"{_DEDUP_PREFIX}{dedup_key}"

    def _is_expired(self, ts: float) -> bool:
        """Return True if the stored timestamp is past the TTL window."""
        if self._ttl_seconds <= 0:
            return False  # No expiry
        return (time.monotonic() - ts) >= self._ttl_seconds

    async def already_sent(self, dedup_key: str) -> bool:
        """Return True when this intent was already dispatched (within TTL)."""
        now = time.monotonic()
        # Check in-memory store first
        entry = self._memory.get(dedup_key)
        if entry is not None:
            if self._is_expired(entry):
                del self._memory[dedup_key]
            else:
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
        # Check TTL on persisted entries
        stored_ts = raw.get("ts") if isinstance(raw, dict) else None
        if stored_ts is not None and self._is_expired(float(stored_ts)):
            return False  # Expired — allow re-notification
        self._memory[dedup_key] = now
        return True

    async def mark_sent(self, dedup_key: str) -> None:
        """Record a successful dispatch decision (before/after fan-out)."""
        now = time.monotonic()
        self._memory[dedup_key] = now
        if self._store is None:
            return
        try:
            await self._store.save(self._key(dedup_key), {"sent": True, "ts": now})
        except Exception:
            logger.debug("Notify dedup write failed for %s", dedup_key, exc_info=True)
