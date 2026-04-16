"""PersistStore protocol -- simple key-value persistence interface."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PersistStore(Protocol):
    """Simple key-value persistence interface.

    Implemented by JsonPersistStore, RocksDBPersistStore, and PostgreSQLPersistStore.
    Provides a storage-agnostic interface for context, memory, and durability backends.
    """

    def save(self, key: str, data: Any) -> None:
        """Persist data under the given key.

        Args:
            key: Storage key.
            data: JSON-serialisable data.
        """
        ...

    def load(self, key: str) -> Any | None:
        """Load data for the given key.

        Args:
            key: Storage key.

        Returns:
            The stored data, or None if not found.
        """
        ...

    def delete(self, key: str) -> None:
        """Delete data for the given key.

        Args:
            key: Storage key.
        """
        ...

    def close(self) -> None:
        """Release any resources held by the store."""
        ...