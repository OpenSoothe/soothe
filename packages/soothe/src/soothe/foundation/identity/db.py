"""SQLite / PostgreSQL connection adapter for IdentityService (unified persistence)."""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

_QMARK = re.compile(r"\?")

IdentityBackend = Literal["sqlite", "postgresql"]

_IDENTITY_SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS identity_users (
    user_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    metadata TEXT
);
CREATE TABLE IF NOT EXISTS identity_aksk_pairs (
    aksk_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES identity_users(user_id),
    access_key TEXT NOT NULL UNIQUE,
    secret_key_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS identity_tokens (
    jti TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    aksk_id TEXT NOT NULL REFERENCES identity_aksk_pairs(aksk_id),
    token_type TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS identity_external_mappings (
    mapping_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES identity_users(user_id),
    created_at TEXT NOT NULL,
    UNIQUE(channel, sender_id)
);
CREATE TABLE IF NOT EXISTS identity_revoked_jtis (
    jti TEXT PRIMARY KEY,
    revoked_at TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_identity_aksk_user ON identity_aksk_pairs(user_id);
CREATE INDEX IF NOT EXISTS idx_identity_tokens_user ON identity_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_identity_tokens_aksk ON identity_tokens(aksk_id);
CREATE INDEX IF NOT EXISTS idx_identity_mappings_channel_sender
    ON identity_external_mappings(channel, sender_id);
CREATE INDEX IF NOT EXISTS idx_identity_mappings_user ON identity_external_mappings(user_id);
"""


class IdentityDbConnection:
    """Connection wrapper so IdentityService SQL can use ``?`` placeholders on both backends."""

    def __init__(self, backend: IdentityBackend, conn: Any) -> None:
        self.backend = backend
        self._conn = conn

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> Any:
        if self.backend == "postgresql":
            pg_sql = _QMARK.sub("%s", sql)
            return self._conn.execute(pg_sql, params)
        return self._conn.execute(sql, params)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def open_identity_connection(
    *,
    backend: IdentityBackend,
    db_path: Path | None = None,
    dsn: str | None = None,
) -> IdentityDbConnection:
    """Open a writer connection and ensure identity tables exist."""
    if backend == "postgresql":
        if not dsn:
            raise ValueError("dsn required for postgresql identity backend")
        import psycopg

        conn = psycopg.connect(dsn, autocommit=False)
        with conn.cursor() as cur:
            for statement in (s.strip() for s in _IDENTITY_SCHEMA_PG.split(";") if s.strip()):
                cur.execute(statement)
        conn.commit()
        logger.info("IdentityService initialized: backend=postgresql")
        return IdentityDbConnection("postgresql", conn)

    if db_path is None:
        raise ValueError("db_path required for sqlite identity backend")
    from soothe.foundation.identity.identity_service import initialize_identity_tables_sync

    db_path.parent.mkdir(parents=True, exist_ok=True)
    initialize_identity_tables_sync(db_path)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    logger.info("IdentityService initialized: backend=sqlite path=%s", db_path)
    return IdentityDbConnection("sqlite", conn)


__all__ = [
    "IdentityBackend",
    "IdentityDbConnection",
    "open_identity_connection",
]
