"""PostgreSQL CronJobStore (RFC-229) — used when persistence.default_backend=postgresql."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from soothe.foundation.cron.models import CronJob, JobStatus, ScheduleKind

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cron_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    description TEXT NOT NULL,
    schedule_kind TEXT NOT NULL,
    schedule_value TEXT NOT NULL,
    end_condition TEXT,
    priority INTEGER DEFAULT 50,
    status TEXT DEFAULT 'pending',
    next_run TEXT NOT NULL,
    last_run TEXT,
    run_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cron_jobs_user_status ON cron_jobs(user_id, status);
CREATE INDEX IF NOT EXISTS idx_cron_jobs_next_run ON cron_jobs(next_run) WHERE status = 'pending';
"""


class PostgresCronJobStore:
    """PostgreSQL-backed persistence for cron jobs (async API matches CronJobStore)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any | None = None
        self._init_lock = asyncio.Lock()
        self._writer_lock = asyncio.Lock()
        self._schema_ready = False
        logger.info("PostgresCronJobStore initialized: dsn_db=metadata")

    async def _ensure_pool(self) -> Any:
        if self._pool is not None:
            return self._pool
        async with self._init_lock:
            if self._pool is not None:
                return self._pool
            await asyncio.to_thread(self._open_pool_sync)
            return self._pool

    def _open_pool_sync(self) -> None:
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

    async def create(self, job: CronJob) -> CronJob:
        async with self._writer_lock:
            pool = await self._ensure_pool()
            now = datetime.now(tz=UTC)
            job.created_at = now
            job.updated_at = now
            data = job.to_dict()
            await asyncio.to_thread(self._create_sync, pool, data)
            logger.info("Created cron job: id=%s user=%s", job.id, job.user_id)
            return job

    def _create_sync(self, pool: Any, data: dict[str, Any]) -> None:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cron_jobs (
                        id, user_id, description, schedule_kind, schedule_value,
                        end_condition, priority, status, next_run, last_run,
                        run_count, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        data["id"],
                        data["user_id"],
                        data["description"],
                        data["schedule_kind"],
                        data["schedule_value"],
                        data["end_condition"],
                        data["priority"],
                        data["status"],
                        data["next_run"],
                        data["last_run"],
                        data["run_count"],
                        data["created_at"],
                        data["updated_at"],
                    ),
                )
            conn.commit()

    async def get(self, job_id: str) -> CronJob | None:
        pool = await self._ensure_pool()
        row = await asyncio.to_thread(self._get_sync, pool, job_id)
        return self._row_to_job(row) if row else None

    def _get_sync(self, pool: Any, job_id: str) -> dict[str, Any] | None:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM cron_jobs WHERE id = %s", (job_id,))
                return cur.fetchone()

    async def list_by_user(
        self,
        user_id: str,
        status: JobStatus | str | None = None,
    ) -> list[CronJob]:
        pool = await self._ensure_pool()
        status_val = status.value if isinstance(status, JobStatus) else status
        rows = await asyncio.to_thread(self._list_by_user_sync, pool, user_id, status_val)
        return [self._row_to_job(row) for row in rows]

    def _list_by_user_sync(
        self, pool: Any, user_id: str, status: str | None
    ) -> list[dict[str, Any]]:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                if status:
                    cur.execute(
                        "SELECT * FROM cron_jobs WHERE user_id = %s AND status = %s ORDER BY next_run",
                        (user_id, status),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM cron_jobs WHERE user_id = %s ORDER BY next_run",
                        (user_id,),
                    )
                return list(cur.fetchall())

    async def list_pending(self) -> list[CronJob]:
        pool = await self._ensure_pool()
        rows = await asyncio.to_thread(self._list_pending_sync, pool)
        return [self._row_to_job(row) for row in rows]

    def _list_pending_sync(self, pool: Any) -> list[dict[str, Any]]:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM cron_jobs WHERE status = 'pending' ORDER BY next_run",
                )
                return list(cur.fetchall())

    async def find_active_duplicate(
        self,
        user_id: str,
        *,
        description: str,
        schedule_kind: ScheduleKind | str,
        schedule_value: str,
    ) -> CronJob | None:
        from soothe.foundation.cron.models import cron_descriptions_equivalent

        kind_val = schedule_kind.value if isinstance(schedule_kind, ScheduleKind) else schedule_kind
        pool = await self._ensure_pool()
        rows = await asyncio.to_thread(
            self._find_active_by_schedule_sync,
            pool,
            user_id,
            kind_val,
            schedule_value,
        )
        for row in rows:
            job = self._row_to_job(row)
            if cron_descriptions_equivalent(job.description, description):
                return job
        return None

    def _find_active_by_schedule_sync(
        self,
        pool: Any,
        user_id: str,
        schedule_kind: str,
        schedule_value: str,
    ) -> list[dict[str, Any]]:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM cron_jobs
                    WHERE user_id = %s
                      AND schedule_kind = %s
                      AND schedule_value = %s
                      AND status IN ('pending', 'running')
                    ORDER BY created_at
                    """,
                    (user_id, schedule_kind, schedule_value),
                )
                return list(cur.fetchall())

    async def update_status(
        self,
        job_id: str,
        status: JobStatus | str,
        last_run: datetime | None = None,
    ) -> bool:
        async with self._writer_lock:
            pool = await self._ensure_pool()
            now = datetime.now(tz=UTC).isoformat()
            status_val = status.value if isinstance(status, JobStatus) else status
            last_run_val = last_run.isoformat() if last_run else None
            result = await asyncio.to_thread(
                self._update_status_sync, pool, job_id, status_val, now, last_run_val
            )
            if result:
                logger.info("Updated cron job status: id=%s status=%s", job_id, status_val)
            return result

    def _update_status_sync(
        self,
        pool: Any,
        job_id: str,
        status: str,
        updated_at: str,
        last_run: str | None,
    ) -> bool:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                if last_run:
                    cur.execute(
                        """
                        UPDATE cron_jobs
                        SET status = %s, updated_at = %s, last_run = %s
                        WHERE id = %s
                        """,
                        (status, updated_at, last_run, job_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE cron_jobs
                        SET status = %s, updated_at = %s
                        WHERE id = %s
                        """,
                        (status, updated_at, job_id),
                    )
                updated = cur.rowcount > 0
            conn.commit()
            return updated

    async def update_next_run(
        self,
        job_id: str,
        next_run: datetime,
        run_count: int,
    ) -> bool:
        async with self._writer_lock:
            pool = await self._ensure_pool()
            now = datetime.now(tz=UTC).isoformat()
            result = await asyncio.to_thread(
                self._update_next_run_sync,
                pool,
                job_id,
                next_run.isoformat(),
                run_count,
                now,
            )
            if result:
                logger.debug("Updated cron job next_run: id=%s next_run=%s", job_id, next_run)
            return result

    def _update_next_run_sync(
        self,
        pool: Any,
        job_id: str,
        next_run: str,
        run_count: int,
        updated_at: str,
    ) -> bool:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE cron_jobs
                    SET next_run = %s, run_count = %s, status = 'pending', updated_at = %s
                    WHERE id = %s
                    """,
                    (next_run, run_count, updated_at, job_id),
                )
                updated = cur.rowcount > 0
            conn.commit()
            return updated

    async def get_due_jobs(self, now: datetime | None = None) -> list[CronJob]:
        now = now or datetime.now(tz=UTC)
        pool = await self._ensure_pool()
        rows = await asyncio.to_thread(self._get_due_jobs_sync, pool, now.isoformat())
        return [self._row_to_job(row) for row in rows]

    def _get_due_jobs_sync(self, pool: Any, now_iso: str) -> list[dict[str, Any]]:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM cron_jobs
                    WHERE status = 'pending' AND next_run <= %s
                    ORDER BY next_run
                    """,
                    (now_iso,),
                )
                return list(cur.fetchall())

    async def delete(self, job_id: str) -> bool:
        async with self._writer_lock:
            pool = await self._ensure_pool()
            result = await asyncio.to_thread(self._delete_sync, pool, job_id)
            if result:
                logger.info("Deleted cron job: id=%s", job_id)
            return result

    def _delete_sync(self, pool: Any, job_id: str) -> bool:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM cron_jobs WHERE id = %s", (job_id,))
                deleted = cur.rowcount > 0
            conn.commit()
            return deleted

    async def count_by_user(self, user_id: str) -> int:
        pool = await self._ensure_pool()
        return await asyncio.to_thread(self._count_by_user_sync, pool, user_id)

    def _count_by_user_sync(self, pool: Any, user_id: str) -> int:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM cron_jobs WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
                return int(row["c"]) if row else 0

    def _row_to_job(self, row: dict[str, Any]) -> CronJob:
        return CronJob(
            id=row["id"],
            user_id=row["user_id"],
            description=row["description"],
            schedule_kind=ScheduleKind(row["schedule_kind"]),
            schedule_value=row["schedule_value"],
            end_condition=row["end_condition"],
            priority=row["priority"],
            status=JobStatus(row["status"]),
            next_run=datetime.fromisoformat(row["next_run"]),
            last_run=datetime.fromisoformat(row["last_run"]) if row["last_run"] else None,
            run_count=row["run_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    async def close(self) -> None:
        async with self._init_lock:
            pool = self._pool
            self._pool = None
            self._schema_ready = False
        if pool is not None:
            await asyncio.to_thread(pool.close)
        logger.info("PostgresCronJobStore connections closed")


__all__ = ["PostgresCronJobStore"]
