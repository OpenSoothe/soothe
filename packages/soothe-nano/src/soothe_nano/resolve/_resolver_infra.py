"""Infrastructure resolution: durability and checkpointer backends.

Extracted from ``resolver.py`` to isolate persistence infrastructure
from protocol and tool/subagent resolution.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_sdk.core.exceptions import ConfigurationError

from soothe_nano.config import SootheConfig

if TYPE_CHECKING:
    from langgraph.types import Checkpointer
    from soothe_sdk.protocols.durability import DurabilityProtocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Durability
# ---------------------------------------------------------------------------


def resolve_durability(config: SootheConfig) -> DurabilityProtocol:
    """Instantiate the DurabilityProtocol implementation from config.

    Supports: postgresql, sqlite backends (binary choice).
    Uses RFC-612 multi-database architecture for PostgreSQL (metadata database).
    """
    backend = config.resolve_durability_backend()  # Resolve inheritance
    if backend == "postgresql":
        try:
            from soothe_nano.backends.durability.postgresql import PostgreSQLDurability
            from soothe_nano.backends.persistence import create_persist_store
            from soothe_nano.persistence.shared_metadata_pool import SharedMetadataPool

            # RFC-612: Use dedicated metadata database
            dsn = config.resolve_postgres_dsn_for_database("metadata")
            shared_pool = SharedMetadataPool.get_or_create_pool(config)
            persist_store = create_persist_store(
                backend="postgresql",
                dsn=dsn,
                namespace="durability",
                config=config,
                shared_pool=shared_pool,
            )
            logger.debug("Using PostgreSQL durability backend (metadata database)")
            return PostgreSQLDurability(persist_store=persist_store)
        except Exception as e:
            logger.error(
                "PostgreSQL durability requested but failed: %s. "
                "Check PostgreSQL configuration and connectivity. "
                "Ensure soothe is up to date: pip install -U soothe",
                e,
            )
            raise ConfigurationError(
                f"PostgreSQL durability backend unavailable: {e}\n"
                f"Verify postgres_base_dsn and postgres_databases configuration.\n"
                f"Ensure metadata database is created and accessible."
            )

    if backend == "sqlite":
        try:
            from soothe_nano.backends.durability.sqlite import SQLiteDurability

            logger.info("Using SQLite durability backend (metadata.db)")
            return SQLiteDurability()
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
        f"Unknown durability backend: {backend}\nSupported backends: postgresql, sqlite"
    )


# ---------------------------------------------------------------------------
# Checkpointer
# ---------------------------------------------------------------------------


def resolve_checkpointer(config: SootheConfig) -> tuple[Checkpointer, Any] | Checkpointer:
    """Resolve a LangGraph checkpointer from config.

    Uses persistence configuration for PostgreSQL or SQLite connection.
    RFC-612: Uses dedicated checkpoints database for PostgreSQL.
    No fallback to in-memory storage - persistent storage required.

    Returns:
        A tuple of (checkpointer, connection_resource) for PostgreSQL, or just the checkpointer for SQLite.
        The connection_resource must be closed during cleanup (e.g., via runner.cleanup()).
    """
    backend = config.resolve_checkpointer_backend()  # Resolve inheritance
    if backend == "postgresql":
        from soothe_nano.resolve.shared_checkpointer_pool import SharedCheckpointerPool

        pool = SharedCheckpointerPool.get_or_create_pool(config)
        if pool is not None:
            return (None, pool)
        logger.error("PostgreSQL checkpointer unavailable")
        raise ConfigurationError(
            "PostgreSQL checkpointer requested but failed.\n"
            "Check postgres_base_dsn and postgres_databases configuration.\n"
            "Ensure checkpoints database is created and accessible.\n"
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
        from soothe_sdk.paths import SOOTHE_DATA_DIR

        db_path = str(Path(SOOTHE_DATA_DIR) / "soothe_checkpoints.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("Failed to create SQLite checkpointer path: %s", exc)
        return None

    logger.info("SQLite checkpointer path resolved at %s (soothe_checkpoints.db)", db_path)
    return (None, db_path)


def _resolve_postgres_checkpointer(
    dsn: str, *, min_pool_size: int = 4, max_pool_size: int = 24
) -> tuple[Checkpointer, Any] | None:
    """Initialize PostgreSQL checkpointer with provided DSN.

    Args:
        dsn: PostgreSQL connection string for the checkpoints database.
        min_pool_size: ``AsyncConnectionPool`` min_size (warm connections).
        max_pool_size: ``AsyncConnectionPool`` max_size.

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
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: F401
    except ImportError:
        logger.warning(
            "PostgreSQL checkpointer requires 'langgraph-checkpoint-postgres'. "
            "Install with: pip install 'langgraph-checkpoint-postgres'"
        )
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
            min_size=min_pool_size,
            max_size=max_pool_size,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            open=False,
        )

        logger.info(
            "PostgreSQL checkpointer pool created (max_size=%d), DSN: %s",
            max_pool_size,
            _mask_dsn(dsn),
        )
    except Exception as exc:
        logger.warning("Failed to create PostgreSQL connection pool: %s", exc)
        return None
    else:
        return (None, pool)  # type: ignore[return-value]


def _mask_dsn(dsn: str) -> str:
    """Mask password in DSN for logging."""
    import re

    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", dsn)
