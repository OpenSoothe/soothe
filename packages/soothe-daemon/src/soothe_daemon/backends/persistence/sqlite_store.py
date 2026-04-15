"""SQLite-backed key-value store implementing PersistStore protocol."""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from soothe.config import SOOTHE_HOME

logger = logging.getLogger(__name__)


class SQLitePersistStore:
    """SQLite-backed key-value persistence implementing PersistStore protocol.

    Uses a single SQLite database with WAL mode for concurrent reads.
    Provides namespace isolation like PostgreSQLPersistStore.
    """

    def __init__(self, db_path: str | None = None, namespace: str = "default") -> None:
        """Initialize SQLite persist store.

        Args:
            db_path: Path to SQLite database file. Defaults to $SOOTHE_HOME/soothe.db.
            namespace: Namespace for key isolation.
        """
        self._namespace = namespace
        self._db_path = db_path or str(Path(SOOTHE_HOME) / "soothe.db")
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _ensure_connection(self) -> sqlite3.Connection:
        """Lazy connection initialization with WAL mode.

        Returns:
            Active SQLite connection.
        """
        if self._conn is not None:
            return self._conn

        with self._lock:
            if self._conn is not None:
                return self._conn

            db_path = Path(self._db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)

            self._conn = sqlite3.connect(
                str(db_path),
                check_same_thread=False,
                timeout=30,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.row_factory = sqlite3.Row

            self._create_table()
            logger.info("SQLite persist store initialized at %s", self._db_path)
            return self._conn

    def _create_table(self) -> None:
        """Create key-value table if it does not exist."""
        if self._conn is None:
            return
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS soothe_kv (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (namespace, key)
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_soothe_kv_namespace ON soothe_kv(namespace)"
        )
        self._conn.commit()

    def save(self, key: str, data: Any) -> None:
        """Persist data under the given key.

        Args:
            key: Storage key.
            data: JSON-serialisable data.
        """
        conn = self._ensure_connection()
        serialized = json.dumps(data, ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO soothe_kv (namespace, key, data, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(namespace, key) DO UPDATE
                SET data = excluded.data, updated_at = CURRENT_TIMESTAMP
            """,
            (self._namespace, key, serialized),
        )
        conn.commit()

    def load(self, key: str) -> Any | None:
        """Load data for the given key.

        Args:
            key: Storage key.

        Returns:
            The stored data, or None if not found.
        """
        conn = self._ensure_connection()
        row = conn.execute(
            "SELECT data FROM soothe_kv WHERE namespace = ? AND key = ?",
            (self._namespace, key),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["data"])

    def delete(self, key: str) -> None:
        """Delete data for the given key.

        Args:
            key: Storage key.
        """
        conn = self._ensure_connection()
        conn.execute(
            "DELETE FROM soothe_kv WHERE namespace = ? AND key = ?",
            (self._namespace, key),
        )
        conn.commit()

    def list_keys(self, namespace: str | None = None) -> list[str]:
        """List all keys in the given namespace.

        Args:
            namespace: Namespace to list keys from. Defaults to store namespace.

        Returns:
            List of keys.
        """
        conn = self._ensure_connection()
        ns = namespace or self._namespace
        rows = conn.execute("SELECT key FROM soothe_kv WHERE namespace = ?", (ns,)).fetchall()
        return [row["key"] for row in rows]

    def close(self) -> None:
        """Commit pending changes and close the connection."""
        if self._conn is not None:
            with self._lock:
                if self._conn is not None:
                    with contextlib.suppress(Exception):
                        self._conn.commit()
                    self._conn.close()
                    self._conn = None
                    logger.info("SQLite persist store closed")
