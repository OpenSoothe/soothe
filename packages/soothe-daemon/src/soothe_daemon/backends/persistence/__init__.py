"""Pluggable persistence backends for context and memory stores."""

from __future__ import annotations

from soothe_daemon.protocols.persistence import PersistStore


def create_persist_store(
    persist_dir: str | None = None,
    backend: str = "json",
    dsn: str | None = None,
    namespace: str = "default",
    db_path: str | None = None,
) -> PersistStore | None:
    """Factory for persistence backends.

    Args:
        persist_dir: Root directory for file-based backends (json/rocksdb). None disables file persistence.
        backend: Backend type (``json``, ``rocksdb``, ``postgresql``, or ``sqlite``).
        dsn: PostgreSQL DSN (required for backend="postgresql").
        namespace: Namespace for key isolation (PostgreSQL and SQLite).
        db_path: SQLite database file path (SQLite only).

    Returns:
        A PersistStore instance, or None if persistence is disabled.
    """
    if backend == "postgresql":
        if not dsn:
            raise ValueError("DSN required for PostgreSQL backend")
        from soothe_daemon.backends.persistence.postgres_store import PostgreSQLPersistStore

        return PostgreSQLPersistStore(dsn=dsn, namespace=namespace)

    if backend == "sqlite":
        from soothe_daemon.backends.persistence.sqlite_store import SQLitePersistStore

        return SQLitePersistStore(db_path, namespace=namespace)

    if not persist_dir:
        return None

    if backend == "rocksdb":
        from soothe_daemon.backends.persistence.rocksdb_store import RocksDBPersistStore

        return RocksDBPersistStore(persist_dir)

    from soothe_daemon.backends.persistence.json_store import JsonPersistStore

    return JsonPersistStore(persist_dir)
