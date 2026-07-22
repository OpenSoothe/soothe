"""SQLite persistence backend for the Context Engine (RFC-624 Phase 4).

Stores CE DAG and ledger in a single SQLite database keyed by ``loop_id``.
Uses WAL mode and ``asyncio.to_thread`` for non-blocking I/O, following
the same conventions as ``SQLitePersistenceBackend`` in the StrangeLoop
state module.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from soothe.context.models import GoalStepDAG, GoalStepDAGSnapshot

logger = logging.getLogger(__name__)


class SqliteContextPersistence:
    """SQLite-backed persistence for ContextEngine.

    Two tables in a single DB file:
    - ``ce_dag`` — serialized GoalStepDAG (one row per loop_id)
    - ``ce_ledger`` — serialized message ledger (one row per loop_id)

    Args:
        loop_id: Loop identifier used as primary key.
        db_path: Path to the SQLite database file.
    """

    def __init__(self, loop_id: str, db_path: Path) -> None:
        self._loop_id = loop_id
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # ── Internal helpers ────────────────────────────────────────────

    def _ensure_connection(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is not None:
                return self._conn
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), timeout=30, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=60000")
            conn.row_factory = sqlite3.Row
            self._ensure_schema(conn)
            self._conn = conn
            return conn

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ce_dag (
                loop_id TEXT PRIMARY KEY,
                dag_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ce_ledger (
                loop_id TEXT PRIMARY KEY,
                ledger_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()

    def _close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    async def close(self) -> None:
        """Close the database connection."""
        import asyncio

        try:
            await asyncio.to_thread(self._close)
        except Exception:
            logger.warning("[CE] Failed to close SQLite connection", exc_info=True)

    # ── Public API ──────────────────────────────────────────────────

    async def save_dag(self, dag: GoalStepDAG) -> None:
        snapshot = dag.snapshot()
        data = snapshot.model_dump(mode="json")
        json_str = json.dumps(data, default=str)

        def _save() -> None:
            conn = self._ensure_connection()
            from datetime import UTC, datetime

            now = datetime.now(UTC).isoformat()
            conn.execute(
                """
                INSERT INTO ce_dag (loop_id, dag_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(loop_id) DO UPDATE SET
                    dag_json = excluded.dag_json,
                    updated_at = excluded.updated_at
                """,
                (self._loop_id, json_str, now),
            )
            conn.commit()

        import asyncio

        try:
            await asyncio.to_thread(_save)
        except Exception:
            logger.warning("[CE] Failed to save DAG to SQLite", exc_info=True)

    async def load_dag(self) -> GoalStepDAG | None:
        def _load() -> str | None:
            conn = self._ensure_connection()
            row = conn.execute(
                "SELECT dag_json FROM ce_dag WHERE loop_id = ?",
                (self._loop_id,),
            ).fetchone()
            return row["dag_json"] if row else None

        import asyncio

        try:
            json_str = await asyncio.to_thread(_load)
        except Exception:
            logger.warning("[CE] Failed to load DAG from SQLite", exc_info=True)
            return None

        if json_str is None:
            return None

        try:
            data = json.loads(json_str)
            snapshot = GoalStepDAGSnapshot.model_validate(data)
            dag = GoalStepDAG()
            dag.restore_from_snapshot(snapshot)
            return dag
        except Exception:
            logger.warning("[CE] Failed to parse DAG snapshot", exc_info=True)
            return None

    async def save_ledger(self, messages: list[dict[str, Any]]) -> None:
        json_str = json.dumps(messages, default=str)

        def _save() -> None:
            conn = self._ensure_connection()
            from datetime import UTC, datetime

            now = datetime.now(UTC).isoformat()
            conn.execute(
                """
                INSERT INTO ce_ledger (loop_id, ledger_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(loop_id) DO UPDATE SET
                    ledger_json = excluded.ledger_json,
                    updated_at = excluded.updated_at
                """,
                (self._loop_id, json_str, now),
            )
            conn.commit()

        import asyncio

        try:
            await asyncio.to_thread(_save)
        except Exception:
            logger.warning("[CE] Failed to save ledger to SQLite", exc_info=True)

    async def load_ledger(self) -> list[dict[str, Any]]:
        def _load() -> str | None:
            conn = self._ensure_connection()
            row = conn.execute(
                "SELECT ledger_json FROM ce_ledger WHERE loop_id = ?",
                (self._loop_id,),
            ).fetchone()
            return row["ledger_json"] if row else None

        import asyncio

        try:
            json_str = await asyncio.to_thread(_load)
        except Exception:
            logger.warning("[CE] Failed to load ledger from SQLite", exc_info=True)
            return []

        if json_str is None:
            return []

        try:
            return json.loads(json_str)
        except Exception:
            logger.warning("[CE] Failed to parse ledger JSON", exc_info=True)
            return []

    async def clear(self) -> None:
        def _clear() -> None:
            conn = self._ensure_connection()
            conn.execute("DELETE FROM ce_dag WHERE loop_id = ?", (self._loop_id,))
            conn.execute("DELETE FROM ce_ledger WHERE loop_id = ?", (self._loop_id,))
            conn.commit()

        import asyncio

        try:
            await asyncio.to_thread(_clear)
        except Exception:
            logger.warning("[CE] Failed to clear CE tables", exc_info=True)


def purge_loop_context_engine_state(
    loop_id: str,
    *,
    db_path: Path | None = None,
) -> None:
    """Delete ContextEngine rows for ``loop_id`` from the shared database."""
    from soothe.sloop.checkpoints.runtime_paths import (
        resolve_context_engine_db_path,
    )

    path = db_path or resolve_context_engine_db_path()
    if not path.is_file():
        return
    try:
        with sqlite3.connect(str(path), timeout=30) as conn:
            conn.execute("DELETE FROM ce_dag WHERE loop_id = ?", (loop_id,))
            conn.execute("DELETE FROM ce_ledger WHERE loop_id = ?", (loop_id,))
            conn.commit()
    except sqlite3.Error:
        logger.warning("[CE] Failed to purge loop %s from %s", loop_id, path, exc_info=True)
