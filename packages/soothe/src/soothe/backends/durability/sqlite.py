"""DurabilityProtocol implementation using SQLite backend."""

from __future__ import annotations

from typing import TYPE_CHECKING

from soothe.backends.durability.base import BasePersistStoreDurability
from soothe.backends.persistence.sqlite_store import SQLitePersistStore

if TYPE_CHECKING:
    from soothe.protocols.persistence import PersistStore


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
                Defaults to metadata.db for ThreadInfo storage.
        """
        if persist_store is None:
            # Default to data/metadata.db for clear separation from data/checkpoints.db
            from pathlib import Path

            from soothe_sdk.client.config import SOOTHE_DATA_DIR

            actual_path = db_path or str(Path(SOOTHE_DATA_DIR) / "metadata.db")
            persist_store = SQLitePersistStore(actual_path, namespace="durability")
        super().__init__(persist_store)
