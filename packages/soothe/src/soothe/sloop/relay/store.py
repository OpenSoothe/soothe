"""CE-backed durable store for clarification relay rows.

The `clarifications` table lives in the same database as the Context Engine
tables. One backend mode per process (Rule #10). Rows are keyed by `relay_id`
and indexed by `goal_id` and `loop_id`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel

from soothe.sloop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationRequest,
    answer_from_state,
    answer_to_state,
    request_from_state,
    request_to_state,
)

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS clarifications (
    relay_id              TEXT PRIMARY KEY,
    loop_id               TEXT NOT NULL,
    goal_id               TEXT NOT NULL,
    origin                TEXT NOT NULL,
    origin_interrupt_id   TEXT NOT NULL,
    core_agent_thread_id  TEXT,
    step_id               TEXT,
    step_description      TEXT,
    request_json          TEXT NOT NULL,
    status                TEXT NOT NULL,
    answer_json           TEXT,
    answer_source         TEXT,
    idempotency_key       TEXT,
    captured_at           TEXT NOT NULL,
    parked_at             TEXT,
    answered_at           TEXT,
    consumed_at           TEXT,
    retry_count           INTEGER DEFAULT 0,
    defer_kind            TEXT,
    policy_mode           TEXT
);
CREATE INDEX IF NOT EXISTS idx_clar_goal ON clarifications(goal_id, status);
CREATE INDEX IF NOT EXISTS idx_clar_loop ON clarifications(loop_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_clar_idem ON clarifications(idempotency_key)
    WHERE idempotency_key IS NOT NULL;
"""

_SCHEMA_PGSQL = """
CREATE TABLE IF NOT EXISTS clarifications (
    relay_id              TEXT PRIMARY KEY,
    loop_id               TEXT NOT NULL,
    goal_id               TEXT NOT NULL,
    origin                TEXT NOT NULL,
    origin_interrupt_id   TEXT NOT NULL,
    core_agent_thread_id  TEXT,
    step_id               TEXT,
    step_description      TEXT,
    request_json          TEXT NOT NULL,
    status                TEXT NOT NULL,
    answer_json           TEXT,
    answer_source         TEXT,
    idempotency_key       TEXT,
    captured_at           TIMESTAMPTZ NOT NULL,
    parked_at             TIMESTAMPTZ,
    answered_at           TIMESTAMPTZ,
    consumed_at           TIMESTAMPTZ,
    retry_count           INTEGER DEFAULT 0,
    defer_kind            TEXT,
    policy_mode           TEXT
);
CREATE INDEX IF NOT EXISTS idx_clar_goal ON clarifications(goal_id, status);
CREATE INDEX IF NOT EXISTS idx_clar_loop ON clarifications(loop_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_clar_idem ON clarifications(idempotency_key)
    WHERE idempotency_key IS NOT NULL;
"""

_PENDING_STATUSES = ("captured", "parked")


class ClarificationRow(BaseModel):
    """One row in the `clarifications` table.

    Use `decode_request()` / `decode_answer()` to reconstruct typed objects
    from the JSON fields.
    """

    relay_id: str
    loop_id: str
    goal_id: str
    origin: str
    origin_interrupt_id: str
    core_agent_thread_id: str | None = None
    step_id: str | None = None
    step_description: str | None = None
    request_json: str
    status: str = "captured"
    answer_json: str | None = None
    answer_source: str | None = None
    idempotency_key: str | None = None
    captured_at: str
    parked_at: str | None = None
    answered_at: str | None = None
    consumed_at: str | None = None
    retry_count: int = 0
    defer_kind: str | None = None
    policy_mode: str | None = None

    def decode_request(self) -> ClarificationRequest:
        """Reconstruct the `ClarificationRequest` from `request_json`."""
        return request_from_state(json.loads(self.request_json))

    def decode_answer(self) -> ClarificationAnswer | None:
        """Reconstruct the `ClarificationAnswer` from `answer_json`."""
        if not self.answer_json:
            return None
        return answer_from_state(json.loads(self.answer_json))

    @classmethod
    def from_handle(
        cls,
        *,
        relay_id: str,
        loop_id: str,
        goal_id: str,
        handle_origin: str,
        handle_interrupt_id: str,
        request: ClarificationRequest,
        core_agent_thread_id: str | None,
        step_id: str | None,
        step_description: str | None,
        policy_mode: str,
        captured_at: str | None = None,
    ) -> ClarificationRow:
        """Build a row from capture-time fields."""
        return cls(
            relay_id=relay_id,
            loop_id=loop_id,
            goal_id=goal_id,
            origin=handle_origin,
            origin_interrupt_id=handle_interrupt_id,
            core_agent_thread_id=core_agent_thread_id,
            step_id=step_id,
            step_description=step_description,
            request_json=json.dumps(request_to_state(request), default=str),
            status="captured",
            captured_at=captured_at or datetime.now(UTC).isoformat(),
            policy_mode=policy_mode,
        )


def encode_answer(answer: ClarificationAnswer) -> str:
    """Serialize a `ClarificationAnswer` for storage."""
    return json.dumps(answer_to_state(answer), default=str)


class ClarificationStore(Protocol):
    """Durable store for clarification relay rows."""

    async def insert(self, row: ClarificationRow) -> None: ...
    async def get(self, relay_id: str) -> ClarificationRow | None: ...
    async def update(
        self,
        relay_id: str,
        *,
        status: str | None = None,
        answer_json: str | None = None,
        answer_source: str | None = None,
        idempotency_key: str | None = None,
        parked_at: str | None = None,
        answered_at: str | None = None,
        consumed_at: str | None = None,
        retry_count: int | None = None,
        defer_kind: str | None = None,
    ) -> bool: ...
    async def list_by_goal(
        self, goal_id: str, *, status: str | None = None
    ) -> list[ClarificationRow]: ...
    async def list_by_loop(
        self, loop_id: str, *, status: str | None = None
    ) -> list[ClarificationRow]: ...
    async def count_pending_by_goal(self, goal_id: str) -> int: ...
    async def count_retries_by_goal(self, goal_id: str) -> int: ...
    async def close(self) -> None: ...


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row_from_dict(d: Mapping[str, Any]) -> ClarificationRow:
    """Build a `ClarificationRow` from a DB row dict."""
    return ClarificationRow(
        relay_id=str(d["relay_id"]),
        loop_id=str(d["loop_id"]),
        goal_id=str(d["goal_id"]),
        origin=str(d["origin"]),
        origin_interrupt_id=str(d["origin_interrupt_id"]),
        core_agent_thread_id=d["core_agent_thread_id"],
        step_id=d["step_id"],
        step_description=d["step_description"],
        request_json=str(d["request_json"]),
        status=str(d["status"]),
        answer_json=d["answer_json"],
        answer_source=d["answer_source"],
        idempotency_key=d["idempotency_key"],
        captured_at=str(d["captured_at"]),
        parked_at=d["parked_at"],
        answered_at=d["answered_at"],
        consumed_at=d["consumed_at"],
        retry_count=int(d.get("retry_count", 0) or 0),
        defer_kind=d["defer_kind"],
        policy_mode=d["policy_mode"],
    )


class SqliteClarificationStore:
    """SQLite-backed `ClarificationStore` via `SqliteStoreRuntime`.

    Uses the same DB path as the Context Engine (`resolve_context_db_path()`).
    """

    def __init__(self, loop_id: str, db_path: Path) -> None:
        from soothe_nano.persistence.sqlite_runtime import (
            SqliteRuntimeRegistry,
            SqliteStoreRuntime,
        )

        self._loop_id = loop_id
        self._db_path = Path(db_path)
        self._runtime: SqliteStoreRuntime = SqliteRuntimeRegistry.acquire(self._db_path)
        self._owns_private_runtime = (
            str(self._db_path) == ":memory:" or self._db_path.name == ":memory:"
        )
        self._runtime.run_write_sync(_ensure_relay_schema)

    async def close(self) -> None:
        if self._owns_private_runtime:
            from soothe_nano.persistence.sqlite_runtime import SqliteRuntimeRegistry

            await self._runtime.close()
            return
        try:
            from soothe_nano.persistence.sqlite_runtime import SqliteRuntimeRegistry

            await SqliteRuntimeRegistry.release(self._db_path)
        except Exception:
            logger.warning("[Relay] Failed to release SQLite Runtime", exc_info=True)

    async def insert(self, row: ClarificationRow) -> None:
        def _insert(conn: Any) -> None:
            conn.execute(
                """
                INSERT INTO clarifications (
                    relay_id, loop_id, goal_id, origin, origin_interrupt_id,
                    core_agent_thread_id, step_id, step_description,
                    request_json, status, captured_at, policy_mode, retry_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.relay_id,
                    row.loop_id,
                    row.goal_id,
                    row.origin,
                    row.origin_interrupt_id,
                    row.core_agent_thread_id,
                    row.step_id,
                    row.step_description,
                    row.request_json,
                    row.status,
                    row.captured_at,
                    row.policy_mode,
                    row.retry_count,
                ),
            )

        try:
            await self._runtime.run_write(_insert)
        except Exception:
            logger.warning("[Relay] Failed to insert clarification row", exc_info=True)
            raise

    async def get(self, relay_id: str) -> ClarificationRow | None:
        def _get(conn: Any) -> dict[str, Any] | None:
            row = conn.execute(
                "SELECT * FROM clarifications WHERE relay_id = ?", (relay_id,)
            ).fetchone()
            return dict(row) if row else None

        try:
            data = await self._runtime.run_read(_get)
        except Exception:
            logger.warning("[Relay] Failed to get clarification row", exc_info=True)
            return None
        return _row_from_dict(data) if data else None

    async def update(
        self,
        relay_id: str,
        *,
        status: str | None = None,
        answer_json: str | None = None,
        answer_source: str | None = None,
        idempotency_key: str | None = None,
        parked_at: str | None = None,
        answered_at: str | None = None,
        consumed_at: str | None = None,
        retry_count: int | None = None,
        defer_kind: str | None = None,
    ) -> bool:
        fields: list[str] = []
        params: list[Any] = []
        for col, val in [
            ("status", status),
            ("answer_json", answer_json),
            ("answer_source", answer_source),
            ("idempotency_key", idempotency_key),
            ("parked_at", parked_at),
            ("answered_at", answered_at),
            ("consumed_at", consumed_at),
            ("retry_count", retry_count),
            ("defer_kind", defer_kind),
        ]:
            if val is not None:
                fields.append(f"{col} = ?")
                params.append(val)
        if not fields:
            return False

        sql = f"UPDATE clarifications SET {', '.join(fields)} WHERE relay_id = ?"
        params.append(relay_id)

        def _update(conn: Any) -> int:
            cur = conn.execute(sql, params)
            return cur.rowcount

        try:
            affected = await self._runtime.run_write(_update)
        except Exception:
            logger.warning("[Relay] Failed to update clarification row", exc_info=True)
            raise
        return affected > 0

    async def list_by_goal(
        self, goal_id: str, *, status: str | None = None
    ) -> list[ClarificationRow]:
        if status is not None:
            sql = "SELECT * FROM clarifications WHERE goal_id = ? AND status = ? ORDER BY captured_at ASC"
            params: tuple[Any, ...] = (goal_id, status)
        else:
            sql = "SELECT * FROM clarifications WHERE goal_id = ? ORDER BY captured_at ASC"
            params = (goal_id,)

        def _list(conn: Any) -> list[dict[str, Any]]:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

        try:
            data = await self._runtime.run_read(_list)
        except Exception:
            logger.warning("[Relay] Failed to list by goal", exc_info=True)
            return []
        return [_row_from_dict(d) for d in data]

    async def list_by_loop(
        self, loop_id: str, *, status: str | None = None
    ) -> list[ClarificationRow]:
        if status is not None:
            sql = "SELECT * FROM clarifications WHERE loop_id = ? AND status = ? ORDER BY captured_at ASC"
            params: tuple[Any, ...] = (loop_id, status)
        else:
            sql = "SELECT * FROM clarifications WHERE loop_id = ? ORDER BY captured_at ASC"
            params = (loop_id,)

        def _list(conn: Any) -> list[dict[str, Any]]:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

        try:
            data = await self._runtime.run_read(_list)
        except Exception:
            logger.warning("[Relay] Failed to list by loop", exc_info=True)
            return []
        return [_row_from_dict(d) for d in data]

    async def count_pending_by_goal(self, goal_id: str) -> int:
        placeholders = ",".join("?" * len(_PENDING_STATUSES))
        sql = f"SELECT COUNT(*) as cnt FROM clarifications WHERE goal_id = ? AND status IN ({placeholders})"
        params = (goal_id, *_PENDING_STATUSES)

        def _count(conn: Any) -> int:
            row = conn.execute(sql, params).fetchone()
            return int(row["cnt"]) if row else 0

        try:
            return await self._runtime.run_read(_count)
        except Exception:
            logger.warning("[Relay] Failed to count pending", exc_info=True)
            return 0

    async def count_retries_by_goal(self, goal_id: str) -> int:
        sql = "SELECT COUNT(*) as cnt FROM clarifications WHERE goal_id = ? AND answer_source = 'retry'"

        def _count(conn: Any) -> int:
            row = conn.execute(sql, (goal_id,)).fetchone()
            return int(row["cnt"]) if row else 0

        try:
            return await self._runtime.run_read(_count)
        except Exception:
            logger.warning("[Relay] Failed to count retries", exc_info=True)
            return 0


def _ensure_relay_schema(conn: Any) -> None:
    """Create the `clarifications` table and indexes if they don't exist."""
    conn.executescript(_SCHEMA_SQLITE)


class PgsqlClarificationStore:
    """PostgreSQL-backed `ClarificationStore` via `SharedPostgreSQLPool`."""

    def __init__(self, loop_id: str, *, config: SootheConfig) -> None:
        self._loop_id = loop_id
        self._config = config
        self._schema_ensured = False

    async def _shared_pool(self) -> Any:
        from soothe.sloop.checkpoints.shared_pool import SharedPostgreSQLPool

        wrapper = await SharedPostgreSQLPool.get_shared_instance(self._config)
        if wrapper is None:
            msg = "Shared PostgreSQL pool unavailable for relay store"
            raise RuntimeError(msg)
        pool = wrapper.get_pool()
        if pool is None:
            msg = "Shared PostgreSQL pool is not open"
            raise RuntimeError(msg)
        return pool

    async def _ensure_schema(self) -> None:
        if self._schema_ensured:
            return
        pool = await self._shared_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_SCHEMA_PGSQL)
        self._schema_ensured = True

    async def close(self) -> None:
        pass

    async def insert(self, row: ClarificationRow) -> None:
        await self._ensure_schema()
        pool = await self._shared_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO clarifications (
                        relay_id, loop_id, goal_id, origin, origin_interrupt_id,
                        core_agent_thread_id, step_id, step_description,
                        request_json, status, captured_at, policy_mode, retry_count
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row.relay_id,
                        row.loop_id,
                        row.goal_id,
                        row.origin,
                        row.origin_interrupt_id,
                        row.core_agent_thread_id,
                        row.step_id,
                        row.step_description,
                        row.request_json,
                        row.status,
                        row.captured_at,
                        row.policy_mode,
                        row.retry_count,
                    ),
                )

    async def get(self, relay_id: str) -> ClarificationRow | None:
        await self._ensure_schema()
        pool = await self._shared_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT * FROM clarifications WHERE relay_id = %s", (relay_id,))
                row = await cur.fetchone()
        return _row_from_dict(row) if row else None

    async def update(
        self,
        relay_id: str,
        *,
        status: str | None = None,
        answer_json: str | None = None,
        answer_source: str | None = None,
        idempotency_key: str | None = None,
        parked_at: str | None = None,
        answered_at: str | None = None,
        consumed_at: str | None = None,
        retry_count: int | None = None,
        defer_kind: str | None = None,
    ) -> bool:
        await self._ensure_schema()
        fields: list[str] = []
        params: list[Any] = []
        for col, val in [
            ("status", status),
            ("answer_json", answer_json),
            ("answer_source", answer_source),
            ("idempotency_key", idempotency_key),
            ("parked_at", parked_at),
            ("answered_at", answered_at),
            ("consumed_at", consumed_at),
            ("retry_count", retry_count),
            ("defer_kind", defer_kind),
        ]:
            if val is not None:
                fields.append(f"{col} = %s")
                params.append(val)
        if not fields:
            return False

        sql = f"UPDATE clarifications SET {', '.join(fields)} WHERE relay_id = %s"
        params.append(relay_id)

        pool = await self._shared_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                return cur.rowcount > 0

    async def list_by_goal(
        self, goal_id: str, *, status: str | None = None
    ) -> list[ClarificationRow]:
        await self._ensure_schema()
        pool = await self._shared_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                if status is not None:
                    await cur.execute(
                        "SELECT * FROM clarifications WHERE goal_id = %s AND status = %s ORDER BY captured_at ASC",
                        (goal_id, status),
                    )
                else:
                    await cur.execute(
                        "SELECT * FROM clarifications WHERE goal_id = %s ORDER BY captured_at ASC",
                        (goal_id,),
                    )
                rows = await cur.fetchall()
        return [_row_from_dict(r) for r in rows]

    async def list_by_loop(
        self, loop_id: str, *, status: str | None = None
    ) -> list[ClarificationRow]:
        await self._ensure_schema()
        pool = await self._shared_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                if status is not None:
                    await cur.execute(
                        "SELECT * FROM clarifications WHERE loop_id = %s AND status = %s ORDER BY captured_at ASC",
                        (loop_id, status),
                    )
                else:
                    await cur.execute(
                        "SELECT * FROM clarifications WHERE loop_id = %s ORDER BY captured_at ASC",
                        (loop_id,),
                    )
                rows = await cur.fetchall()
        return [_row_from_dict(r) for r in rows]

    async def count_pending_by_goal(self, goal_id: str) -> int:
        await self._ensure_schema()
        pool = await self._shared_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) as cnt FROM clarifications "
                    "WHERE goal_id = %s AND status IN ('captured', 'parked')",
                    (goal_id,),
                )
                row = await cur.fetchone()
        return int(row["cnt"]) if row else 0

    async def count_retries_by_goal(self, goal_id: str) -> int:
        await self._ensure_schema()
        pool = await self._shared_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) as cnt FROM clarifications "
                    "WHERE goal_id = %s AND answer_source = 'retry'",
                    (goal_id,),
                )
                row = await cur.fetchone()
        return int(row["cnt"]) if row else 0


def resolve_clarification_store(config: SootheConfig, loop_id: str) -> ClarificationStore:
    """Return a `ClarificationStore` for `loop_id`, branching on the backend."""
    backend = config.persistence.default_backend
    if backend == "postgresql":
        return PgsqlClarificationStore(loop_id, config=config)
    if backend not in ("sqlite", "postgresql"):
        msg = f"Unknown persistence backend: {backend}"
        raise ValueError(msg)
    from soothe.sloop.checkpoints.runtime_paths import resolve_context_db_path

    return SqliteClarificationStore(loop_id, db_path=resolve_context_db_path())


__all__ = [
    "ClarificationRow",
    "ClarificationStore",
    "PgsqlClarificationStore",
    "SqliteClarificationStore",
    "encode_answer",
    "resolve_clarification_store",
]
