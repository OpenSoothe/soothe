"""Display card mutation persistence (RFC-413).

SQLite (``databases/display.db``) is the default. When ``persistence.default_backend`` is
``postgresql``, the process configures a PostgreSQL store in ``soothe_metadata``.

Moved from ``soothe_nano`` to the daemon (IG-635 PR-2): display cards are a
daemon display concept with no standalone-nano consumers; the store and its
DDL belong here beside ``LoopCardLedger`` / ``LoopCardManager``.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from soothe.sloop.checkpoints.runtime_paths import resolve_display_db_path
from soothe_sdk.display.card_ledger import CardMutation

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS display_card_mutations (
    loop_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    op TEXT NOT NULL,
    card_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY (loop_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_display_cards_loop
    ON display_card_mutations(loop_id, seq);
CREATE TABLE IF NOT EXISTS goal_display_snapshots (
    loop_id TEXT NOT NULL,
    goal_index INTEGER NOT NULL,
    goal_id TEXT NOT NULL,
    frozen_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    card_count INTEGER NOT NULL,
    PRIMARY KEY (loop_id, goal_index)
);
CREATE INDEX IF NOT EXISTS idx_goal_snapshots_loop
    ON goal_display_snapshots(loop_id, goal_index);
"""


@runtime_checkable
class DisplayCardStoreProtocol(Protocol):
    """Shared sync API for SQLite and PostgreSQL display card stores."""

    def list_mutations(self, loop_id: str) -> list[CardMutation]: ...

    def append_mutations(self, loop_id: str, mutations: list[CardMutation]) -> None: ...

    def replace_mutations(self, loop_id: str, mutations: list[CardMutation]) -> None: ...

    def delete_loop(self, loop_id: str) -> None: ...

    def list_goal_snapshots(self, loop_id: str) -> list[dict[str, Any]]: ...

    def goal_snapshot_count(self, loop_id: str) -> int: ...

    def insert_goal_snapshot_with_auto_index(
        self,
        loop_id: str,
        *,
        goal_id: str | None,
        snapshot: dict[str, Any],
    ) -> tuple[int, str]: ...

    def insert_goal_snapshot(
        self,
        loop_id: str,
        *,
        goal_index: int,
        goal_id: str,
        snapshot: dict[str, Any],
    ) -> None: ...

    def peek_user_prompt(self, loop_id: str, *, max_chars: int = 120) -> str | None: ...

    def peek_latest_assistant_response(
        self, loop_id: str, *, max_chars: int = 120
    ) -> str | None: ...

    def close(self) -> None: ...


class DisplayCardStore:
    """Append-only SQLite store for ``CardMutation`` rows (Runtime-backed)."""

    def __init__(self, db_path: Path | None = None) -> None:
        from soothe_nano.persistence.sqlite_runtime import SqliteRuntimeRegistry

        self._db_path = db_path or resolve_display_db_path()
        self._runtime = SqliteRuntimeRegistry.acquire(self._db_path)
        self._runtime.run_write_sync(lambda conn: conn.executescript(_SCHEMA))

    @property
    def db_path(self) -> Path:
        return self._db_path

    def list_mutations(self, loop_id: str) -> list[CardMutation]:
        """Load all mutations for a loop ordered by ``seq``."""

        def _read(conn: Any) -> list[CardMutation]:
            cursor = conn.execute(
                """
                SELECT seq, ts, op, card_id, kind, data_json
                FROM display_card_mutations
                WHERE loop_id = ?
                ORDER BY seq ASC
                """,
                (loop_id,),
            )
            mutations: list[CardMutation] = []
            for row in cursor.fetchall():
                data = json.loads(row[5])
                mutations.append(
                    CardMutation(
                        seq=int(row[0]),
                        ts=str(row[1]),
                        op=row[2],  # type: ignore[arg-type]
                        card_id=str(row[3]),
                        kind=str(row[4]),
                        data=data,
                    )
                )
            return mutations

        return self._runtime.run_read_sync(_read)

    def append_mutations(self, loop_id: str, mutations: list[CardMutation]) -> None:
        """Insert mutations; ignores duplicates on ``(loop_id, seq)``."""
        if not mutations:
            return
        rows = [
            (
                loop_id,
                mutation.seq,
                mutation.ts,
                mutation.op,
                mutation.card_id,
                mutation.kind,
                json.dumps(mutation.data, default=str),
            )
            for mutation in mutations
        ]

        def _write(conn: Any) -> None:
            conn.executemany(
                """
                INSERT OR IGNORE INTO display_card_mutations
                (loop_id, seq, ts, op, card_id, kind, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        self._runtime.run_write_sync(_write)

    def replace_mutations(self, loop_id: str, mutations: list[CardMutation]) -> None:
        """Replace all mutations for a loop."""
        rows = [
            (
                loop_id,
                mutation.seq,
                mutation.ts,
                mutation.op,
                mutation.card_id,
                mutation.kind,
                json.dumps(mutation.data, default=str),
            )
            for mutation in mutations
        ]

        def _write(conn: Any) -> None:
            conn.execute(
                "DELETE FROM display_card_mutations WHERE loop_id = ?",
                (loop_id,),
            )
            if rows:
                conn.executemany(
                    """
                    INSERT INTO display_card_mutations
                    (loop_id, seq, ts, op, card_id, kind, data_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )

        self._runtime.run_write_sync(_write)

    def delete_loop(self, loop_id: str) -> None:
        """Delete all card mutations and goal snapshots for a loop."""

        def _write(conn: Any) -> None:
            conn.execute(
                "DELETE FROM display_card_mutations WHERE loop_id = ?",
                (loop_id,),
            )
            conn.execute(
                "DELETE FROM goal_display_snapshots WHERE loop_id = ?",
                (loop_id,),
            )

        self._runtime.run_write_sync(_write)

    def list_goal_snapshots(self, loop_id: str) -> list[dict[str, Any]]:
        """Load goal display snapshots ordered by ``goal_index``."""

        def _read(conn: Any) -> list[dict[str, Any]]:
            cursor = conn.execute(
                """
                SELECT snapshot_json
                FROM goal_display_snapshots
                WHERE loop_id = ?
                ORDER BY goal_index ASC
                """,
                (loop_id,),
            )
            out: list[dict[str, Any]] = []
            for row in cursor.fetchall():
                try:
                    data = json.loads(row[0])
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    out.append(data)
            return out

        return self._runtime.run_read_sync(_read)

    def goal_snapshot_count(self, loop_id: str) -> int:
        """Return number of stored goal snapshots for a loop."""

        def _read(conn: Any) -> int:
            row = conn.execute(
                "SELECT COUNT(*) FROM goal_display_snapshots WHERE loop_id = ?",
                (loop_id,),
            ).fetchone()
            return int(row[0]) if row else 0

        return self._runtime.run_read_sync(_read)

    def insert_goal_snapshot_with_auto_index(
        self,
        loop_id: str,
        *,
        goal_id: str | None,
        snapshot: dict[str, Any],
    ) -> tuple[int, str]:
        """Reserve ``goal_index`` and insert the snapshot in one critical section."""

        def _write(conn: Any) -> tuple[int, str]:
            row = conn.execute(
                """
                SELECT COALESCE(MAX(goal_index), -1) + 1
                FROM goal_display_snapshots
                WHERE loop_id = ?
                """,
                (loop_id,),
            ).fetchone()
            goal_index = int(row[0]) if row else 0
            resolved_goal_id = goal_id or f"{loop_id}_goal_{goal_index}"
            snapshot_body = dict(snapshot)
            snapshot_body["goal_index"] = goal_index
            snapshot_body["goal_id"] = resolved_goal_id
            card_count = int(snapshot_body.get("card_count") or 0)
            frozen_at = str(
                snapshot_body.get("completed_at") or snapshot_body.get("started_at") or ""
            )
            if not frozen_at:
                from datetime import UTC, datetime

                frozen_at = datetime.now(UTC).isoformat()
            conn.execute(
                """
                INSERT OR IGNORE INTO goal_display_snapshots
                (loop_id, goal_index, goal_id, frozen_at, snapshot_json, card_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    loop_id,
                    goal_index,
                    resolved_goal_id,
                    frozen_at,
                    json.dumps(snapshot_body, default=str),
                    card_count,
                ),
            )
            return goal_index, resolved_goal_id

        return self._runtime.run_write_sync(_write)

    def insert_goal_snapshot(
        self,
        loop_id: str,
        *,
        goal_index: int,
        goal_id: str,
        snapshot: dict[str, Any],
    ) -> None:
        """Insert one immutable goal snapshot (ignore duplicate goal_index)."""
        card_count = int(snapshot.get("card_count") or 0)
        frozen_at = str(snapshot.get("completed_at") or snapshot.get("started_at") or "")
        if not frozen_at:
            from datetime import UTC, datetime

            frozen_at = datetime.now(UTC).isoformat()
        payload = (
            loop_id,
            goal_index,
            goal_id,
            frozen_at,
            json.dumps(snapshot, default=str),
            card_count,
        )

        def _write(conn: Any) -> None:
            conn.execute(
                """
                INSERT OR IGNORE INTO goal_display_snapshots
                (loop_id, goal_index, goal_id, frozen_at, snapshot_json, card_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                payload,
            )

        self._runtime.run_write_sync(_write)

    def peek_user_prompt(
        self,
        loop_id: str,
        *,
        max_chars: int = 120,
    ) -> str | None:
        """Return the first user card content for ``loop_id``, if present."""

        def _read(conn: Any) -> str | None:
            row = conn.execute(
                """
                SELECT data_json
                FROM display_card_mutations
                WHERE loop_id = ? AND op = 'create' AND kind = 'user'
                ORDER BY seq ASC
                LIMIT 1
                """,
                (loop_id,),
            ).fetchone()
            if row is None:
                return None
            try:
                data = json.loads(row[0])
            except json.JSONDecodeError:
                return None
            if not isinstance(data, dict):
                return None
            content = data.get("content")
            if not isinstance(content, str):
                return None
            cleaned = " ".join(content.split())
            if not cleaned:
                return None
            if len(cleaned) > max_chars:
                return cleaned[: max_chars - 1] + "…"
            return cleaned

        return self._runtime.run_read_sync(_read)

    def peek_latest_assistant_response(
        self,
        loop_id: str,
        *,
        max_chars: int = 120,
    ) -> str | None:
        """Return the latest assistant card content for ``loop_id``, if present."""

        def _read(conn: Any) -> str | None:
            row = conn.execute(
                """
                SELECT data_json
                FROM display_card_mutations
                WHERE loop_id = ? AND op = 'create' AND kind = 'assistant'
                ORDER BY seq DESC
                LIMIT 1
                """,
                (loop_id,),
            ).fetchone()
            if row is None:
                return None
            try:
                data = json.loads(row[0])
            except json.JSONDecodeError:
                return None
            if not isinstance(data, dict):
                return None
            content = data.get("content")
            if not isinstance(content, str):
                return None
            cleaned = " ".join(content.split())
            if not cleaned:
                return None
            if len(cleaned) > max_chars:
                return cleaned[: max_chars - 1] + "…"
            return cleaned

        return self._runtime.run_read_sync(_read)

    def close(self) -> None:
        from soothe_nano.persistence.sqlite_runtime import SqliteRuntimeRegistry

        SqliteRuntimeRegistry.release_sync(self._db_path)


_shared_store: DisplayCardStoreProtocol | None = None
_shared_store_lock = threading.Lock()


def _close_shared_store_unlocked() -> None:
    global _shared_store
    if _shared_store is None:
        return
    try:
        _shared_store.close()
    except Exception:
        logger.debug("Error closing display card store", exc_info=True)
    _shared_store = None


def configure_display_card_store(config: SootheConfig) -> DisplayCardStoreProtocol:
    """Select SQLite or PostgreSQL display store from ``persistence.default_backend``.

    Call once during process startup after PostgreSQL databases are provisioned.
    """
    global _shared_store
    with _shared_store_lock:
        _close_shared_store_unlocked()
        if config.persistence.default_backend == "postgresql":
            from soothe_daemon.display.display_store_postgres import (
                PostgresDisplayCardStore,
            )

            dsn = config.resolve_postgres_dsn_for_database("metadata")
            store: DisplayCardStoreProtocol = PostgresDisplayCardStore(dsn=dsn)
            logger.info("Display card store backend=postgresql db=metadata")
        else:
            store = DisplayCardStore()
            logger.info("Display card store backend=sqlite path=%s", store.db_path)
        _shared_store = store
        return store


def get_display_card_store(db_path: Path | None = None) -> DisplayCardStoreProtocol:
    """Return the process-wide display card store singleton.

    Pass ``db_path`` only in tests to force an isolated SQLite file.
    """
    global _shared_store
    with _shared_store_lock:
        if db_path is not None:
            current_path = getattr(_shared_store, "db_path", None)
            if _shared_store is None or current_path != db_path:
                _close_shared_store_unlocked()
                _shared_store = DisplayCardStore(db_path=db_path)
            return _shared_store
        if _shared_store is None:
            _shared_store = DisplayCardStore()
        return _shared_store


def reset_display_card_store_for_tests() -> None:
    """Clear the process-wide singleton (tests only)."""
    with _shared_store_lock:
        _close_shared_store_unlocked()


__all__ = [
    "DisplayCardStore",
    "DisplayCardStoreProtocol",
    "configure_display_card_store",
    "get_display_card_store",
    "reset_display_card_store_for_tests",
]
