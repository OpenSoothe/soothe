"""PostgreSQL-based durability backend for thread lifecycle and metadata."""

from __future__ import annotations

from soothe_daemon.backends.durability.base import BasePersistStoreDurability
from soothe_daemon.backends.persistence import PersistStore


class PostgreSQLDurability(BasePersistStoreDurability):
    """DurabilityProtocol implementation using PostgreSQL.

    Uses PostgreSQLPersistStore for thread metadata storage.
    All ThreadInfo objects are serialized as JSONB.
    """

    def __init__(self, persist_store: PersistStore) -> None:
        """Initialize with PostgreSQL persist store.

        Args:
            persist_store: A PersistStore instance backed by PostgreSQL.
        """
        super().__init__(persist_store)
