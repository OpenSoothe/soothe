"""PostgreSQL-based durability backend for thread lifecycle and metadata."""

from __future__ import annotations

from soothe.backends.durability.base import BasePersistStoreDurability
from soothe.protocols.persistence import AsyncPersistStore


class PostgreSQLDurability(BasePersistStoreDurability):
    """DurabilityProtocol implementation using PostgreSQL.

    Uses PostgreSQLPersistStore for thread metadata storage.
    All ThreadInfo objects are serialized as JSONB.
    """

    def __init__(self, persist_store: AsyncPersistStore) -> None:
        """Initialize with PostgreSQL persist store.

        Args:
            persist_store: An AsyncPersistStore instance backed by PostgreSQL.
        """
        super().__init__(persist_store)
