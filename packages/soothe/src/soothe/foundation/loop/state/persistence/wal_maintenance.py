"""SQLite WAL checkpoint helpers for shared runtime databases."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def checkpoint_sqlite_db(db_path: Path, *, truncate: bool = True) -> None:
    """Run ``PRAGMA wal_checkpoint`` on a SQLite file if it exists.

    Args:
        db_path: Path to the SQLite database file.
        truncate: When True, use TRUNCATE mode to reset WAL size.
    """
    path = Path(db_path).expanduser()
    if not path.is_file():
        return
    mode = "TRUNCATE" if truncate else "PASSIVE"
    try:
        with sqlite3.connect(str(path), timeout=30) as conn:
            conn.execute(f"PRAGMA wal_checkpoint({mode})")
    except sqlite3.Error:
        logger.warning("WAL checkpoint failed for %s", path, exc_info=True)


def checkpoint_runtime_databases(*db_paths: Path) -> None:
    """Checkpoint each existing runtime database path."""
    for db_path in db_paths:
        checkpoint_sqlite_db(db_path)


__all__ = ["checkpoint_runtime_databases", "checkpoint_sqlite_db"]
