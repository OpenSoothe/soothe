"""SQLite-backed workspace state store.

Stores file, blob, checkpoint, and artifact state in a workspace-local
SQLite database at `.workspace/state.db`.  All operations are async
(via `asyncio.to_thread`) to match the `WorkspaceStateStore` protocol.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path     TEXT PRIMARY KEY,
    size     INTEGER,
    mtime    REAL,
    inode    INTEGER,
    sha256   TEXT,
    status   TEXT NOT NULL DEFAULT 'clean'
);

CREATE TABLE IF NOT EXISTS blobs (
    sha256     TEXT PRIMARY KEY,
    size       INTEGER,
    local_path TEXT,
    last_used  REAL
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id             TEXT PRIMARY KEY,
    timestamp      REAL NOT NULL,
    manifest_hash  TEXT,
    status         TEXT NOT NULL DEFAULT 'pending_upload'
);

CREATE TABLE IF NOT EXISTS artifacts (
    path          TEXT PRIMARY KEY,
    sha256        TEXT,
    published_uri TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
);

CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_checkpoints_status ON checkpoints(status);
"""


class SqliteWorkspaceStateStore:
    """SQLite implementation of `WorkspaceStateStore`.

    Args:
        db_path: Path to the SQLite database file.
        run_id: Unique run identifier (for logging and future multi-run support).
    """

    def __init__(self, *, db_path: Path, run_id: str) -> None:
        self._db_path = db_path
        self._run_id = run_id
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        logger.debug("SqliteWorkspaceStateStore initialized: db=%s, run=%s", db_path, run_id)

    def _execute(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> list[dict[str, Any]]:
        """Execute a query and return rows as dicts."""
        cursor = self._conn.execute(sql, params)
        rows = cursor.fetchall()
        self._conn.commit()
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
            self._execute,
            """INSERT INTO files (path, size, mtime, inode, sha256, status)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
                   size=excluded.size,
                   mtime=excluded.mtime,
                   inode=excluded.inode,
                   sha256=excluded.sha256,
                   status=excluded.status""",
            (path, size, mtime, inode, sha256, status),
        )

    async def get_file(self, path: str) -> dict[str, Any] | None:
        """Get a file record by path."""
        rows = await asyncio.to_thread(
            self._execute,
            "SELECT * FROM files WHERE path = ?",
            (path,),
        )
        return rows[0] if rows else None

    async def list_dirty_files(self) -> list[dict[str, Any]]:
        """Return all files with status='dirty'."""
        return await asyncio.to_thread(
            self._execute,
            "SELECT * FROM files WHERE status = 'dirty'",
        )

    async def clear_dirty(self) -> None:
        """Mark all dirty files as clean."""
        await asyncio.to_thread(
            self._execute,
            "UPDATE files SET status = 'clean' WHERE status = 'dirty'",
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
            self._execute,
            """INSERT INTO blobs (sha256, size, local_path, last_used)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(sha256) DO UPDATE SET
                   size=excluded.size,
                   local_path=excluded.local_path,
                   last_used=excluded.last_used""",
            (sha256, size, local_path, last_used),
        )

    async def get_blob(self, sha256: str) -> dict[str, Any] | None:
        """Get a blob cache entry by hash."""
        rows = await asyncio.to_thread(
            self._execute,
            "SELECT * FROM blobs WHERE sha256 = ?",
            (sha256,),
        )
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # Checkpoint references
    # ------------------------------------------------------------------

    async def insert_checkpoint(
        self,
        checkpoint_id: str,
        *,
        manifest_hash: str,
        status: str,
    ) -> None:
        """Insert a checkpoint reference."""
        await asyncio.to_thread(
            self._execute,
            """INSERT INTO checkpoints (id, timestamp, manifest_hash, status)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   timestamp=excluded.timestamp,
                   manifest_hash=excluded.manifest_hash,
                   status=excluded.status""",
            (checkpoint_id, time.time(), manifest_hash, status),
        )

    async def list_pending_checkpoints(self) -> list[dict[str, Any]]:
        """Return all checkpoints with status='pending_upload' in FIFO order."""
        return await asyncio.to_thread(
            self._execute,
            "SELECT * FROM checkpoints WHERE status = 'pending_upload' ORDER BY timestamp ASC",
        )

    async def update_checkpoint_status(
        self,
        checkpoint_id: str,
        status: str,
    ) -> None:
        """Update a checkpoint's status."""
        await asyncio.to_thread(
            self._execute,
            "UPDATE checkpoints SET status = ? WHERE id = ?",
            (status, checkpoint_id),
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
            self._execute,
            """INSERT INTO artifacts (path, sha256, published_uri, status)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
                   sha256=excluded.sha256,
                   published_uri=excluded.published_uri,
                   status=excluded.status""",
            (path, sha256, published_uri, status),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the database connection."""
        await asyncio.to_thread(self._conn.close)

    async def cleanup(self) -> None:
        """Remove all state for this run."""

        def _cleanup() -> None:
            self._conn.executescript(
                "DELETE FROM files;"
                " DELETE FROM blobs;"
                " DELETE FROM checkpoints;"
                " DELETE FROM artifacts;"
            )
            self._conn.commit()

        await asyncio.to_thread(_cleanup)
        logger.debug("State store cleaned up for run %s", self._run_id)
