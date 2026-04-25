"""Adapter wrapping sync PersistStore to AsyncPersistStore interface."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SyncPersistStoreAdapter:
    """Adapter wrapping legacy sync stores to AsyncPersistStore interface.

    Provides backward compatibility for legacy synchronous PersistStore implementations
    (JsonPersistStore, RocksDBPersistStore) by wrapping their sync methods with asyncio.to_thread.

    Note:
        This adapter is for backward compatibility only. New implementations should use
        SQLitePersistStore or PostgreSQLPersistStore which are fully async with connection pooling.

    Example:
        ```python
        from soothe.backends.persistence.sync_adapter import SyncPersistStoreAdapter
        from soothe.backends.persistence.json_store import JsonPersistStore

        legacy_store = JsonPersistStore(persist_dir="/path/to/data")
        async_store = SyncPersistStoreAdapter(legacy_store)

        # Now can use with async interface
        await async_store.save("key", {"data": "value"})
        result = await async_store.load("key")
        ```
    """

    def __init__(self, sync_store: Any) -> None:
        """Initialize adapter with a sync store.

        Args:
            sync_store: Legacy synchronous PersistStore instance.
        """
        self._sync_store = sync_store
        logger.info(
            "SyncPersistStoreAdapter initialized (wrapping %s)",
            type(sync_store).__name__,
        )

    async def save(self, key: str, data: Any) -> None:
        """Async save wrapping sync store.

        Args:
            key: Storage key
            data: JSON-serializable data
        """
        await asyncio.to_thread(self._sync_store.save, key, data)

    async def load(self, key: str) -> Any | None:
        """Async load wrapping sync store.

        Args:
            key: Storage key

        Returns:
            The stored data, or None if not found
        """
        return await asyncio.to_thread(self._sync_store.load, key)

    async def delete(self, key: str) -> None:
        """Async delete wrapping sync store.

        Args:
            key: Storage key
        """
        await asyncio.to_thread(self._sync_store.delete, key)

    async def list_keys(self, namespace: str | None = None) -> list[str]:
        """List keys in namespace (returns empty list for legacy stores).

        Args:
            namespace: Optional namespace (ignored for legacy stores)

        Returns:
            Empty list (legacy sync stores don't support list_keys)
        """
        # Legacy sync stores don't have list_keys method
        # Return empty list to satisfy AsyncPersistStore protocol
        logger.warning(
            "list_keys called on SyncPersistStoreAdapter wrapping %s - returning empty list",
            type(self._sync_store).__name__,
        )
        return []

    async def close(self) -> None:
        """Async close wrapping sync store."""
        await asyncio.to_thread(self._sync_store.close)
        logger.info("SyncPersistStoreAdapter closed")
