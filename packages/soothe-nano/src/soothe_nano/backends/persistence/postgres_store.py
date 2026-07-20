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
        *,
        shared_pool: Any | None = None,
        pool_timing: dict[str, Any] | None = None,
    ) -> None:
        """Initialize PostgreSQL store.

        Args:
            dsn: PostgreSQL connection string
            namespace: Namespace for key isolation (e.g., "context", "memory", "durability")
            pool_size: Connection pool size (default: 10). Use 0 with ``shared_pool`` for
                process-wide singleton mode.
            shared_pool: Externally managed ``AsyncConnectionPool`` (daemon singleton).
            pool_timing: Optional psycopg pool options when creating an owned pool.
        """
        self._dsn = dsn
        self._namespace = namespace
        self._pool_size = pool_size
        self._pool_timing = pool_timing
        self._shared_pool = shared_pool
        self._owns_pool = pool_size != 0 and shared_pool is None
        if shared_pool is not None:
            self._pool = shared_pool
        else:
            self._pool: Any = None
        self._init_lock = asyncio.Lock()
        self._schema_initialized = shared_pool is not None

    @property
    def _uses_shared_pool(self) -> bool:
        """True when this store borrows an externally managed pool."""
        return not self._owns_pool and self._shared_pool is not None

    def _bind_shared_pool(self) -> Any | None:
        """Reattach the borrowed pool reference when local cache was cleared."""
        if self._shared_pool is None:
            return None
        self._pool = self._shared_pool
        return self._pool

    def _rebind_shared_pool_from_registry(self) -> Any | None:
        """Prefer registry-opened metadata pool over a stale local singleton."""
        if self._shared_pool is None:
            return None
        try:
            from soothe_nano.persistence.postgres_pool_registry import PostgresPoolRegistry
            from soothe_nano.persistence.shared_metadata_pool import SharedMetadataPool

            registry = PostgresPoolRegistry.try_get_instance()
            if registry is None:
                return self._bind_shared_pool()
            reg_pool = registry.try_get_pool("metadata")
            if reg_pool is None:
                return self._bind_shared_pool()
            self._shared_pool = reg_pool
            SharedMetadataPool._register_pool(reg_pool)
            return self._bind_shared_pool()
        except Exception:
            logger.debug("Failed to rebind metadata pool from registry", exc_info=True)
            return self._bind_shared_pool()

    async def _prepare_pool_for_use(self, pool: Any) -> Any:
        """Ensure *pool* is open before returning it to callers."""
        from soothe_nano.persistence.postgres_pool_lifecycle import ensure_async_pool_open

        await ensure_async_pool_open(pool)
        return pool

    async def _reset_pool(self) -> None:
        """Reset pool state after a recoverable connection error.

        Owned pools are closed and cleared for lazy re-open. Shared/registry pools
        must never be closed from this wrapper — rebind and ensure open instead.
        """
        async with self._init_lock:
            if self._uses_shared_pool:
                pool = self._rebind_shared_pool_from_registry()
                if pool is not None:
                    await self._prepare_pool_for_use(pool)
                return
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
            from psycopg_pool import PoolClosed

            recoverable_classes = (
                psycopg.OperationalError,
                psycopg.InterfaceError,
                pg_errors.AdminShutdown,
                pg_errors.CrashShutdown,
                pg_errors.ConnectionFailure,
                PoolClosed,
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
                "not open yet",
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
            if not self._schema_initialized:
                await self._initialize_schema(self._pool)
                self._schema_initialized = True
            await self._prepare_pool_for_use(self._pool)
            return self._pool

        if self._pool_size == 0:
            if self._bind_shared_pool() is not None:
                if not self._schema_initialized:
                    await self._initialize_schema(self._pool)
                    self._schema_initialized = True
                await self._prepare_pool_for_use(self._pool)
                return self._pool
            msg = "PostgreSQL persist store in shared pool mode but pool not set"
            raise RuntimeError(msg)

        async with self._init_lock:
            if self._pool is not None:
                return self._pool

            try:
                from psycopg_pool import AsyncConnectionPool
            except ImportError as exc:
                msg = (
                    "psycopg[pool] is required for PostgreSQL persistence. "
                    "Install with: pip install -U soothe"
                )
                raise ImportError(msg) from exc

            from soothe_nano.persistence.postgres_pool_lifecycle import apply_row_factory

            pool_kwargs: dict[str, Any] = {
                "conninfo": self._dsn,
                "max_size": self._pool_size,
                "open": False,
            }
            if self._pool_timing:
                pool_kwargs.update(self._pool_timing)
            else:
                pool_kwargs["min_size"] = min(1, self._pool_size)
            pool = AsyncConnectionPool(**apply_row_factory(pool_kwargs))

            try:
                await pool.open()
                await self._initialize_schema(pool)
                self._schema_initialized = True
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
            await self._prepare_pool_for_use(pool)
            return self._pool

    async def close(self) -> None:
        """Close the owned connection pool (skip shared singleton pools)."""
        if not self._owns_pool or self._pool is None:
            return
        try:
            if not getattr(self._pool, "closed", False):
                await self._pool.close()
        except Exception:
            logger.debug("[Store] Failed to close PostgreSQL pool", exc_info=True)
        finally:
            self._pool = None

    async def _initialize_schema(self, pool: Any) -> None:
        """Apply soothe_metadata init script (async)."""
        from soothe_nano.persistence.db_init import initialize_database

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
                data = row["data"]
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
                return [row["key"] for row in rows]

        return await self._run_with_pool_recovery("list_keys", _list_keys_with_pool)
