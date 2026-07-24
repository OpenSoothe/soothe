"""CronJobStore — Database persistence for cron jobs (RFC-229).

SQLite-backed storage via process-scoped ``SqliteStoreRuntime`` (IG-647).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from typing import Any

from soothe_sdk.paths import resolve_cron_db_path

from soothe.cron.models import CronJob, JobStatus, ScheduleKind

logger = logging.getLogger(__name__)


class CronJobStore:
    """SQLite-backed persistence for cron jobs via ``SqliteStoreRuntime``.

    Args:
        db_path: Path to SQLite database file. Defaults to ``$SOOTHE_DATA_DIR/databases/cron.db``.
        reader_pool_size: Reader pool size for the Runtime.
    """

    def __init__(
        self,
        db_path: str | None = None,
        reader_pool_size: int = 5,
    ) -> None:
        from soothe_nano.config.models import SqliteRuntimeConfig
        from soothe_nano.persistence.sqlite_runtime import SqliteRuntimeRegistry

        self._db_path = db_path or str(resolve_cron_db_path())
        self._runtime = SqliteRuntimeRegistry.acquire(
            self._db_path,
            SqliteRuntimeConfig(reader_pool_size=reader_pool_size),
        )
        self._runtime.run_write_sync(self._create_table_sync)
        logger.info(
            "CronJobStore initialized: path=%s pool_size=%d",
            self._db_path,
            reader_pool_size,
        )

    def _create_table_sync(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
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
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cron_jobs_user_status ON cron_jobs(user_id, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cron_jobs_next_run "
            "ON cron_jobs(next_run) WHERE status = 'pending'"
        )

    async def create(self, job: CronJob) -> CronJob:
        """Insert new job, return with timestamps set."""
        now = datetime.now(tz=UTC)
        job.created_at = now
        job.updated_at = now
        data = job.to_dict()
        await self._runtime.run_write(lambda conn: self._create_sync(conn, data))
        logger.info("Created cron job: id=%s user=%s", job.id, job.user_id)
        return job

    def _create_sync(self, conn: sqlite3.Connection, data: dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT INTO cron_jobs (
                id, user_id, description, schedule_kind, schedule_value,
                end_condition, priority, status, next_run, last_run,
                run_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["id"],
                data["user_id"],
                data["description"],
                data["schedule_kind"],
                data["schedule_value"],
                data.get("end_condition"),
                data.get("priority", 50),
                data.get("status", "pending"),
                data["next_run"],
                data.get("last_run"),
                data.get("run_count", 0),
                data["created_at"],
                data["updated_at"],
            ),
        )

    async def get(self, job_id: str) -> CronJob | None:
        """Get job by ID."""

        def _read(conn: sqlite3.Connection) -> CronJob | None:
            row = conn.execute("SELECT * FROM cron_jobs WHERE id = ?", (job_id,)).fetchone()
            return self._row_to_job(row) if row else None

        return await self._runtime.run_read(_read)

    async def list_by_user(
        self,
        user_id: str,
        status: JobStatus | str | None = None,
    ) -> list[CronJob]:
        """List jobs for a user, optionally filtered by status."""
        status_val = status.value if isinstance(status, JobStatus) else status

        def _read(conn: sqlite3.Connection) -> list[CronJob]:
            rows = self._list_by_user_sync(conn, user_id, status_val)
            return [self._row_to_job(row) for row in rows]

        return await self._runtime.run_read(_read)

    async def list_pending(self) -> list[CronJob]:
        """List all pending jobs ordered by next_run."""

        def _read(conn: sqlite3.Connection) -> list[CronJob]:
            rows = self._list_pending_sync(conn)
            return [self._row_to_job(row) for row in rows]

        return await self._runtime.run_read(_read)

    def _list_pending_sync(self, conn: sqlite3.Connection) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT * FROM cron_jobs WHERE status = 'pending' ORDER BY next_run",
        ).fetchall()

    async def find_active_duplicate(
        self,
        user_id: str,
        *,
        description: str,
        schedule_kind: ScheduleKind | str,
        schedule_value: str,
    ) -> CronJob | None:
        """Find an active job with the same task and schedule for this user."""
        from soothe.cron.models import cron_descriptions_equivalent

        kind_val = schedule_kind.value if isinstance(schedule_kind, ScheduleKind) else schedule_kind

        def _read(conn: sqlite3.Connection) -> list[sqlite3.Row]:
            return self._find_active_by_schedule_sync(conn, user_id, kind_val, schedule_value)

        rows = await self._runtime.run_read(_read)
        for row in rows:
            job = self._row_to_job(row)
            if cron_descriptions_equivalent(job.description, description):
                return job
        return None

    def _find_active_by_schedule_sync(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        schedule_kind: str,
        schedule_value: str,
    ) -> list[sqlite3.Row]:
        return conn.execute(
            """
            SELECT * FROM cron_jobs
            WHERE user_id = ?
              AND schedule_kind = ?
              AND schedule_value = ?
              AND status IN ('pending', 'running')
            ORDER BY created_at
            """,
            (user_id, schedule_kind, schedule_value),
        ).fetchall()

    def _list_by_user_sync(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        status: str | None,
    ) -> list[sqlite3.Row]:
        if status:
            return conn.execute(
                "SELECT * FROM cron_jobs WHERE user_id = ? AND status = ? ORDER BY next_run",
                (user_id, status),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM cron_jobs WHERE user_id = ? ORDER BY next_run",
            (user_id,),
        ).fetchall()

    async def update_status(
        self,
        job_id: str,
        status: JobStatus | str,
        last_run: datetime | None = None,
    ) -> bool:
        """Update job status."""
        now = datetime.now(tz=UTC).isoformat()
        status_val = status.value if isinstance(status, JobStatus) else status
        last_run_val = last_run.isoformat() if last_run else None
        result = await self._runtime.run_write(
            lambda conn: self._update_status_sync(conn, job_id, status_val, now, last_run_val)
        )
        if result:
            logger.info("Updated cron job status: id=%s status=%s", job_id, status_val)
        return result

    def _update_status_sync(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        status: str,
        updated_at: str,
        last_run: str | None,
    ) -> bool:
        if last_run:
            conn.execute(
                """
                UPDATE cron_jobs
                SET status = ?, updated_at = ?, last_run = ?
                WHERE id = ?
                """,
                (status, updated_at, last_run, job_id),
            )
        else:
            conn.execute(
                """
                UPDATE cron_jobs
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, updated_at, job_id),
            )
        return conn.execute("SELECT changes()").fetchone()[0] > 0

    async def update_next_run(
        self,
        job_id: str,
        next_run: datetime,
        run_count: int,
    ) -> bool:
        """Update next_run for recurring jobs."""
        now = datetime.now(tz=UTC).isoformat()
        next_run_val = next_run.isoformat()
        result = await self._runtime.run_write(
            lambda conn: self._update_next_run_sync(conn, job_id, next_run_val, run_count, now)
        )
        if result:
            logger.debug("Updated cron job next_run: id=%s next_run=%s", job_id, next_run_val)
        return result

    def _update_next_run_sync(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        next_run: str,
        run_count: int,
        updated_at: str,
    ) -> bool:
        conn.execute(
            """
            UPDATE cron_jobs
            SET next_run = ?, run_count = ?, status = 'pending', updated_at = ?
            WHERE id = ?
            """,
            (next_run, run_count, updated_at, job_id),
        )
        return conn.execute("SELECT changes()").fetchone()[0] > 0

    async def get_due_jobs(self, now: datetime | None = None) -> list[CronJob]:
        """Get pending jobs where next_run <= now."""
        now = now or datetime.now(tz=UTC)
        now_iso = now.isoformat()

        def _read(conn: sqlite3.Connection) -> list[CronJob]:
            rows = self._get_due_jobs_sync(conn, now_iso)
            return [self._row_to_job(row) for row in rows]

        return await self._runtime.run_read(_read)

    def _get_due_jobs_sync(
        self,
        conn: sqlite3.Connection,
        now_iso: str,
    ) -> list[sqlite3.Row]:
        return conn.execute(
            """
            SELECT * FROM cron_jobs
            WHERE status = 'pending' AND next_run <= ?
            ORDER BY next_run
            """,
            (now_iso,),
        ).fetchall()

    async def delete(self, job_id: str) -> bool:
        """Delete a job (used for cleanup, not cancellation)."""
        result = await self._runtime.run_write(lambda conn: self._delete_sync(conn, job_id))
        if result:
            logger.info("Deleted cron job: id=%s", job_id)
        return result

    def _delete_sync(self, conn: sqlite3.Connection, job_id: str) -> bool:
        conn.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
        return conn.execute("SELECT changes()").fetchone()[0] > 0

    async def count_by_user(self, user_id: str) -> int:
        """Count jobs for a user."""

        def _read(conn: sqlite3.Connection) -> int:
            return self._count_by_user_sync(conn, user_id)

        return await self._runtime.run_read(_read)

    def _count_by_user_sync(self, conn: sqlite3.Connection, user_id: str) -> int:
        row = conn.execute(
            "SELECT COUNT(*) FROM cron_jobs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row[0] if row else 0

    def _row_to_job(self, row: sqlite3.Row) -> CronJob:
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
        """Release the process Runtime reference."""
        from soothe_nano.persistence.sqlite_runtime import SqliteRuntimeRegistry

        await SqliteRuntimeRegistry.release(self._db_path)
        logger.info("CronJobStore Runtime released")
