"""PostgreSQL-based durability backend for thread lifecycle and metadata."""

from __future__ import annotations

from soothe_sdk.protocols.persistence import AsyncPersistStore

from soothe_nano.backends.durability.base import BasePersistStoreDurability


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
