"""SQLite persistence for per-loop display card mutations."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path

from soothe_sdk.display.card_ledger import CardMutation

from soothe.foundation.loop.state.persistence.runtime_paths import resolve_display_db_path

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
"""


class DisplayCardStore:
    """Append-only SQLite store for ``CardMutation`` rows."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or resolve_display_db_path()
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connection(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is not None:
                return self._conn
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), timeout=30, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=60000")
            conn.executescript(_SCHEMA)
            conn.commit()
            self._conn = conn
            return conn

    def list_mutations(self, loop_id: str) -> list[CardMutation]:
        """Load all mutations for a loop ordered by ``seq``."""
        conn = self._connection()
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

    def append_mutations(self, loop_id: str, mutations: list[CardMutation]) -> None:
        """Insert mutations; ignores duplicates on ``(loop_id, seq)``."""
        if not mutations:
            return
        conn = self._connection()
        with self._lock:
            conn.executemany(
                """
                INSERT OR IGNORE INTO display_card_mutations
                (loop_id, seq, ts, op, card_id, kind, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
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
                ],
            )
            conn.commit()

    def replace_mutations(self, loop_id: str, mutations: list[CardMutation]) -> None:
        """Replace all mutations for a loop."""
        conn = self._connection()
        with self._lock:
            conn.execute(
                "DELETE FROM display_card_mutations WHERE loop_id = ?",
                (loop_id,),
            )
            if mutations:
                conn.executemany(
                    """
                    INSERT INTO display_card_mutations
                    (loop_id, seq, ts, op, card_id, kind, data_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
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
                    ],
                )
            conn.commit()

    def delete_loop(self, loop_id: str) -> None:
        """Delete all card mutations for a loop."""
        conn = self._connection()
        with self._lock:
            conn.execute(
                "DELETE FROM display_card_mutations WHERE loop_id = ?",
                (loop_id,),
            )
            conn.commit()

    def peek_user_prompt(
        self,
        loop_id: str,
        *,
        max_chars: int = 120,
    ) -> str | None:
        """Return the first user card content for ``loop_id``, if present."""
        conn = self._connection()
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

    def peek_latest_assistant_response(
        self,
        loop_id: str,
        *,
        max_chars: int = 120,
    ) -> str | None:
        """Return the latest assistant card content for ``loop_id``, if present."""
        conn = self._connection()
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

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None


_shared_store: DisplayCardStore | None = None
_shared_store_lock = threading.Lock()


def get_display_card_store(db_path: Path | None = None) -> DisplayCardStore:
    """Return a process-wide ``DisplayCardStore`` singleton."""
    global _shared_store
    with _shared_store_lock:
        if _shared_store is None or (db_path is not None and _shared_store.db_path != db_path):
            _shared_store = DisplayCardStore(db_path=db_path)
        return _shared_store


__all__ = ["DisplayCardStore", "get_display_card_store"]
