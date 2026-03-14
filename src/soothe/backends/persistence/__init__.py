"""Pluggable persistence backends for context and memory stores."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PersistStore(Protocol):
    """Simple key-value persistence interface.

    Both JSON-file and RocksDB backends implement this protocol.
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


def create_persist_store(
    persist_dir: str | None,
    backend: str = "json",
) -> PersistStore | None:
    """Factory for persistence backends.

    Args:
        persist_dir: Root directory for persistence. None disables persistence.
        backend: Backend type (``json`` or ``rocksdb``).

    Returns:
        A PersistStore instance, or None if persistence is disabled.
    """
    if not persist_dir:
        return None

    if backend == "rocksdb":
        from soothe.backends.persistence.rocksdb_store import RocksDBPersistStore

        return RocksDBPersistStore(persist_dir)

    from soothe.backends.persistence.json_store import JsonPersistStore

    return JsonPersistStore(persist_dir)
