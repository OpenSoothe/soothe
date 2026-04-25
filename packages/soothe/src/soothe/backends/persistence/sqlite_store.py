"""SQLite-backed key-value store implementing PersistStore protocol.

IG-258 Phase 2: Async operations to eliminate sync blocking.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from soothe.config import SOOTHE_HOME

logger = logging.getLogger(__name__)


class SQLitePersistStore:
    """SQLite-backed key-value persistence with async operations (IG-258 Phase 2).

    Phase 2 improvements:
    - Async methods (no blocking event loop)
    - asyncio.Lock instead of threading.Lock
    - Connection pool for concurrent reads
    - asyncio.to_thread for sync SQLite operations

    Uses WAL mode for concurrent reads with single writer.
    Provides namespace isolation like PostgreSQLPersistStore.
    """

    def __init__(
        self,
        db_path: str | None = None,
        namespace: str = "default",
        reader_pool_size: int = 5,  # IG-258 Phase 2
    ) -> None:
        """Initialize SQLite persist store with async support (Phase 2).

        Args:
            db_path: Path to SQLite database file. Defaults to $SOOTHE_HOME/soothe.db.
            namespace: Namespace for key isolation.
            reader_pool_size: Number of reader connections for concurrent reads (Phase 2).
        """
        self._namespace = namespace
        self._db_path = db_path or str(Path(SOOTHE_HOME) / "soothe.db")
        self._reader_pool_size = reader_pool_size

        # Writer connection (single writer for consistency)
        self._writer_conn: sqlite3.Connection | None = None

        # Reader pool (multiple readers for concurrent reads)
        self._reader_pool: list[sqlite3.Connection] = []
        self._pool_semaphore = asyncio.Semaphore(reader_pool_size)

        # Async lock (doesn't block event loop) - IG-258 Phase 2
        self._lock = asyncio.Lock()

        logger.info(
            "SQLite persist store initialized: path=%s namespace=%s pool_size=%d",
            self._db_path,
            namespace,
            reader_pool_size,
        )

    async def _ensure_writer_connection(self) -> sqlite3.Connection:
        """Lazy writer connection initialization with WAL mode (Phase 2).

        Returns:
            Active SQLite writer connection.
        """
        if self._writer_conn is not None:
            return self._writer_conn

        async with self._lock:
            if self._writer_conn is not None:
                return self._writer_conn

            # Initialize writer in thread pool (sync operation)
            await asyncio.to_thread(self._init_writer_connection)

            return self._writer_conn

    def _init_writer_connection(self) -> None:
        """Sync writer initialization executed in thread pool."""
        db_path = Path(self._db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._writer_conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            timeout=30,
        )
        self._writer_conn.execute("PRAGMA journal_mode=WAL")
        self._writer_conn.execute("PRAGMA foreign_keys=ON")
        self._writer_conn.row_factory = sqlite3.Row

        self._create_table_sync(self._writer_conn)
        logger.info("SQLite writer connection initialized at %s", self._db_path)

    async def _get_reader_connection(self) -> sqlite3.Connection:
        """Get reader connection from pool (Phase 2).

        Uses semaphore to limit concurrent reads to pool size.

        Returns:
            Reader connection from pool.
        """
        async with self._lock:
            if not self._reader_pool:
                # Initialize reader pool
                await asyncio.to_thread(self._init_reader_pool)

            # Return connection from pool (or create new if pool empty)
            return (
                self._reader_pool.pop() if self._reader_pool else await self._create_reader_conn()
            )

    def _init_reader_pool(self) -> None:
        """Sync reader pool initialization executed in thread pool."""
        db_path = Path(self._db_path)
        for i in range(self._reader_pool_size):
            conn = sqlite3.connect(
                str(db_path),
                check_same_thread=False,
                timeout=30,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._reader_pool.append(conn)

        logger.info("SQLite reader pool initialized: size=%d", self._reader_pool_size)

    async def _create_reader_conn(self) -> sqlite3.Connection:
        """Create new reader connection if pool empty."""
        return await asyncio.to_thread(self._create_reader_conn_sync)

    def _create_reader_conn_sync(self) -> sqlite3.Connection:
        """Sync reader connection creation."""
        db_path = Path(self._db_path)
        conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _create_table_sync(self, conn: sqlite3.Connection) -> None:
        """Create key-value table if it does not exist (sync)."""
        conn.execute(
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_soothe_kv_namespace ON soothe_kv(namespace)")
        conn.commit()

    async def save(self, key: str, data: Any) -> None:
        """Persist data under the given key (async, IG-258 Phase 2).

        Args:
            key: Storage key.
            data: JSON-serialisable data.
        """
        conn = await self._ensure_writer_connection()
        serialized = json.dumps(data, ensure_ascii=False)

        # Execute sync SQLite operation in thread pool
        await asyncio.to_thread(
            self._save_sync,
            conn,
            self._namespace,
            key,
            serialized,
        )

    def _save_sync(
        self, conn: sqlite3.Connection, namespace: str, key: str, serialized: str
    ) -> None:
        """Sync save operation executed in thread pool."""
        conn.execute(
            """
            INSERT INTO soothe_kv (namespace, key, data, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(namespace, key) DO UPDATE
                SET data = excluded.data, updated_at = CURRENT_TIMESTAMP
            """,
            (namespace, key, serialized),
        )
        conn.commit()

    async def load(self, key: str) -> Any | None:
        """Load data for the given key (async, IG-258 Phase 2).

        Args:
            key: Storage key.

        Returns:
            The stored data, or None if not found.
        """
        # Use reader connection from pool
        async with self._pool_semaphore:  # Limit concurrent reads
            conn = await self._get_reader_connection()

            # Execute sync read in thread pool
            row_data = await asyncio.to_thread(
                self._load_sync,
                conn,
                self._namespace,
                key,
            )

            # Return connection to pool
            async with self._lock:
                self._reader_pool.append(conn)

            if row_data is None:
                return None
            return json.loads(row_data)

    def _load_sync(self, conn: sqlite3.Connection, namespace: str, key: str) -> str | None:
        """Sync load operation executed in thread pool."""
        row = conn.execute(
            "SELECT data FROM soothe_kv WHERE namespace = ? AND key = ?",
            (namespace, key),
        ).fetchone()
        if row is None:
            return None
        return row["data"]

    async def delete(self, key: str) -> None:
        """Delete data for the given key (async, IG-258 Phase 2).

        Args:
            key: Storage key.
        """
        conn = await self._ensure_writer_connection()

        # Execute sync delete in thread pool
        await asyncio.to_thread(
            self._delete_sync,
            conn,
            self._namespace,
            key,
        )

    def _delete_sync(self, conn: sqlite3.Connection, namespace: str, key: str) -> None:
        """Sync delete operation executed in thread pool."""
        conn.execute(
            "DELETE FROM soothe_kv WHERE namespace = ? AND key = ?",
            (namespace, key),
        )
        conn.commit()

    async def list_keys(self, namespace: str | None = None) -> list[str]:
        """List all keys in the given namespace (async, IG-258 Phase 2).

        Args:
            namespace: Namespace to list keys from. Defaults to store namespace.

        Returns:
            List of keys.
        """
        # Use reader connection from pool
        async with self._pool_semaphore:
            conn = await self._get_reader_connection()
            ns = namespace or self._namespace

            # Execute sync list in thread pool
            keys = await asyncio.to_thread(
                self._list_keys_sync,
                conn,
                ns,
            )

            # Return connection to pool
            async with self._lock:
                self._reader_pool.append(conn)

            return keys

    def _list_keys_sync(self, conn: sqlite3.Connection, namespace: str) -> list[str]:
        """Sync list operation executed in thread pool."""
        rows = conn.execute(
            "SELECT key FROM soothe_kv WHERE namespace = ?", (namespace,)
        ).fetchall()
        return [row["key"] for row in rows]

    async def close(self) -> None:
        """Commit pending changes and close all connections (async, Phase 2)."""
        async with self._lock:
            # Close writer connection
            if self._writer_conn is not None:
                await asyncio.to_thread(self._close_conn_sync, self._writer_conn)
                self._writer_conn = None

            # Close reader pool
            for conn in self._reader_pool:
                await asyncio.to_thread(self._close_conn_sync, conn)
            self._reader_pool.clear()

            logger.info("SQLite persist store closed")

    def _close_conn_sync(self, conn: sqlite3.Connection) -> None:
        """Sync connection close executed in thread pool."""
        with contextlib.suppress(Exception):
            conn.commit()
        conn.close()
