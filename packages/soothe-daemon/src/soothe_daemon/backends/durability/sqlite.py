"""DurabilityProtocol implementation using SQLite backend."""

from __future__ import annotations

from typing import TYPE_CHECKING

from soothe_daemon.backends.durability.base import BasePersistStoreDurability
from soothe_daemon.backends.persistence.sqlite_store import SQLitePersistStore

if TYPE_CHECKING:
    from soothe_daemon.protocols.persistence import PersistStore


class SQLiteDurability(BasePersistStoreDurability):
    """Durability protocol implementation backed by SQLite.

    Wraps SQLitePersistStore via the BasePersistStoreDurability composition pattern.
    """

    def __init__(
        self,
        persist_store: PersistStore | None = None,
        db_path: str | None = None,
    ) -> None:
        """Initialize SQLite durability backend.

        Args:
            persist_store: Optional PersistStore instance. If None, creates SQLitePersistStore.
            db_path: Database file path. Used only when persist_store is None.
        """
        if persist_store is None:
            persist_store = SQLitePersistStore(db_path, namespace="durability")
        super().__init__(persist_store)
