"""PostgreSQL persistence backend using psycopg."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class PostgreSQLPersistStore:
    """PersistStore implementation using PostgreSQL with JSONB storage.

    Features:
    - Async connection pooling via psycopg_pool.AsyncConnectionPool
    - JSONB storage with namespace isolation
    - Automatic table creation with indexes
    - Graceful connection error handling
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
        self._pool: Any = None  # AsyncConnectionPool
        self._loop: asyncio.AbstractEventLoop | None = None

    async def _ensure_pool(self) -> Any:
        """Lazy pool initialization with automatic table creation.

        Returns:
            AsyncConnectionPool instance

        Raises:
            ImportError: If psycopg[pool] is not installed
            RuntimeError: If pool initialization fails
        """
        if self._pool is not None:
            return self._pool

        try:
            from psycopg_pool import AsyncConnectionPool
        except ImportError as exc:
            msg = "psycopg[pool] is required for PostgreSQL persistence: pip install 'soothe[postgres]'"
            raise ImportError(msg) from exc

        # Store event loop for async-to-sync wrapper
        self._loop = asyncio.get_event_loop()

        # Create connection pool
        self._pool = AsyncConnectionPool(
            conninfo=self._dsn,
            min_size=1,
            max_size=self._pool_size,
            open=False,  # Don't open immediately
        )

        # Open pool and create table
        try:
            await self._pool.open()
            await self._create_table()
            logger.info(
                "PostgreSQL persist store initialized (namespace=%s, pool_size=%d)",
                self._namespace,
                self._pool_size,
            )
        except Exception as exc:
            await self._pool.close()
            self._pool = None
            msg = f"Failed to initialize PostgreSQL connection pool: {exc}"
            raise RuntimeError(msg) from exc

        return self._pool

    async def _create_table(self) -> None:
        """Create persistence table with indexes if not exists."""
        pool = await self._ensure_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("""
                    CREATE TABLE IF NOT EXISTS soothe_persistence (
                        key TEXT NOT NULL,
                        namespace TEXT NOT NULL,
                        data JSONB NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (namespace, key)
                    )
                """)
            await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_persistence_updated
                    ON soothe_persistence(updated_at)
                """)
            await conn.commit()

    def save(self, key: str, data: Any) -> None:
        """Persist data under the given key (upsert).

        Args:
            key: Storage key
            data: JSON-serializable data
        """
        # Run async operation in event loop
        asyncio.run_coroutine_threadsafe(self._async_save(key, data), self._loop or asyncio.get_event_loop()).result()

    async def _async_save(self, key: str, data: Any) -> None:
        """Async implementation of save."""
        pool = await self._ensure_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    INSERT INTO soothe_persistence (key, namespace, data, updated_at)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (namespace, key)
                    DO UPDATE SET data = EXCLUDED.data, updated_at = CURRENT_TIMESTAMP
                    """,
                (key, self._namespace, json.dumps(data, default=str)),
            )
            await conn.commit()

    def load(self, key: str) -> Any | None:
        """Load data for the given key.

        Args:
            key: Storage key

        Returns:
            The stored data, or None if not found
        """
        # Run async operation in event loop
        return asyncio.run_coroutine_threadsafe(self._async_load(key), self._loop or asyncio.get_event_loop()).result()

    async def _async_load(self, key: str) -> Any | None:
        """Async implementation of load."""
        pool = await self._ensure_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT data FROM soothe_persistence WHERE namespace = %s AND key = %s",
                (self._namespace, key),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            try:
                return json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                logger.warning("Failed to decode PostgreSQL value for key %s", key)
                return None

    def delete(self, key: str) -> None:
        """Delete data for the given key.

        Args:
            key: Storage key
        """
        # Run async operation in event loop
        asyncio.run_coroutine_threadsafe(self._async_delete(key), self._loop or asyncio.get_event_loop()).result()

    async def _async_delete(self, key: str) -> None:
        """Async implementation of delete."""
        pool = await self._ensure_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM soothe_persistence WHERE namespace = %s AND key = %s",
                (self._namespace, key),
            )
            await conn.commit()

    def close(self) -> None:
        """Close connection pool."""
        if self._pool is not None:
            # Run async close in event loop
            if self._loop and not self._loop.is_closed():
                asyncio.run_coroutine_threadsafe(self._pool.close(), self._loop).result(timeout=5.0)
            self._pool = None
            logger.info("PostgreSQL persist store closed (namespace=%s)", self._namespace)
