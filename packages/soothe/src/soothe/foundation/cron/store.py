"""CronJobStore — Database persistence for cron jobs (RFC-229).

SQLite-backed storage for scheduled jobs with async operations.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from soothe_sdk.paths import SOOTHE_DATA_DIR

from soothe.foundation.cron.models import CronJob, JobStatus, ScheduleKind

logger = logging.getLogger(__name__)


class CronJobStore:
    """SQLite-backed persistence for cron jobs.

    Uses WAL mode for concurrent reads with single writer.
    Async operations prevent event loop blocking.

    Args:
        db_path: Path to SQLite database file. Defaults to $SOOTHE_DATA_DIR/cron.db.
        reader_pool_size: Number of reader connections for concurrent reads.
    """

    def __init__(
        self,
        db_path: str | None = None,
        reader_pool_size: int = 5,
    ) -> None:
        """Initialize CronJobStore.

        Args:
            db_path: Path to SQLite database file. Defaults to $SOOTHE_DATA_DIR/cron.db.
            reader_pool_size: Number of reader connections for concurrent reads.
        """
        self._db_path = db_path or str(Path(SOOTHE_DATA_DIR) / "cron.db")
        self._reader_pool_size = reader_pool_size

        # Writer connection (single writer for consistency)
        self._writer_conn: sqlite3.Connection | None = None

        # Reader pool (multiple readers for concurrent reads)
        self._reader_pool: list[sqlite3.Connection] = []
        self._pool_semaphore = asyncio.Semaphore(reader_pool_size)

        # Async locks
        self._init_lock = asyncio.Lock()
        self._writer_lock = asyncio.Lock()

        logger.info(
            "CronJobStore initialized: path=%s pool_size=%d",
            self._db_path,
            reader_pool_size,
        )

    async def _ensure_writer_connection(self) -> sqlite3.Connection:
        """Lazy writer connection initialization with WAL mode.

        Returns:
            Active SQLite writer connection.
        """
        if self._writer_conn is not None:
            return self._writer_conn

        async with self._init_lock:
            if self._writer_conn is not None:
                return self._writer_conn

            await asyncio.to_thread(self._init_writer_connection)
            return self._writer_conn

    def _init_writer_connection(self) -> None:
        """Sync writer initialization executed in thread pool."""
        db_path = Path(self._db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._writer_conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            timeout=30,
        )
        self._writer_conn.execute("PRAGMA journal_mode=WAL")
        self._writer_conn.execute("PRAGMA foreign_keys=ON")
        self._writer_conn.row_factory = sqlite3.Row
        self._create_table_sync(self._writer_conn)
        logger.info("CronJobStore writer connection initialized at %s", self._db_path)

    async def _get_reader_connection(self) -> sqlite3.Connection:
        """Get reader connection from pool.

        Returns:
            Reader connection from pool.
        """
        async with self._init_lock:
            if not self._reader_pool:
                await asyncio.to_thread(self._init_reader_pool)

            return (
                self._reader_pool.pop() if self._reader_pool else await self._create_reader_conn()
            )

    def _init_reader_pool(self) -> None:
        """Sync reader pool initialization."""
        db_path = Path(self._db_path)
        for _ in range(self._reader_pool_size):
            conn = sqlite3.connect(
                str(db_path),
                check_same_thread=False,
                timeout=30,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._reader_pool.append(conn)
        logger.info("CronJobStore reader pool initialized: size=%d", self._reader_pool_size)

    async def _create_reader_conn(self) -> sqlite3.Connection:
        """Create new reader connection if pool empty."""
        return await asyncio.to_thread(self._create_reader_conn_sync)

    def _create_reader_conn_sync(self) -> sqlite3.Connection:
        """Sync reader connection creation."""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _create_table_sync(self, conn: sqlite3.Connection) -> None:
        """Create cron_jobs table if it does not exist (sync)."""
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
            "CREATE INDEX IF NOT EXISTS idx_cron_jobs_next_run ON cron_jobs(next_run) WHERE status = 'pending'"
        )
        conn.commit()

    async def create(self, job: CronJob) -> CronJob:
        """Insert new job, return with timestamps set.

        Args:
            job: CronJob to create (id must be set).

        Returns:
            The created CronJob with timestamps.
        """
        async with self._writer_lock:
            conn = await self._ensure_writer_connection()
            now = datetime.now(tz=UTC)
            job.created_at = now
            job.updated_at = now

            await asyncio.to_thread(
                self._create_sync,
                conn,
                job.to_dict(),
            )
            logger.info("Created cron job: id=%s user=%s", job.id, job.user_id)
            return job

    def _create_sync(self, conn: sqlite3.Connection, data: dict[str, Any]) -> None:
        """Sync create operation."""
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
        """Get job by ID.

        Args:
            job_id: Job identifier.

        Returns:
            CronJob if found, None otherwise.
        """
        await self._ensure_writer_connection()

        async with self._pool_semaphore:
            conn = await self._get_reader_connection()
            row = await asyncio.to_thread(self._get_sync, conn, job_id)

            async with self._init_lock:
                self._reader_pool.append(conn)

            if row is None:
                return None
            return self._row_to_job(row)

    def _get_sync(self, conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
        """Sync get operation."""
        return conn.execute(
            "SELECT * FROM cron_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()

    async def list_by_user(
        self,
        user_id: str,
        status: JobStatus | str | None = None,
    ) -> list[CronJob]:
        """List jobs for user, optionally filtered by status.

        Args:
            user_id: User identifier.
            status: Optional status filter.

        Returns:
            List of CronJob objects.
        """
        await self._ensure_writer_connection()

        async with self._pool_semaphore:
            conn = await self._get_reader_connection()
            rows = await asyncio.to_thread(
                self._list_by_user_sync,
                conn,
                user_id,
                status.value if isinstance(status, JobStatus) else status,
            )

            async with self._init_lock:
                self._reader_pool.append(conn)

            return [self._row_to_job(row) for row in rows]

    async def list_pending(self) -> list[CronJob]:
        """List all pending cron jobs across users.

        Returns:
            Pending CronJob objects ordered by next_run.
        """
        await self._ensure_writer_connection()

        async with self._pool_semaphore:
            conn = await self._get_reader_connection()
            rows = await asyncio.to_thread(
                self._list_pending_sync,
                conn,
            )

            async with self._init_lock:
                self._reader_pool.append(conn)

            return [self._row_to_job(row) for row in rows]

    def _list_pending_sync(self, conn: sqlite3.Connection) -> list[sqlite3.Row]:
        """Sync list all pending jobs."""
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
        """Find an active job with the same task and schedule for this user.

        Args:
            user_id: Owner user identifier.
            description: Task description (normalized before compare).
            schedule_kind: Schedule kind.
            schedule_value: Schedule value.

        Returns:
            Matching CronJob if one exists with status pending/running, else None.
        """
        from soothe.foundation.cron.models import cron_descriptions_equivalent

        kind_val = schedule_kind.value if isinstance(schedule_kind, ScheduleKind) else schedule_kind
        await self._ensure_writer_connection()

        async with self._pool_semaphore:
            conn = await self._get_reader_connection()
            rows = await asyncio.to_thread(
                self._find_active_by_schedule_sync,
                conn,
                user_id,
                kind_val,
                schedule_value,
            )

            async with self._init_lock:
                self._reader_pool.append(conn)

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
        """Sync lookup for active jobs sharing schedule kind/value."""
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
        """Sync list operation."""
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
        """Update job status.

        Args:
            job_id: Job identifier.
            status: New status.
            last_run: Optional last_run timestamp.

        Returns:
            True if updated, False if not found.
        """
        async with self._writer_lock:
            conn = await self._ensure_writer_connection()
            now = datetime.now(tz=UTC).isoformat()
            status_val = status.value if isinstance(status, JobStatus) else status
            last_run_val = last_run.isoformat() if last_run else None

            result = await asyncio.to_thread(
                self._update_status_sync,
                conn,
                job_id,
                status_val,
                now,
                last_run_val,
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
        """Sync status update operation."""
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
        conn.commit()
        return conn.execute("SELECT changes()").fetchone()[0] > 0

    async def update_next_run(
        self,
        job_id: str,
        next_run: datetime,
        run_count: int,
    ) -> bool:
        """Update next_run for recurring jobs.

        Args:
            job_id: Job identifier.
            next_run: New next run time.
            run_count: New run count.

        Returns:
            True if updated, False if not found.
        """
        async with self._writer_lock:
            conn = await self._ensure_writer_connection()
            now = datetime.now(tz=UTC).isoformat()
            next_run_val = next_run.isoformat()

            result = await asyncio.to_thread(
                self._update_next_run_sync,
                conn,
                job_id,
                next_run_val,
                run_count,
                now,
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
        """Sync next_run update operation."""
        conn.execute(
            """
            UPDATE cron_jobs
            SET next_run = ?, run_count = ?, status = 'pending', updated_at = ?
            WHERE id = ?
            """,
            (next_run, run_count, updated_at, job_id),
        )
        conn.commit()
        return conn.execute("SELECT changes()").fetchone()[0] > 0

    async def get_due_jobs(self, now: datetime | None = None) -> list[CronJob]:
        """Get pending jobs where next_run <= now.

        Args:
            now: Reference time. Defaults to current time.

        Returns:
            List of due CronJob objects.
        """
        now = now or datetime.now(tz=UTC)
        await self._ensure_writer_connection()

        async with self._pool_semaphore:
            conn = await self._get_reader_connection()
            rows = await asyncio.to_thread(
                self._get_due_jobs_sync,
                conn,
                now.isoformat(),
            )

            async with self._init_lock:
                self._reader_pool.append(conn)

            return [self._row_to_job(row) for row in rows]

    def _get_due_jobs_sync(
        self,
        conn: sqlite3.Connection,
        now_iso: str,
    ) -> list[sqlite3.Row]:
        """Sync get due jobs operation."""
        return conn.execute(
            """
            SELECT * FROM cron_jobs
            WHERE status = 'pending' AND next_run <= ?
            ORDER BY next_run
            """,
            (now_iso,),
        ).fetchall()

    async def delete(self, job_id: str) -> bool:
        """Delete a job (used for cleanup, not cancellation).

        Args:
            job_id: Job identifier.

        Returns:
            True if deleted, False if not found.
        """
        async with self._writer_lock:
            conn = await self._ensure_writer_connection()
            result = await asyncio.to_thread(self._delete_sync, conn, job_id)
            if result:
                logger.info("Deleted cron job: id=%s", job_id)
            return result

    def _delete_sync(self, conn: sqlite3.Connection, job_id: str) -> bool:
        """Sync delete operation."""
        conn.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
        conn.commit()
        return conn.execute("SELECT changes()").fetchone()[0] > 0

    async def count_by_user(self, user_id: str) -> int:
        """Count jobs for a user.

        Args:
            user_id: User identifier.

        Returns:
            Number of jobs for this user.
        """
        await self._ensure_writer_connection()

        async with self._pool_semaphore:
            conn = await self._get_reader_connection()
            count = await asyncio.to_thread(self._count_by_user_sync, conn, user_id)

            async with self._init_lock:
                self._reader_pool.append(conn)

            return count

    def _count_by_user_sync(self, conn: sqlite3.Connection, user_id: str) -> int:
        """Sync count operation."""
        row = conn.execute(
            "SELECT COUNT(*) FROM cron_jobs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row[0] if row else 0

    def _row_to_job(self, row: sqlite3.Row) -> CronJob:
        """Convert sqlite3.Row to CronJob.

        Args:
            row: Database row.

        Returns:
            CronJob instance.
        """
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
        """Close all database connections."""
        async with self._init_lock:
            if self._writer_conn:
                await asyncio.to_thread(self._writer_conn.close)
                self._writer_conn = None

            for conn in self._reader_pool:
                await asyncio.to_thread(conn.close)
            self._reader_pool.clear()

        logger.info("CronJobStore connections closed")
