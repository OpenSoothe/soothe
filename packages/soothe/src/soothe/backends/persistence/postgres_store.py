"""PostgreSQL persistence backend using psycopg (async with connection pooling)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


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

    async def _reset_pool(self) -> None:
        """Close and clear the current pool after a fatal connection error."""
        async with self._init_lock:
            pool = self._pool
            self._pool = None
        if pool is not None:
            try:
                await pool.close()
            except Exception:
                logger.debug("[Store] Error closing stale PostgreSQL pool", exc_info=True)

    def _is_recoverable_connection_error(self, exc: Exception) -> bool:
        """Return True for transient PostgreSQL connection failures."""
        recoverable_classes: tuple[type[BaseException], ...] = ()
        try:
            import psycopg
            from psycopg import errors as pg_errors

            recoverable_classes = (
                psycopg.OperationalError,
                psycopg.InterfaceError,
                pg_errors.AdminShutdown,
                pg_errors.CrashShutdown,
                pg_errors.ConnectionFailure,
            )
        except Exception:
            recoverable_classes = ()

        if recoverable_classes and isinstance(exc, recoverable_classes):
            return True

        text = str(exc).lower()
        return any(
            needle in text
            for needle in (
                "admin shutdown",
                "terminating connection due to administrator command",
                "connection is closed",
                "connection not open",
                "server closed the connection unexpectedly",
                "connection failure",
            )
        )

    async def _run_with_pool_recovery(
        self,
        action: str,
        op: Callable[[Any], Awaitable[_T]],
    ) -> _T:
        """Run operation with one reconnect/retry on recoverable failures."""
        attempts = 2
        for attempt in range(1, attempts + 1):
            pool = await self._ensure_pool()
            try:
                return await op(pool)
            except Exception as exc:
                if attempt >= attempts or not self._is_recoverable_connection_error(exc):
                    raise
                logger.warning(
                    "[Store] PostgreSQL %s failed with recoverable connection error; "
                    "resetting pool and retrying once",
                    action,
                    exc_info=True,
                )
                await self._reset_pool()
        msg = f"Unreachable retry path while executing PostgreSQL store action: {action}"
        raise RuntimeError(msg)

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
                await self._initialize_schema(pool)
                logger.debug(
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

    async def _initialize_schema(self, pool: Any) -> None:
        """Apply soothe_metadata init script (async)."""
        from soothe.foundation.persistence.db_init import initialize_database

        await initialize_database(pool, "soothe_metadata")

    async def save(self, key: str, data: Any) -> None:
        """Persist data under the given key (upsert) (async).

        Args:
            key: Storage key
            data: JSON-serializable data
        """
        adapted_data = self._adapt_data(data)

        async def _save_with_pool(pool: Any) -> None:
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

        await self._run_with_pool_recovery("save", _save_with_pool)

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

        async def _load_with_pool(pool: Any) -> Any | None:
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
                if isinstance(data, (bytes, bytearray)):
                    # Defensive: JSONB should not return bytes; if it does, decode as JSON text.
                    try:
                        return json.loads(data.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as e:
                        logger.warning(
                            "Failed to decode PostgreSQL value for key %s: %s (value type: %s)",
                            key,
                            e,
                            type(data).__name__,
                        )
                        return None
                # JSONB values are already Python objects (including ``str`` scalars from JSON
                # strings). Do not ``json.loads`` plain ``str`` — it breaks values like ``second``.
                return data

        return await self._run_with_pool_recovery("load", _load_with_pool)

    async def delete(self, key: str) -> None:
        """Delete data for the given key (async).

        Args:
            key: Storage key
        """

        async def _delete_with_pool(pool: Any) -> None:
            async with pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM soothe_persistence WHERE namespace = %s AND key = %s",
                    (self._namespace, key),
                )
                await conn.commit()

        await self._run_with_pool_recovery("delete", _delete_with_pool)

    async def list_keys(self, namespace: str | None = None) -> list[str]:
        """List all keys in the namespace (async).

        Args:
            namespace: Optional namespace to list keys from. If None, uses default namespace.

        Returns:
            List of keys in the namespace.
        """
        ns = namespace or self._namespace

        async def _list_keys_with_pool(pool: Any) -> list[str]:
            async with pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    "SELECT key FROM soothe_persistence WHERE namespace = %s",
                    (ns,),
                )
                rows = await cur.fetchall()
                return [row[0] for row in rows]

        return await self._run_with_pool_recovery("list_keys", _list_keys_with_pool)

    async def close(self) -> None:
        """Close connection pool (async)."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("[Store] PostgreSQL closed (namespace=%s)", self._namespace)
