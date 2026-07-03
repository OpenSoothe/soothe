"""Unit tests for CronService orchestrator (RFC-229)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.cron.extraction import AutopilotDisabledError
from soothe.foundation.cron.models import (
    DEFAULT_CRON_USER_ID,
    CronJob,
    DuplicateCronJobError,
    ExtractionResult,
    JobStatus,
    ScheduleKind,
)
from soothe.foundation.cron.service import CronService
from soothe.foundation.cron.store import CronJobStore


def _mock_config(*, max_jobs: int = 100, poll_interval: int = 60) -> MagicMock:
    cfg = MagicMock()
    cfg.agent.autopilot.enabled = True
    cfg.cron.max_jobs = max_jobs
    cfg.cron.poll_interval = poll_interval
    cfg.cron.extraction_model = "fast"
    cfg.cron.extraction_timeout = 30
    cfg.cron.default_priority = 50
    return cfg


def _extraction(
    description: str = "check deploy",
    *,
    kind: ScheduleKind = ScheduleKind.DELAY,
    value: str = "1h",
) -> ExtractionResult:
    return ExtractionResult(
        description=description,
        schedule_kind=kind,
        schedule_value=value,
        confidence=0.9,
        raw_input="test",
    )


@pytest.fixture
def temp_store(tmp_path) -> CronJobStore:
    return CronJobStore(db_path=str(tmp_path / "cron.db"), reader_pool_size=1)


@pytest.mark.asyncio
async def test_add_job_rejects_when_autopilot_disabled(temp_store: CronJobStore) -> None:
    """Pending jobs must not be created when autopilot scheduling is disabled."""
    svc = CronService(config=_mock_config(), store=temp_store)
    svc._config.agent.autopilot.enabled = False
    svc._extraction_service.extract = AsyncMock(return_value=_extraction())

    with pytest.raises(AutopilotDisabledError, match="Autopilot is disabled"):
        await svc.add_job("in 1 hour check deploy", DEFAULT_CRON_USER_ID)

    assert await svc.list_jobs(DEFAULT_CRON_USER_ID) == []
    svc._extraction_service.extract.assert_not_awaited()
    await svc.stop()


@pytest.mark.asyncio
async def test_add_job_persists(temp_store: CronJobStore) -> None:
    svc = CronService(config=_mock_config(), store=temp_store)
    svc._extraction_service.extract = AsyncMock(return_value=_extraction())

    job = await svc.add_job("in 1 hour check deploy", DEFAULT_CRON_USER_ID)

    assert job.user_id == DEFAULT_CRON_USER_ID
    assert job.status == JobStatus.PENDING
    assert job.description == "check deploy"
    listed = await svc.list_jobs(DEFAULT_CRON_USER_ID)
    assert len(listed) == 1
    assert listed[0].id == job.id
    await svc.stop()


@pytest.mark.asyncio
async def test_add_job_respects_max_jobs(temp_store: CronJobStore) -> None:
    svc = CronService(config=_mock_config(max_jobs=1), store=temp_store)
    svc._extraction_service.extract = AsyncMock(return_value=_extraction())

    await svc.add_job("in 1 hour first", DEFAULT_CRON_USER_ID)
    with pytest.raises(ValueError, match="Maximum scheduled jobs"):
        await svc.add_job("in 1 hour second", DEFAULT_CRON_USER_ID)
    await svc.stop()


@pytest.mark.asyncio
async def test_add_job_rejects_near_duplicate_description(temp_store: CronJobStore) -> None:
    svc = CronService(config=_mock_config(), store=temp_store)
    extraction_full = _extraction(
        "polish packages folder to cleanse dead code package by package and module by module",
        kind=ScheduleKind.CRON,
        value="0 3 * * *",
    )
    extraction_short = _extraction(
        "polish packages folder to cleanse dead code package by package",
        kind=ScheduleKind.CRON,
        value="0 3 * * *",
    )
    svc._extraction_service.extract = AsyncMock(return_value=extraction_full)

    first = await svc.add_job("every day at 3am polish packages", DEFAULT_CRON_USER_ID)
    svc._extraction_service.extract = AsyncMock(return_value=extraction_short)

    with pytest.raises(DuplicateCronJobError) as exc_info:
        await svc.add_job("daily at 3am polish packages short wording", DEFAULT_CRON_USER_ID)

    assert exc_info.value.existing_job.id == first.id
    await svc.stop()


@pytest.mark.asyncio
async def test_add_job_rejects_duplicate_active_job(temp_store: CronJobStore) -> None:
    svc = CronService(config=_mock_config(), store=temp_store)
    svc._extraction_service.extract = AsyncMock(
        return_value=_extraction(
            "polish packages folder to cleanse dead code",
            kind=ScheduleKind.CRON,
            value="0 3 * * *",
        )
    )

    first = await svc.add_job(
        "every day at 3am polish packages folder to cleanse dead code",
        DEFAULT_CRON_USER_ID,
    )
    assert first.id

    with pytest.raises(DuplicateCronJobError) as exc_info:
        await svc.add_job(
            "At 3am every day polish packages folder to cleanse dead code",
            DEFAULT_CRON_USER_ID,
        )

    assert exc_info.value.existing_job.id == first.id
    assert len(await svc.list_jobs(DEFAULT_CRON_USER_ID)) == 1
    await svc.stop()


@pytest.mark.asyncio
async def test_add_job_allows_resubmit_after_cancel(temp_store: CronJobStore) -> None:
    svc = CronService(config=_mock_config(), store=temp_store)
    svc._extraction_service.extract = AsyncMock(return_value=_extraction())

    job = await svc.add_job("in 1 hour check deploy", DEFAULT_CRON_USER_ID)
    await svc.cancel_job(job.id, DEFAULT_CRON_USER_ID)

    second = await svc.add_job("in 1 hour check deploy", DEFAULT_CRON_USER_ID)
    assert second.id != job.id
    assert len(await svc.list_jobs(DEFAULT_CRON_USER_ID, status=JobStatus.PENDING)) == 1
    await svc.stop()


@pytest.mark.asyncio
async def test_cancel_job_pending_only(temp_store: CronJobStore) -> None:
    svc = CronService(config=_mock_config(), store=temp_store)
    svc._extraction_service.extract = AsyncMock(return_value=_extraction())
    job = await svc.add_job("in 1 hour task", DEFAULT_CRON_USER_ID)

    assert await svc.cancel_job(job.id, DEFAULT_CRON_USER_ID) is True
    cancelled = await svc.show_job(job.id, DEFAULT_CRON_USER_ID)
    assert cancelled is not None
    assert cancelled.status == JobStatus.CANCELLED

    assert await svc.cancel_job(job.id, DEFAULT_CRON_USER_ID) is False
    assert await svc.cancel_job(job.id, "other-user") is False
    await svc.stop()


@pytest.mark.asyncio
async def test_tick_dispatches_due_job_to_autopilot(temp_store: CronJobStore) -> None:
    autopilot = MagicMock()
    goal = MagicMock(id="goal-abc")
    autopilot.submit_task = AsyncMock(return_value=goal)

    svc = CronService(config=_mock_config(), store=temp_store, autopilot=autopilot)
    due_job = CronJob(
        id="due001",
        user_id=DEFAULT_CRON_USER_ID,
        description="run nightly backup",
        schedule_kind=ScheduleKind.DELAY,
        schedule_value="1m",
        status=JobStatus.PENDING,
        next_run=datetime.now(tz=UTC) - timedelta(minutes=1),
    )
    await temp_store.create(due_job)

    await svc._tick()

    autopilot.submit_task.assert_awaited_once_with(
        "run nightly backup",
        priority=50,
        cron_job_id="due001",  # RFC-229: Link goal to cron job for rescheduling
    )
    updated = await temp_store.get("due001")
    assert updated is not None
    assert updated.status == JobStatus.COMPLETED
    await svc.stop()


@pytest.mark.asyncio
async def test_show_job_ownership(temp_store: CronJobStore) -> None:
    svc = CronService(config=_mock_config(), store=temp_store)
    job = CronJob(
        id="own001",
        user_id=DEFAULT_CRON_USER_ID,
        description="private task",
        schedule_kind=ScheduleKind.DELAY,
        schedule_value="2h",
    )
    await temp_store.create(job)

    assert (await svc.show_job("own001", DEFAULT_CRON_USER_ID)) is not None
    assert await svc.show_job("own001", "other-user") is None
    await svc.stop()
