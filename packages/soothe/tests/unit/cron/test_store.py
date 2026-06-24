"""Unit tests for CronJobStore (RFC-229).

Uses SQLite file-based database for tests (in-memory doesn't share between
connections).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, datetime, timedelta

from soothe.foundation.cron.models import CronJob, JobStatus, ScheduleKind
from soothe.foundation.cron.store import CronJobStore


def run_async(coro):
    """Helper to run async tests."""
    return asyncio.run(coro)


class TestCronJobStore:
    """Tests for CronJobStore async operations."""

    def test_create_job(self) -> None:
        """Create a new job."""

        async def _test():
            temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            temp_path = temp_file.name
            temp_file.close()
            store = CronJobStore(db_path=temp_path, reader_pool_size=1)

            job = CronJob(
                id="test001",
                user_id="alice",
                description="Check deploy",
                schedule_kind=ScheduleKind.AT,
                schedule_value="2026-06-25T09:00:00",
            )
            created = await store.create(job)

            assert created.id == job.id
            assert created.created_at is not None
            assert created.updated_at is not None

            await store.close()
            os.unlink(temp_path)

        run_async(_test())

    def test_get_job(self) -> None:
        """Get job by ID."""

        async def _test():
            temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            temp_path = temp_file.name
            temp_file.close()
            store = CronJobStore(db_path=temp_path, reader_pool_size=1)

            job = CronJob(
                id="test002",
                user_id="alice",
                description="Test job",
                schedule_kind=ScheduleKind.DELAY,
                schedule_value="2h",
            )
            await store.create(job)

            retrieved = await store.get("test002")
            assert retrieved is not None
            assert retrieved.id == "test002"
            assert retrieved.description == "Test job"

            await store.close()
            os.unlink(temp_path)

        run_async(_test())

    def test_get_nonexistent_job(self) -> None:
        """Get returns None for nonexistent job."""

        async def _test():
            temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            temp_path = temp_file.name
            temp_file.close()
            store = CronJobStore(db_path=temp_path, reader_pool_size=1)

            retrieved = await store.get("nonexistent")
            assert retrieved is None

            await store.close()
            os.unlink(temp_path)

        run_async(_test())

    def test_list_by_user(self) -> None:
        """List jobs for a specific user."""

        async def _test():
            temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            temp_path = temp_file.name
            temp_file.close()
            store = CronJobStore(db_path=temp_path, reader_pool_size=1)

            # Create jobs for different users
            job1 = CronJob(
                id="alice1",
                user_id="alice",
                description="Alice job 1",
                schedule_kind=ScheduleKind.EVERY,
                schedule_value="1h",
            )
            job2 = CronJob(
                id="alice2",
                user_id="alice",
                description="Alice job 2",
                schedule_kind=ScheduleKind.CRON,
                schedule_value="0 9 * * *",
            )
            job3 = CronJob(
                id="bob1",
                user_id="bob",
                description="Bob job",
                schedule_kind=ScheduleKind.DELAY,
                schedule_value="30m",
            )

            await store.create(job1)
            await store.create(job2)
            await store.create(job3)

            alice_jobs = await store.list_by_user("alice")
            assert len(alice_jobs) == 2
            assert all(j.user_id == "alice" for j in alice_jobs)

            bob_jobs = await store.list_by_user("bob")
            assert len(bob_jobs) == 1

            await store.close()
            os.unlink(temp_path)

        run_async(_test())

    def test_list_by_user_with_status_filter(self) -> None:
        """List jobs filtered by status."""

        async def _test():
            temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            temp_path = temp_file.name
            temp_file.close()
            store = CronJobStore(db_path=temp_path, reader_pool_size=1)

            job1 = CronJob(
                id="pending1",
                user_id="alice",
                description="Pending job",
                schedule_kind=ScheduleKind.EVERY,
                schedule_value="1h",
                status=JobStatus.PENDING,
            )
            job2 = CronJob(
                id="completed1",
                user_id="alice",
                description="Completed job",
                schedule_kind=ScheduleKind.AT,
                schedule_value="2026-06-25T09:00:00",
                status=JobStatus.COMPLETED,
            )

            await store.create(job1)
            await store.create(job2)

            pending_jobs = await store.list_by_user("alice", JobStatus.PENDING)
            assert len(pending_jobs) == 1
            assert pending_jobs[0].status == JobStatus.PENDING

            await store.close()
            os.unlink(temp_path)

        run_async(_test())

    def test_update_status(self) -> None:
        """Update job status."""

        async def _test():
            temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            temp_path = temp_file.name
            temp_file.close()
            store = CronJobStore(db_path=temp_path, reader_pool_size=1)

            job = CronJob(
                id="status1",
                user_id="alice",
                description="Status test",
                schedule_kind=ScheduleKind.DELAY,
                schedule_value="1h",
            )
            await store.create(job)

            result = await store.update_status("status1", JobStatus.RUNNING)
            assert result is True

            updated = await store.get("status1")
            assert updated is not None
            assert updated.status == JobStatus.RUNNING

            await store.close()
            os.unlink(temp_path)

        run_async(_test())

    def test_update_status_nonexistent(self) -> None:
        """Update status returns False for nonexistent job."""

        async def _test():
            temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            temp_path = temp_file.name
            temp_file.close()
            store = CronJobStore(db_path=temp_path, reader_pool_size=1)

            result = await store.update_status("nonexistent", JobStatus.COMPLETED)
            assert result is False

            await store.close()
            os.unlink(temp_path)

        run_async(_test())

    def test_update_next_run(self) -> None:
        """Update next_run for recurring jobs."""

        async def _test():
            temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            temp_path = temp_file.name
            temp_file.close()
            store = CronJobStore(db_path=temp_path, reader_pool_size=1)

            job = CronJob(
                id="recurring1",
                user_id="alice",
                description="Recurring job",
                schedule_kind=ScheduleKind.EVERY,
                schedule_value="1h",
                run_count=0,
            )
            await store.create(job)

            new_next_run = datetime.now(tz=UTC) + timedelta(hours=2)
            result = await store.update_next_run("recurring1", new_next_run, 1)
            assert result is True

            updated = await store.get("recurring1")
            assert updated is not None
            assert updated.run_count == 1
            assert updated.status == JobStatus.PENDING  # Reset to pending

            await store.close()
            os.unlink(temp_path)

        run_async(_test())

    def test_get_due_jobs(self) -> None:
        """Get jobs that are due for execution."""

        async def _test():
            temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            temp_path = temp_file.name
            temp_file.close()
            store = CronJobStore(db_path=temp_path, reader_pool_size=1)

            now = datetime.now(tz=UTC)

            # Due job (next_run in past)
            due_job = CronJob(
                id="due1",
                user_id="alice",
                description="Due job",
                schedule_kind=ScheduleKind.AT,
                schedule_value="",
                next_run=now - timedelta(minutes=30),
            )
            # Not due job (next_run in future)
            not_due_job = CronJob(
                id="notdue1",
                user_id="alice",
                description="Not due job",
                schedule_kind=ScheduleKind.AT,
                schedule_value="",
                next_run=now + timedelta(hours=1),
            )
            # Running job (should not be due)
            running_job = CronJob(
                id="running1",
                user_id="alice",
                description="Running job",
                schedule_kind=ScheduleKind.EVERY,
                schedule_value="1h",
                next_run=now - timedelta(minutes=30),
                status=JobStatus.RUNNING,
            )

            await store.create(due_job)
            await store.create(not_due_job)
            await store.create(running_job)

            due_jobs = await store.get_due_jobs(now)
            assert len(due_jobs) == 1
            assert due_jobs[0].id == "due1"

            await store.close()
            os.unlink(temp_path)

        run_async(_test())

    def test_count_by_user(self) -> None:
        """Count jobs for a user."""

        async def _test():
            temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            temp_path = temp_file.name
            temp_file.close()
            store = CronJobStore(db_path=temp_path, reader_pool_size=1)

            for i in range(5):
                job = CronJob(
                    id=f"count{i}",
                    user_id="alice",
                    description=f"Job {i}",
                    schedule_kind=ScheduleKind.EVERY,
                    schedule_value="1h",
                )
                await store.create(job)

            count = await store.count_by_user("alice")
            assert count == 5

            bob_count = await store.count_by_user("bob")
            assert bob_count == 0

            await store.close()
            os.unlink(temp_path)

        run_async(_test())

    def test_delete_job(self) -> None:
        """Delete a job."""

        async def _test():
            temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            temp_path = temp_file.name
            temp_file.close()
            store = CronJobStore(db_path=temp_path, reader_pool_size=1)

            job = CronJob(
                id="delete1",
                user_id="alice",
                description="Delete test",
                schedule_kind=ScheduleKind.DELAY,
                schedule_value="1h",
            )
            await store.create(job)

            result = await store.delete("delete1")
            assert result is True

            deleted = await store.get("delete1")
            assert deleted is None

            await store.close()
            os.unlink(temp_path)

        run_async(_test())
