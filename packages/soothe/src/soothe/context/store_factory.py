"""Factory helpers for ContextEngine persistence backends."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


def resolve_context_engine_persistence(config: SootheConfig, loop_id: str) -> Any:
    """Return a ContextEngine persistence backend for ``loop_id``.

    Mirrors the backend selection used when StrangeLoop binds ContextEngine.
    """
    persistence_backend = config.persistence.default_backend

    persistence = None
    if persistence_backend == "postgresql":
        from soothe.context.store_pgsql import (
            PgsqlContextPersistence,
        )

        base_dsn = config.persistence.postgres_base_dsn
        if base_dsn:
            db_name = config.persistence.postgres_databases.get("checkpoints", "soothe_checkpoints")
            pgsql_dsn = f"{base_dsn.rstrip('/')}/{db_name}"
        else:
            pgsql_dsn = config.persistence.soothe_postgres_dsn
        if not pgsql_dsn:
            msg = (
                "PostgreSQL persistence backend requires "
                "postgres_base_dsn or soothe_postgres_dsn in config"
            )
            raise ValueError(msg)
        persistence = PgsqlContextPersistence(
            loop_id=loop_id,
            config=config,
        )

    if persistence is None:
        if persistence_backend not in ("sqlite", "postgresql"):
            msg = f"Unknown CE persistence backend: {persistence_backend}"
            raise ValueError(msg)
        from soothe.context.store_sqlite import (
            SqliteContextPersistence,
        )
        from soothe.sloop.checkpoints.runtime_paths import (
            resolve_context_engine_db_path,
        )

        persistence = SqliteContextPersistence(
            loop_id=loop_id,
            db_path=resolve_context_engine_db_path(),
        )

    return persistence


__all__ = ["resolve_context_engine_persistence"]
