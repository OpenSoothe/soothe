"""PostgreSQL-backed workspace state store.

Stores file, blob, checkpoint, and artifact state in the shared
``soothe_metadata`` database, scoped by ``loop_id`` so that multiple
loops coexist in the same database.  All operations are async
(via ``asyncio.to_thread``) to match the ``WorkspaceStateStore`` protocol.

Uses a workspace-sync-specific sync ``ConnectionPool`` (not the shared
``SharedMetadataPool``), mirroring ``PostgresCronJobStore`` and
``PostgresDisplayCardStore`` — each store owns its own lazy pool.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ws_files (
    loop_id   TEXT NOT NULL,
    path      TEXT NOT NULL,
    size      INTEGER,
    mtime     REAL,
    inode     INTEGER,
    sha256    TEXT,
    status    TEXT NOT NULL DEFAULT 'clean',
    PRIMARY KEY (loop_id, path)
);
CREATE INDEX IF NOT EXISTS idx_ws_files_status ON ws_files(loop_id, status);

CREATE TABLE IF NOT EXISTS ws_blobs (
    loop_id     TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    size        INTEGER,
    local_path  TEXT,
    last_used   REAL,
    PRIMARY KEY (loop_id, sha256)
);

CREATE TABLE IF NOT EXISTS ws_checkpoints (
    loop_id        TEXT NOT NULL,
    id             TEXT NOT NULL,
    timestamp      REAL NOT NULL,
    manifest_hash  TEXT,
    status         TEXT NOT NULL DEFAULT 'pending_upload',
    PRIMARY KEY (loop_id, id)
);
CREATE INDEX IF NOT EXISTS idx_ws_checkpoints_status ON ws_checkpoints(loop_id, status);

CREATE TABLE IF NOT EXISTS ws_artifacts (
    loop_id        TEXT NOT NULL,
    path           TEXT NOT NULL,
    sha256         TEXT,
    published_uri  TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (loop_id, path)
);
"""


class PostgresWorkspaceStateStore:
    """PostgreSQL implementation of ``WorkspaceStateStore``.

    Uses a per-store sync ``ConnectionPool`` with ``asyncio.to_thread``
    wrappers, mirroring ``PostgresCronJobStore``.  All tables are scoped
    by ``loop_id`` for multi-tenant coexistence in ``soothe_metadata``.

    Args:
        dsn: Full PostgreSQL DSN (including database name).
        loop_id: Unique loop identifier used as the tenant key.
    """

    def __init__(self, *, dsn: str, loop_id: str) -> None:
        self._dsn = dsn
        self._loop_id = loop_id
        self._pool: Any | None = None
        self._init_lock = asyncio.Lock()
        self._schema_ready = False
        logger.debug("PostgresWorkspaceStateStore initialized: loop=%s, dsn_db=metadata", loop_id)

    @property
    def dsn(self) -> str:
        """Full PostgreSQL DSN used by this store."""
        return self._dsn

    @property
    def loop_id(self) -> str:
        """Loop identifier used as the tenant scoping key."""
        return self._loop_id

    # ------------------------------------------------------------------
    # Pool lifecycle
    # ------------------------------------------------------------------

    async def _ensure_pool(self) -> Any:
        """Lazily open the connection pool and initialize schema."""
        if self._pool is not None:
            return self._pool
        async with self._init_lock:
            if self._pool is not None:
                return self._pool
            await asyncio.to_thread(self._open_pool_sync)
            return self._pool

    def _open_pool_sync(self) -> None:
        """Open the sync ``ConnectionPool`` and create tables."""
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            conninfo=self._dsn,
            min_size=1,
            max_size=4,
            open=True,
            kwargs={"autocommit": False, "row_factory": dict_row},
        )
        with pool.connection() as conn:
            with conn.cursor() as cur:
                for statement in (s.strip() for s in _SCHEMA.split(";") if s.strip()):
                    cur.execute(statement)
            conn.commit()
        self._pool = pool
        self._schema_ready = True

    def _execute_sync(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> list[dict[str, Any]]:
        """Execute a query and return rows as dicts."""
        assert self._pool is not None
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            conn.commit()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # File tracking
    # ------------------------------------------------------------------

    async def upsert_file(
        self,
        path: str,
        *,
        size: int,
        mtime: float,
        inode: int | None,
        sha256: str | None,
        status: str,
    ) -> None:
        """Insert or update a file record."""
        await asyncio.to_thread(
            self._execute_sync,
            """
            INSERT INTO ws_files (loop_id, path, size, mtime, inode, sha256, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (loop_id, path) DO UPDATE SET
                size = EXCLUDED.size,
                mtime = EXCLUDED.mtime,
                inode = EXCLUDED.inode,
                sha256 = EXCLUDED.sha256,
                status = EXCLUDED.status
            """,
            (self._loop_id, path, size, mtime, inode, sha256, status),
        )

    async def get_file(self, path: str) -> dict[str, Any] | None:
        """Get a file record by path."""
        rows = await asyncio.to_thread(
            self._execute_sync,
            "SELECT path, size, mtime, inode, sha256, status FROM ws_files "
            "WHERE loop_id = %s AND path = %s",
            (self._loop_id, path),
        )
        return rows[0] if rows else None

    async def list_dirty_files(self) -> list[dict[str, Any]]:
        """Return all files with status='dirty'."""
        return await asyncio.to_thread(
            self._execute_sync,
            "SELECT path, size, mtime, inode, sha256, status FROM ws_files "
            "WHERE loop_id = %s AND status = 'dirty'",
            (self._loop_id,),
        )

    async def clear_dirty(self) -> None:
        """Mark all dirty files as clean."""
        await asyncio.to_thread(
            self._execute_sync,
            "UPDATE ws_files SET status = 'clean' WHERE loop_id = %s AND status = 'dirty'",
            (self._loop_id,),
        )

    # ------------------------------------------------------------------
    # Blob cache index
    # ------------------------------------------------------------------

    async def upsert_blob(
        self,
        sha256: str,
        *,
        size: int,
        local_path: str,
        last_used: float,
    ) -> None:
        """Insert or update a blob cache entry."""
        await asyncio.to_thread(
            self._execute_sync,
            """
            INSERT INTO ws_blobs (loop_id, sha256, size, local_path, last_used)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (loop_id, sha256) DO UPDATE SET
                size = EXCLUDED.size,
                local_path = EXCLUDED.local_path,
                last_used = EXCLUDED.last_used
            """,
            (self._loop_id, sha256, size, local_path, last_used),
        )

    async def get_blob(self, sha256: str) -> dict[str, Any] | None:
        """Get a blob cache entry by hash."""
        rows = await asyncio.to_thread(
            self._execute_sync,
            "SELECT sha256, size, local_path, last_used FROM ws_blobs "
            "WHERE loop_id = %s AND sha256 = %s",
            (self._loop_id, sha256),
        )
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # Checkpoint references
    # ------------------------------------------------------------------

    async def insert_checkpoint(
        self,
        checkpoint_id: str,
        *,
        manifest_hash: str | None,
        status: str,
    ) -> None:
        """Insert a checkpoint reference."""
        await asyncio.to_thread(
            self._execute_sync,
            """
            INSERT INTO ws_checkpoints (loop_id, id, timestamp, manifest_hash, status)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (loop_id, id) DO UPDATE SET
                timestamp = EXCLUDED.timestamp,
                manifest_hash = EXCLUDED.manifest_hash,
                status = EXCLUDED.status
            """,
            (self._loop_id, checkpoint_id, time.time(), manifest_hash, status),
        )

    async def list_pending_checkpoints(self) -> list[dict[str, Any]]:
        """Return all checkpoints with status='pending_upload' in FIFO order."""
        return await asyncio.to_thread(
            self._execute_sync,
            "SELECT id, timestamp, manifest_hash, status FROM ws_checkpoints "
            "WHERE loop_id = %s AND status = 'pending_upload' "
            "ORDER BY timestamp ASC",
            (self._loop_id,),
        )

    async def update_checkpoint_status(
        self,
        checkpoint_id: str,
        status: str,
    ) -> None:
        """Update a checkpoint's status."""
        await asyncio.to_thread(
            self._execute_sync,
            "UPDATE ws_checkpoints SET status = %s WHERE loop_id = %s AND id = %s",
            (status, self._loop_id, checkpoint_id),
        )

    # ------------------------------------------------------------------
    # Artifact tracking
    # ------------------------------------------------------------------

    async def upsert_artifact(
        self,
        path: str,
        *,
        sha256: str,
        published_uri: str | None,
        status: str,
    ) -> None:
        """Insert or update an artifact record."""
        await asyncio.to_thread(
            self._execute_sync,
            """
            INSERT INTO ws_artifacts (loop_id, path, sha256, published_uri, status)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (loop_id, path) DO UPDATE SET
                sha256 = EXCLUDED.sha256,
                published_uri = EXCLUDED.published_uri,
                status = EXCLUDED.status
            """,
            (self._loop_id, path, sha256, published_uri, status),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the connection pool."""
        await asyncio.to_thread(self._close_pool_sync)

    def _close_pool_sync(self) -> None:
        pool = self._pool
        self._pool = None
        self._schema_ready = False
        if pool is not None:
            try:
                pool.close()
            except Exception:
                logger.debug("Error closing PostgreSQL workspace state pool", exc_info=True)

    async def cleanup(self) -> None:
        """Remove all state for this loop."""
        await asyncio.to_thread(self._cleanup_sync)
        logger.debug("State store cleaned up for loop %s", self._loop_id)

    def _cleanup_sync(self) -> None:
        """Delete all rows for this loop_id across all four tables."""
        assert self._pool is not None
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ws_files WHERE loop_id = %s", (self._loop_id,))
                cur.execute("DELETE FROM ws_blobs WHERE loop_id = %s", (self._loop_id,))
                cur.execute("DELETE FROM ws_checkpoints WHERE loop_id = %s", (self._loop_id,))
                cur.execute("DELETE FROM ws_artifacts WHERE loop_id = %s", (self._loop_id,))
            conn.commit()


__all__ = ["PostgresWorkspaceStateStore"]
