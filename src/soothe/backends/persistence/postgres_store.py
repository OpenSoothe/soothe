"""PostgreSQL persistence backend using psycopg (synchronous)."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class PostgreSQLPersistStore:
    """PersistStore implementation using PostgreSQL with JSONB storage.

    Uses psycopg's synchronous ConnectionPool so that ``save``/``load``/``delete``
    work correctly whether called from an asyncio event-loop thread or a plain
    thread -- avoiding the deadlock that occurs when ``asyncio.run_coroutine_threadsafe().result()``
    is invoked from within the running loop.

    Features:
    - Synchronous connection pooling via psycopg_pool.ConnectionPool
    - JSONB storage with namespace isolation
    - Automatic table creation with indexes
    - Thread-safe lazy initialization
    """

    def __init__(
        self,
        dsn: str,
        namespace: str = "default",
        pool_size: int = 5,
    ) -> None:
        """Initialize PostgreSQL store.

        Args:
            dsn: PostgreSQL connection string
            namespace: Namespace for key isolation (e.g., "context", "memory", "durability")
            pool_size: Connection pool size
        """
        self._dsn = dsn
        self._namespace = namespace
        self._pool_size = pool_size
        self._pool: Any = None
        self._init_lock = threading.Lock()

    def _ensure_pool(self) -> Any:
        """Lazy pool initialization with automatic table creation.

        Returns:
            ConnectionPool instance

        Raises:
            ImportError: If psycopg[pool] is not installed
            RuntimeError: If pool initialization fails
        """
        if self._pool is not None:
            return self._pool

        with self._init_lock:
            if self._pool is not None:
                return self._pool

            try:
                from psycopg_pool import ConnectionPool
            except ImportError as exc:
                msg = "psycopg[pool] is required for PostgreSQL persistence: pip install 'soothe[postgres]'"
                raise ImportError(msg) from exc

            pool = ConnectionPool(
                conninfo=self._dsn,
                min_size=1,
                max_size=self._pool_size,
                open=False,
            )

            try:
                pool.open()
                self._create_table(pool)
                logger.info(
                    "PostgreSQL persist store initialized (namespace=%s, pool_size=%d)",
                    self._namespace,
                    self._pool_size,
                )
            except Exception as exc:
                pool.close()
                msg = f"Failed to initialize PostgreSQL connection pool: {exc}"
                raise RuntimeError(msg) from exc

            self._pool = pool
            return self._pool

    def _create_table(self, pool: Any | None = None) -> None:
        """Create persistence table with indexes if not exists."""
        pool = pool or self._ensure_pool()
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS soothe_persistence (
                    key TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    data JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (namespace, key)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_persistence_updated
                ON soothe_persistence(updated_at)
            """)
            conn.commit()

    def save(self, key: str, data: Any) -> None:
        """Persist data under the given key (upsert).

        Args:
            key: Storage key
            data: JSON-serializable data
        """
        pool = self._ensure_pool()
        adapted_data = self._adapt_data(data)
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO soothe_persistence (key, namespace, data, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (namespace, key)
                DO UPDATE SET data = EXCLUDED.data, updated_at = CURRENT_TIMESTAMP
                """,
                (key, self._namespace, adapted_data),
            )
            conn.commit()

    def _adapt_data(self, data: Any) -> Any:
        """Adapt data for PostgreSQL JSONB storage.

        psycopg3 handles JSONB automatically, but we use json.dumps with
        a custom default handler for non-serializable types.

        Args:
            data: Python object to adapt

        Returns:
            JSON-serializable object or Json wrapper
        """
        # Use Json adapter for proper JSONB handling
        try:
            from psycopg.types.json import Json

            return Json(data)
        except ImportError:
            # Fallback for older psycopg versions
            return json.dumps(data, default=str)

    def load(self, key: str) -> Any | None:
        """Load data for the given key.

        Args:
            key: Storage key

        Returns:
            The stored data, or None if not found
        """
        pool = self._ensure_pool()
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT data FROM soothe_persistence WHERE namespace = %s AND key = %s",
                (self._namespace, key),
            )
            row = cur.fetchone()
            if row is None:
                return None
            # PostgreSQL JSONB column returns already-parsed Python objects (list/dict)
            # not JSON strings, so we can return directly
            data = row[0]
            if isinstance(data, (str, bytes, bytearray)):
                # Fallback for JSON strings (shouldn't happen with JSONB but be defensive)
                try:
                    return json.loads(data)
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(
                        "Failed to decode PostgreSQL value for key %s: %s (value type: %s)",
                        key,
                        e,
                        type(data).__name__,
                    )
                    return None
            # Data is already a Python object (list/dict/None/etc.)
            return data

    def delete(self, key: str) -> None:
        """Delete data for the given key.

        Args:
            key: Storage key
        """
        pool = self._ensure_pool()
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM soothe_persistence WHERE namespace = %s AND key = %s",
                (self._namespace, key),
            )
            conn.commit()

    def close(self) -> None:
        """Close connection pool."""
        if self._pool is not None:
            self._pool.close()
            self._pool = None
            logger.info("PostgreSQL persist store closed (namespace=%s)", self._namespace)
