"""PostgreSQL persistence for per-loop display card mutations (RFC-413).

Used when ``persistence.default_backend`` is ``postgresql``. Tables live in the
RFC-612 ``metadata`` database (``soothe_metadata``) beside durability KV rows.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any

from soothe_sdk.display.card_ledger import CardMutation

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS display_card_mutations (
    loop_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    op TEXT NOT NULL,
    card_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    data_json JSONB NOT NULL,
    PRIMARY KEY (loop_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_display_cards_loop
    ON display_card_mutations(loop_id, seq);
CREATE TABLE IF NOT EXISTS goal_display_snapshots (
    loop_id TEXT NOT NULL,
    goal_index INTEGER NOT NULL,
    goal_id TEXT NOT NULL,
    frozen_at TEXT NOT NULL,
    snapshot_json JSONB NOT NULL,
    card_count INTEGER NOT NULL,
    PRIMARY KEY (loop_id, goal_index)
);
CREATE INDEX IF NOT EXISTS idx_goal_snapshots_loop
    ON goal_display_snapshots(loop_id, goal_index);
"""


class PostgresDisplayCardStore:
    """Append-only PostgreSQL store for ``CardMutation`` rows."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._lock = threading.Lock()
        self._pool: Any | None = None
        self._schema_ready = False

    @property
    def dsn(self) -> str:
        return self._dsn

    @property
    def db_path(self) -> None:
        """SQLite path compatibility; always ``None`` for PostgreSQL."""
        return None

    def _ensure_pool(self) -> Any:
        with self._lock:
            if self._pool is not None:
                return self._pool
            try:
                from psycopg_pool import ConnectionPool
            except ImportError as exc:
                msg = "psycopg_pool is required for PostgreSQL display card store"
                raise ImportError(msg) from exc

            pool = ConnectionPool(
                conninfo=self._dsn,
                min_size=1,
                max_size=4,
                open=True,
                kwargs={"autocommit": False},
            )
            self._pool = pool
            self._ensure_schema_unlocked(pool)
            return pool

    def _ensure_schema_unlocked(self, pool: Any) -> None:
        if self._schema_ready:
            return
        with pool.connection() as conn:
            with conn.cursor() as cur:
                for statement in _split_statements(_SCHEMA):
                    cur.execute(statement)
            conn.commit()
        self._schema_ready = True

    def list_mutations(self, loop_id: str) -> list[CardMutation]:
        """Load all mutations for a loop ordered by ``seq``."""
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT seq, ts, op, card_id, kind, data_json
                    FROM display_card_mutations
                    WHERE loop_id = %s
                    ORDER BY seq ASC
                    """,
                    (loop_id,),
                )
                rows = cur.fetchall()
        mutations: list[CardMutation] = []
        for row in rows:
            data = row[5]
            if isinstance(data, str):
                data = json.loads(data)
            mutations.append(
                CardMutation(
                    seq=int(row[0]),
                    ts=str(row[1]),
                    op=row[2],  # type: ignore[arg-type]
                    card_id=str(row[3]),
                    kind=str(row[4]),
                    data=data if isinstance(data, dict) else {},
                )
            )
        return mutations

    def append_mutations(self, loop_id: str, mutations: list[CardMutation]) -> None:
        """Insert mutations; ignores duplicates on ``(loop_id, seq)``."""
        if not mutations:
            return
        pool = self._ensure_pool()
        with self._lock:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        INSERT INTO display_card_mutations
                        (loop_id, seq, ts, op, card_id, kind, data_json)
                        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT (loop_id, seq) DO NOTHING
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
        pool = self._ensure_pool()
        with self._lock:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM display_card_mutations WHERE loop_id = %s",
                        (loop_id,),
                    )
                    if mutations:
                        cur.executemany(
                            """
                            INSERT INTO display_card_mutations
                            (loop_id, seq, ts, op, card_id, kind, data_json)
                            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
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
        """Delete all card mutations and goal snapshots for a loop."""
        pool = self._ensure_pool()
        with self._lock:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM display_card_mutations WHERE loop_id = %s",
                        (loop_id,),
                    )
                    cur.execute(
                        "DELETE FROM goal_display_snapshots WHERE loop_id = %s",
                        (loop_id,),
                    )
                conn.commit()

    def list_goal_snapshots(self, loop_id: str) -> list[dict[str, Any]]:
        """Load goal display snapshots ordered by ``goal_index``."""
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT snapshot_json
                    FROM goal_display_snapshots
                    WHERE loop_id = %s
                    ORDER BY goal_index ASC
                    """,
                    (loop_id,),
                )
                rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            data = row[0]
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    continue
            if isinstance(data, dict):
                out.append(data)
        return out

    def goal_snapshot_count(self, loop_id: str) -> int:
        """Return number of stored goal snapshots for a loop."""
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM goal_display_snapshots WHERE loop_id = %s",
                    (loop_id,),
                )
                row = cur.fetchone()
        return int(row[0]) if row else 0

    def allocate_goal_snapshot_index(self, loop_id: str) -> int:
        """Return the next goal snapshot index without inserting (non-atomic alone)."""
        pool = self._ensure_pool()
        with self._lock:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(MAX(goal_index), -1) + 1
                        FROM goal_display_snapshots
                        WHERE loop_id = %s
                        """,
                        (loop_id,),
                    )
                    row = cur.fetchone()
            return int(row[0]) if row else 0

    def insert_goal_snapshot_with_auto_index(
        self,
        loop_id: str,
        *,
        goal_id: str | None,
        snapshot: dict[str, Any],
    ) -> tuple[int, str]:
        """Reserve ``goal_index`` and insert the snapshot in one critical section."""
        pool = self._ensure_pool()
        with self._lock:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(MAX(goal_index), -1) + 1
                        FROM goal_display_snapshots
                        WHERE loop_id = %s
                        """,
                        (loop_id,),
                    )
                    row = cur.fetchone()
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
                        frozen_at = datetime.now(UTC).isoformat()
                    cur.execute(
                        """
                        INSERT INTO goal_display_snapshots
                        (loop_id, goal_index, goal_id, frozen_at, snapshot_json, card_count)
                        VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                        ON CONFLICT (loop_id, goal_index) DO NOTHING
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
                conn.commit()
            return goal_index, resolved_goal_id

    def insert_goal_snapshot(
        self,
        loop_id: str,
        *,
        goal_index: int,
        goal_id: str,
        snapshot: dict[str, Any],
    ) -> None:
        """Insert one immutable goal snapshot (ignore duplicate goal_index)."""
        pool = self._ensure_pool()
        card_count = int(snapshot.get("card_count") or 0)
        frozen_at = str(snapshot.get("completed_at") or snapshot.get("started_at") or "")
        if not frozen_at:
            frozen_at = datetime.now(UTC).isoformat()
        with self._lock:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO goal_display_snapshots
                        (loop_id, goal_index, goal_id, frozen_at, snapshot_json, card_count)
                        VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                        ON CONFLICT (loop_id, goal_index) DO NOTHING
                        """,
                        (
                            loop_id,
                            goal_index,
                            goal_id,
                            frozen_at,
                            json.dumps(snapshot, default=str),
                            card_count,
                        ),
                    )
                conn.commit()

    def peek_user_prompt(
        self,
        loop_id: str,
        *,
        max_chars: int = 120,
    ) -> str | None:
        """Return the first user card content for ``loop_id``, if present."""
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT data_json
                    FROM display_card_mutations
                    WHERE loop_id = %s AND op = 'create' AND kind = 'user'
                    ORDER BY seq ASC
                    LIMIT 1
                    """,
                    (loop_id,),
                )
                row = cur.fetchone()
        return _peek_content(row[0] if row else None, max_chars=max_chars)

    def peek_latest_assistant_response(
        self,
        loop_id: str,
        *,
        max_chars: int = 120,
    ) -> str | None:
        """Return the latest assistant card content for ``loop_id``, if present."""
        pool = self._ensure_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT data_json
                    FROM display_card_mutations
                    WHERE loop_id = %s AND op = 'create' AND kind = 'assistant'
                    ORDER BY seq DESC
                    LIMIT 1
                    """,
                    (loop_id,),
                )
                row = cur.fetchone()
        return _peek_content(row[0] if row else None, max_chars=max_chars)

    def close(self) -> None:
        with self._lock:
            pool = self._pool
            self._pool = None
            self._schema_ready = False
        if pool is not None:
            try:
                pool.close()
            except Exception:
                logger.debug("Error closing PostgreSQL display card pool", exc_info=True)


def _split_statements(sql: str) -> list[str]:
    return [part.strip() for part in sql.split(";") if part.strip()]


def _peek_content(raw: Any, *, max_chars: int) -> str | None:
    if raw is None:
        return None
    data = raw
    if isinstance(data, str):
        try:
            data = json.loads(data)
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


__all__ = ["PostgresDisplayCardStore"]
