"""SQLite persistence backend for the Context Engine (RFC-624 Phase 4).

Stores CE DAG and ledger in ``databases/context.db`` keyed by ``loop_id``.
Uses process-scoped ``SqliteStoreRuntime`` (RFC-801 / IG-647).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from soothe_nano.persistence.sqlite_runtime import SqliteRuntimeRegistry, SqliteStoreRuntime

from soothe.context.models import GoalStepDAG, GoalStepDAGSnapshot

logger = logging.getLogger(__name__)


def _ensure_ce_schema(conn: Any) -> None:
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


class SqliteContextPersistence:
    """SQLite-backed persistence for ContextEngine via ``SqliteStoreRuntime``.

    Args:
        loop_id: Loop identifier used as primary key.
        db_path: Path to the SQLite database file.
    """

    def __init__(self, loop_id: str, db_path: Path) -> None:
        self._loop_id = loop_id
        self._db_path = Path(db_path)
        self._runtime: SqliteStoreRuntime = SqliteRuntimeRegistry.acquire(self._db_path)
        self._owns_private_runtime = (
            str(self._db_path) == ":memory:" or self._db_path.name == ":memory:"
        )
        self._runtime.run_write_sync(_ensure_ce_schema)

    async def close(self) -> None:
        """Release Runtime (or close private ``:memory:`` Runtime)."""
        if self._owns_private_runtime:
            await self._runtime.close()
            return
        try:
            await SqliteRuntimeRegistry.release(self._db_path)
        except Exception:
            logger.warning("[CE] Failed to release SQLite Runtime", exc_info=True)

    async def save_dag(self, dag: GoalStepDAG) -> None:
        snapshot = dag.snapshot()
        data = snapshot.model_dump(mode="json")
        json_str = json.dumps(data, default=str)
        loop_id = self._loop_id

        def _save(conn: Any) -> None:
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
                (loop_id, json_str, now),
            )

        try:
            await self._runtime.run_write(_save)
        except Exception:
            logger.warning("[CE] Failed to save DAG to SQLite", exc_info=True)

    async def load_dag(self) -> GoalStepDAG | None:
        loop_id = self._loop_id

        def _load(conn: Any) -> str | None:
            row = conn.execute(
                "SELECT dag_json FROM ce_dag WHERE loop_id = ?",
                (loop_id,),
            ).fetchone()
            return row["dag_json"] if row else None

        try:
            json_str = await self._runtime.run_read(_load)
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
        loop_id = self._loop_id

        def _save(conn: Any) -> None:
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
                (loop_id, json_str, now),
            )

        try:
            await self._runtime.run_write(_save)
        except Exception:
            logger.warning("[CE] Failed to save ledger to SQLite", exc_info=True)

    async def load_ledger(self) -> list[dict[str, Any]]:
        loop_id = self._loop_id

        def _load(conn: Any) -> str | None:
            row = conn.execute(
                "SELECT ledger_json FROM ce_ledger WHERE loop_id = ?",
                (loop_id,),
            ).fetchone()
            return row["ledger_json"] if row else None

        try:
            json_str = await self._runtime.run_read(_load)
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
        loop_id = self._loop_id

        def _clear(conn: Any) -> None:
            conn.execute("DELETE FROM ce_dag WHERE loop_id = ?", (loop_id,))
            conn.execute("DELETE FROM ce_ledger WHERE loop_id = ?", (loop_id,))

        try:
            await self._runtime.run_write(_clear)
        except Exception:
            logger.warning("[CE] Failed to clear CE tables", exc_info=True)


def purge_loop_context_engine_state(
    loop_id: str,
    *,
    db_path: Path | None = None,
) -> None:
    """Delete ContextEngine rows for ``loop_id`` from the shared database."""
    from soothe.sloop.checkpoints.runtime_paths import (
        resolve_context_db_path,
    )

    path = db_path or resolve_context_db_path()
    if not path.is_file():
        return
    runtime = SqliteRuntimeRegistry.acquire(path)
    try:

        def _purge(conn: Any) -> None:
            _ensure_ce_schema(conn)
            conn.execute("DELETE FROM ce_dag WHERE loop_id = ?", (loop_id,))
            conn.execute("DELETE FROM ce_ledger WHERE loop_id = ?", (loop_id,))

        runtime.run_write_sync(_purge)
    except Exception:
        logger.warning("[CE] Failed to purge loop %s from %s", loop_id, path, exc_info=True)
    finally:
        SqliteRuntimeRegistry.release_sync(path)
