"""Infrastructure resolution: durability and checkpointer backends.

Extracted from ``resolver.py`` to isolate persistence infrastructure
from protocol and tool/subagent resolution.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe_sdk.client.config import SOOTHE_DATA_DIR
from soothe_sdk.exceptions import ConfigurationError

from soothe.config import SootheConfig

if TYPE_CHECKING:
    from langgraph.types import Checkpointer

    from soothe.protocols.durability import DurabilityProtocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Durability
# ---------------------------------------------------------------------------


def resolve_durability(config: SootheConfig) -> DurabilityProtocol:
    """Instantiate the DurabilityProtocol implementation from config.

    Supports: postgresql, sqlite backends (binary choice).
    """
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
            logger.error(
                "PostgreSQL durability requested but failed: %s. "
                "Check PostgreSQL configuration and connectivity. "
                "Install with: pip install 'soothe[postgres]'",
                e,
            )
            raise ConfigurationError(
                f"PostgreSQL durability backend unavailable: {e}\n"
                f"Verify postgres_base_dsn configuration and PostgreSQL connectivity."
            )

    if config.protocols.durability.backend == "sqlite":
        try:
            from soothe.backends.durability.sqlite import SQLiteDurability

            db_path = config.persistence.metadata_sqlite_path
            logger.info("Using SQLite durability backend (metadata.db)")
            return SQLiteDurability(db_path=db_path)
        except Exception as e:
            logger.error(
                "SQLite durability requested but failed: %s. "
                "Check sqlite3 installation and path configuration.",
                e,
            )
            raise ConfigurationError(
                f"SQLite durability backend unavailable: {e}\nVerify database path configuration."
            )

    raise ConfigurationError(
        f"Unknown durability backend: {config.protocols.durability.backend}\n"
        f"Supported backends: postgresql, sqlite"
    )


# ---------------------------------------------------------------------------
# Checkpointer
# ---------------------------------------------------------------------------


def resolve_checkpointer(config: SootheConfig) -> tuple[Checkpointer, Any] | Checkpointer:
    """Resolve a LangGraph checkpointer from config.

    Uses persistence configuration for PostgreSQL or SQLite connection.
    No fallback to in-memory storage - persistent storage required.

    Returns:
        A tuple of (checkpointer, connection_resource) for PostgreSQL, or just the checkpointer for SQLite.
        The connection_resource must be closed during cleanup (e.g., via runner.cleanup()).
    """
    backend = config.protocols.durability.checkpointer
    if backend == "postgresql":
        dsn = config.resolve_persistence_postgres_dsn()
        result = _resolve_postgres_checkpointer(dsn)
        if result:
            return result  # (None, pool)
        logger.error("PostgreSQL checkpointer unavailable")
        raise ConfigurationError(
            "PostgreSQL checkpointer requested but failed.\n"
            "Check DSN configuration and PostgreSQL connectivity.\n"
            "No fallback - production requires persistent storage."
        )

    if backend == "sqlite":
        result = _resolve_sqlite_checkpointer(config)
        if result:
            return result
        logger.error("SQLite checkpointer unavailable")
        raise ConfigurationError(
            "SQLite checkpointer requested but failed.\n"
            "Check sqlite3 installation and path configuration.\n"
            "No fallback - persistent storage required."
        )

    raise ConfigurationError(
        f"Unknown checkpointer backend: {backend}\n"
        f"Supported: postgresql, sqlite\n"
        f"No in-memory fallback - persistent storage required."
    )


def _resolve_sqlite_checkpointer(config: SootheConfig) -> tuple[Checkpointer | None, Any] | None:
    """Initialize SQLite checkpointer via langgraph-checkpoint-sqlite.

    Defers AsyncSqliteSaver creation to async context (same pattern as PostgreSQL).

    Returns:
        A tuple of (None, db_path) if successful, None otherwise.
        The runner will create AsyncSqliteSaver from the path in async context.
    """
    try:
        from pathlib import Path

        # Use new checkpoint_sqlite_path for LangGraph checkpoints (langgraph_checkpoints.db)
        db_path = config.persistence.checkpoint_sqlite_path or str(
            Path(SOOTHE_DATA_DIR) / "langgraph_checkpoints.db"
        )
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("Failed to create SQLite checkpointer path: %s", exc)
        return None

    logger.info("SQLite checkpointer path resolved at %s (langgraph_checkpoints.db)", db_path)
    return (None, db_path)


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
        logger.warning(
            "PostgreSQL checkpointer requires 'psycopg-pool'. Install with: pip install 'psycopg-pool'"
        )
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
