"""RocksDB-based durability backend for thread lifecycle and metadata."""

from __future__ import annotations

from soothe_daemon.backends.durability.base import BasePersistStoreDurability
from soothe_daemon.backends.persistence import PersistStore


class RocksDBDurability(BasePersistStoreDurability):
    """DurabilityProtocol implementation using RocksDB for persistence.

    Stores thread metadata and state in a RocksDB database for durability
    and performance.
    """

    def __init__(self, persist_store: PersistStore) -> None:
        """Initialize RocksDB durability backend.

        Args:
            persist_store: PersistStore instance backed by RocksDB.
        """
        super().__init__(persist_store)
