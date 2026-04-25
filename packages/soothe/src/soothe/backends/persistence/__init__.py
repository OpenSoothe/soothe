"""Pluggable persistence backends for context and memory stores."""

from __future__ import annotations

from soothe.protocols.persistence import AsyncPersistStore


def create_persist_store(
    persist_dir: str | None = None,
    backend: str = "sqlite",
    dsn: str | None = None,
    namespace: str = "default",
    db_path: str | None = None,
) -> AsyncPersistStore | None:
    """Factory for async persistence backends.

    Args:
        persist_dir: Root directory for file-based backends. None disables file persistence.
        backend: Backend type (``postgresql`` or ``sqlite``).
        dsn: PostgreSQL DSN (required for backend="postgresql").
        namespace: Namespace for key isolation (PostgreSQL and SQLite).
        db_path: SQLite database file path (SQLite only).

    Returns:
        An AsyncPersistStore instance, or None if persistence is disabled.
    """
    if backend == "postgresql":
        if not dsn:
            raise ValueError("DSN required for PostgreSQL backend")
        from soothe.backends.persistence.postgres_store import PostgreSQLPersistStore

        return PostgreSQLPersistStore(dsn=dsn, namespace=namespace)

    if backend == "sqlite":
        from soothe.backends.persistence.sqlite_store import SQLitePersistStore

        return SQLitePersistStore(db_path, namespace=namespace)

    raise ValueError(f"Unknown persistence backend: {backend!r}. Supported: 'postgresql', 'sqlite'")
