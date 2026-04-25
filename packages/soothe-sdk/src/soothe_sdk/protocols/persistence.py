"""AsyncPersistStore protocol -- async key-value persistence interface."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AsyncPersistStore(Protocol):
    """Async key-value persistence interface with concurrent operation support.

    Implemented by SQLitePersistStore and PostgreSQLPersistStore.
    Provides a storage-agnostic async interface for context, memory, and durability backends.

    All methods are async to support concurrent operations and connection pooling.
    """

    async def save(self, key: str, data: Any) -> None:
        """Persist data under the given key.

        Args:
            key: Storage key.
            data: JSON-serialisable data.
        """
        ...

    async def load(self, key: str) -> Any | None:
        """Load data for the given key.

        Args:
            key: Storage key.

        Returns:
            The stored data, or None if not found.
        """
        ...

    async def delete(self, key: str) -> None:
        """Delete data for the given key.

        Args:
            key: Storage key.
        """
        ...

    async def list_keys(self, namespace: str | None = None) -> list[str]:
        """List all keys in the namespace.

        Args:
            namespace: Optional namespace to list keys from. If None, uses default namespace.

        Returns:
            List of keys in the namespace.
        """
        ...

    async def close(self) -> None:
        """Release any resources held by the store."""
        ...
