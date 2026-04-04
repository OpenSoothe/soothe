"""Infrastructure resolution: durability and checkpointer backends.

Extracted from ``resolver.py`` to isolate persistence infrastructure
from protocol and tool/subagent resolution.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.config import SOOTHE_HOME, SootheConfig

if TYPE_CHECKING:
    from langgraph.types import Checkpointer

    from soothe.protocols.durability import DurabilityProtocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Durability
# ---------------------------------------------------------------------------


def resolve_durability(config: SootheConfig) -> DurabilityProtocol:
    """Instantiate the DurabilityProtocol implementation from config.

    Supports: json, rocksdb, postgresql, sqlite backends.
    Falls back to json durability when other backends fail.
    """
    from pathlib import Path

    if config.protocols.durability.backend == "sqlite":
        try:
            from soothe.backends.durability.sqlite import SQLiteDurability

            db_path = config.persistence.sqlite_path
            logger.info("Using SQLite durability backend")
            return SQLiteDurability(db_path=db_path)
        except Exception as e:
            logger.warning(
                "SQLite durability requested but failed: %s. Falling back to json durability.",
                e,
            )

    if config.protocols.durability.backend == "postgresql":
        try:
            from soothe.backends.durability.postgresql import PostgreSQLDurability
            from soothe.backends.persistence import create_persist_store

            persist_store = create_persist_store(
                backend="postgresql",
                dsn=config.resolve_persistence_postgres_dsn(),
                namespace="durability",
            )
            logger.info("Using PostgreSQL durability backend")
            return PostgreSQLDurability(persist_store=persist_store)
        except Exception as e:
            logger.warning(
                "PostgreSQL durability requested but failed: %s. "
                "Falling back to json durability. "
                "Install with: pip install 'soothe[postgres]'",
                e,
            )

    if config.protocols.durability.backend == "rocksdb":
        try:
            from soothe.backends.durability.rocksdb import RocksDBDurability
            from soothe.backends.persistence import create_persist_store

            persist_dir = config.protocols.durability.persist_dir or str(Path(SOOTHE_HOME) / "durability" / "data")
            persist_store = create_persist_store(persist_dir, backend="rocksdb")

            if persist_store is None:
                msg = f"Failed to create RocksDB store at {persist_dir}"
                raise ValueError(msg)

            logger.info("Using RocksDB durability backend at %s", persist_dir)
            return RocksDBDurability(persist_store)
        except (ImportError, RuntimeError, ValueError) as e:
            logger.warning(
                "RocksDB durability requested but dependencies unavailable: %s. "
                "Falling back to json durability. "
                "Install with: pip install soothe[rocksdb]",
                e,
            )

    if config.protocols.durability.backend in ("json", "postgresql", "rocksdb", "sqlite"):
        from soothe.backends.durability.json import JsonDurability

        persist_dir = config.protocols.durability.persist_dir or str(Path(SOOTHE_HOME) / "durability")
        logger.info("Using json durability backend at %s", persist_dir)
        return JsonDurability(persist_dir=persist_dir)

    logger.warning(
        "Unknown durability backend '%s'; using json durability",
        config.protocols.durability.backend,
    )
    from soothe.backends.durability.json import JsonDurability

    persist_dir = str(Path(SOOTHE_HOME) / "durability")
    return JsonDurability(persist_dir=persist_dir)


# ---------------------------------------------------------------------------
# Checkpointer
# ---------------------------------------------------------------------------


def resolve_checkpointer(config: SootheConfig) -> tuple[Checkpointer, Any] | Checkpointer:
    """Resolve a LangGraph checkpointer from config.

    Uses persistence.soothe_postgres_dsn for PostgreSQL connection.
    Uses SQLite for SQLite checkpointer via langgraph-checkpoint-sqlite.
    Falls back to MemorySaver when backends are unavailable.

    Returns:
        A tuple of (checkpointer, connection_resource) for PostgreSQL, or just the checkpointer for MemorySaver/SQLite.
        The connection_resource must be closed during cleanup (e.g., via runner.cleanup()).
    """
    from langgraph.checkpoint.memory import MemorySaver

    backend = config.protocols.durability.checkpointer
    if backend == "postgresql":
        dsn = config.resolve_persistence_postgres_dsn()
        result = _resolve_postgres_checkpointer(dsn)
        if result:
            return result  # (None, pool)
        logger.info("PostgreSQL checkpointer unavailable, falling back")
        return _resolve_sqlite_checkpointer(config) or MemorySaver()
    if backend == "sqlite":
        result = _resolve_sqlite_checkpointer(config)
        if result:
            return result
        logger.info("SQLite checkpointer unavailable, using MemorySaver")
        return MemorySaver()
    if backend == "memory":
        logger.debug("Using memory checkpointer")
    else:
        logger.warning("Unknown checkpointer backend '%s'; using memory saver", backend)

    return MemorySaver()


def _resolve_sqlite_checkpointer(config: SootheConfig) -> tuple[Checkpointer | None, Any] | None:
    """Initialize SQLite checkpointer via langgraph-checkpoint-sqlite.

    Defers AsyncSqliteSaver creation to async context (same pattern as PostgreSQL).

    Returns:
        A tuple of (None, sqlite3.Connection) if successful, None otherwise.
        The runner will create AsyncSqliteSaver from the connection in async context.
    """
    try:
        import sqlite3
        from pathlib import Path

        db_path = config.persistence.sqlite_path or str(Path(SOOTHE_HOME) / "soothe.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
    except Exception as exc:
        logger.warning("Failed to create SQLite checkpointer connection: %s", exc)
        return None

    logger.info("SQLite checkpointer connection created at %s", db_path)
    return (None, conn)


def _resolve_postgres_checkpointer(dsn: str) -> tuple[Checkpointer, Any] | None:
    """Initialize PostgreSQL checkpointer with provided DSN.

    Returns:
        A tuple of (None, AsyncConnectionPool) if successful, None otherwise.
        The checkpointer will be created from the pool in async context, and the pool must be closed during cleanup.

    Note:
        We defer AsyncPostgresSaver creation to async context to avoid "no running event loop" errors.
        The runner will create the checkpointer from the pool after opening it.
    """
    if not dsn:
        logger.warning("PostgreSQL checkpointer requires DSN configuration")
        return None

    try:
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool
    except ImportError:
        logger.warning("PostgreSQL checkpointer requires 'psycopg-pool'. Install with: pip install 'psycopg-pool'")
        return None

    try:
        pool = AsyncConnectionPool(
            dsn,
            max_size=10,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            open=False,
        )

        logger.info("PostgreSQL connection pool created, DSN: %s", _mask_dsn(dsn))
    except Exception as exc:
        logger.warning("Failed to create PostgreSQL connection pool: %s", exc)
        return None
    else:
        return (None, pool)  # type: ignore[return-value]


def _mask_dsn(dsn: str) -> str:
    """Mask password in DSN for logging."""
    import re

    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", dsn)
