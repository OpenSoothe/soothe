"""Pluggable persistence backends for context and memory stores."""

from __future__ import annotations

from typing import Any

from soothe_sdk.protocols.persistence import AsyncPersistStore


def create_persist_store(
    persist_dir: str | None = None,
    backend: str = "sqlite",
    dsn: str | None = None,
    namespace: str = "default",
    db_path: str | None = None,
    reader_pool_size: int = 8,
    *,
    config: Any | None = None,
    shared_pool: Any | None = None,
) -> AsyncPersistStore | None:
    """Factory for async persistence backends.

    Args:
        persist_dir: Root directory for file-based backends. None disables file persistence.
        backend: Backend type (``postgresql`` or ``sqlite``).
        dsn: PostgreSQL DSN (required for backend="postgresql").
        namespace: Namespace for key isolation (PostgreSQL and SQLite).
        db_path: SQLite database file path (SQLite only).
        reader_pool_size: SQLite reader connection pool size for concurrent reads.
        config: Optional ``SootheConfig`` for PostgreSQL pool sizing.
        shared_pool: Optional shared ``AsyncConnectionPool`` for metadata (daemon mode).

    Returns:
        An AsyncPersistStore instance, or None if persistence is disabled.
    """
    if backend == "postgresql":
        if not dsn:
            raise ValueError("DSN required for PostgreSQL backend")
        from soothe_nano.backends.persistence.postgres_store import PostgreSQLPersistStore

        pool_size = 10
        pool_timing = None
        if config is not None:
            from soothe_nano.persistence.postgres_pool_lifecycle import (
                postgres_pool_timing_from_config,
            )

            pool_size = config.persistence.metadata_pool_size
            pool_timing = postgres_pool_timing_from_config(config, max_size=pool_size)

        if shared_pool is not None:
            return PostgreSQLPersistStore(
                dsn=dsn,
                namespace=namespace,
                pool_size=0,
                shared_pool=shared_pool,
            )

        return PostgreSQLPersistStore(
            dsn=dsn,
            namespace=namespace,
            pool_size=pool_size,
            pool_timing=pool_timing,
        )

    if backend == "sqlite":
        from soothe_nano.backends.persistence.sqlite_store import SQLitePersistStore

        return SQLitePersistStore(db_path, namespace=namespace, reader_pool_size=reader_pool_size)

    raise ValueError(f"Unknown persistence backend: {backend!r}. Supported: 'postgresql', 'sqlite'")
