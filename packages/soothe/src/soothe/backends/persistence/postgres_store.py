"""PostgreSQL persistence backend using psycopg (async with connection pooling)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class PostgreSQLPersistStore:
    """AsyncPersistStore implementation using PostgreSQL with JSONB storage.

    Uses psycopg's AsyncConnectionPool for concurrent operations with connection pooling.

    Features:
    - Async connection pooling via psycopg_pool.AsyncConnectionPool
    - JSONB storage with namespace isolation
    - Automatic table creation with indexes
    - Async-safe lazy initialization with asyncio.Lock
    - Concurrent operation support (10 connections by default)

    IG-258 Phase 2: Async methods with connection pooling matching PostgreSQL checkpointer pattern.
    """

    def __init__(
        self,
        dsn: str,
        namespace: str = "default",
        pool_size: int = 10,
    ) -> None:
        """Initialize PostgreSQL store.

        Args:
            dsn: PostgreSQL connection string
            namespace: Namespace for key isolation (e.g., "context", "memory", "durability")
            pool_size: Connection pool size (default: 10, matching checkpointer)
        """
        self._dsn = dsn
        self._namespace = namespace
        self._pool_size = pool_size
        self._pool: Any = None
        self._init_lock = asyncio.Lock()

    async def _ensure_pool(self) -> Any:
        """Lazy pool initialization with automatic table creation (async).

        Returns:
            AsyncConnectionPool instance

        Raises:
            ImportError: If psycopg[pool] is not installed
            RuntimeError: If pool initialization fails
        """
        if self._pool is not None:
            return self._pool

        async with self._init_lock:
            if self._pool is not None:
                return self._pool

            try:
                from psycopg_pool import AsyncConnectionPool
            except ImportError as exc:
                msg = "psycopg[pool] is required for PostgreSQL persistence: pip install 'soothe[postgres]'"
                raise ImportError(msg) from exc

            pool = AsyncConnectionPool(
                conninfo=self._dsn,
                min_size=1,
                max_size=self._pool_size,
                open=False,
            )

            try:
                await pool.open()
                await self._create_table(pool)
                logger.info(
                    "[Store] PostgreSQL initialized (namespace=%s, pool=%d)",
                    self._namespace,
                    self._pool_size,
                )
            except Exception as exc:
                await pool.close()
                msg = f"Failed to initialize PostgreSQL connection pool: {exc}"
                raise RuntimeError(msg) from exc

            self._pool = pool
            return self._pool

    async def _create_table(self, pool: Any | None = None) -> None:
        """Create persistence table with indexes if not exists (async)."""
        pool = pool or await self._ensure_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS soothe_persistence (
                    key TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    data JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (namespace, key)
                )
            """
            )
            await cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_persistence_updated
                ON soothe_persistence(updated_at)
            """
            )
            await conn.commit()

    async def save(self, key: str, data: Any) -> None:
        """Persist data under the given key (upsert) (async).

        Args:
            key: Storage key
            data: JSON-serializable data
        """
        pool = await self._ensure_pool()
        adapted_data = self._adapt_data(data)
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO soothe_persistence (key, namespace, data, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (namespace, key)
                DO UPDATE SET data = EXCLUDED.data, updated_at = CURRENT_TIMESTAMP
                """,
                (key, self._namespace, adapted_data),
            )
            await conn.commit()

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

    async def load(self, key: str) -> Any | None:
        """Load data for the given key (async).

        Args:
            key: Storage key

        Returns:
            The stored data, or None if not found
        """
        pool = await self._ensure_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT data FROM soothe_persistence WHERE namespace = %s AND key = %s",
                (self._namespace, key),
            )
            row = await cur.fetchone()
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

    async def delete(self, key: str) -> None:
        """Delete data for the given key (async).

        Args:
            key: Storage key
        """
        pool = await self._ensure_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM soothe_persistence WHERE namespace = %s AND key = %s",
                (self._namespace, key),
            )
            await conn.commit()

    async def list_keys(self, namespace: str | None = None) -> list[str]:
        """List all keys in the namespace (async).

        Args:
            namespace: Optional namespace to list keys from. If None, uses default namespace.

        Returns:
            List of keys in the namespace.
        """
        pool = await self._ensure_pool()
        ns = namespace or self._namespace
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT key FROM soothe_persistence WHERE namespace = %s",
                (ns,),
            )
            rows = await cur.fetchall()
            return [row[0] for row in rows]

    async def close(self) -> None:
        """Close connection pool (async)."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("[Store] PostgreSQL closed (namespace=%s)", self._namespace)
