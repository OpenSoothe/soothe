"""Unit tests for built-in cron jobs (RFC-229).

Covers the ``BUILTIN_JOBS`` registry and the weekly historical-data refresh
job for the drift review dashboard. The seeding path is exercised end-to-end
through ``CronService.seed_builtin_jobs()`` to assert idempotency, schedule
resolution, and persistence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from soothe_daemon.cron.builtin import (
    BUILTIN_JOBS,
    WEEKLY_HISTORICAL_DATA_REFRESH,
)
from soothe_daemon.cron.models import (
    DEFAULT_CRON_USER_ID,
    JobStatus,
    ScheduleKind,
)
from soothe_daemon.cron.schedule import ScheduleSpec
from soothe_daemon.cron.service import CronService
from soothe_daemon.cron.store import CronJobStore


def _mock_config(*, max_jobs: int = 100, poll_interval: int = 60) -> MagicMock:
    cfg = MagicMock()
    cfg.agent.autopilot.enabled = True
    cfg.cron.max_jobs = max_jobs
    cfg.cron.poll_interval = poll_interval
    cfg.cron.extraction_model = "fast"
    cfg.cron.extraction_timeout = 30
    cfg.cron.default_priority = 50
    cfg.cron.timezone = "UTC"
    cfg.cron.enable_builtin_jobs = True
    return cfg


@pytest.fixture
def temp_store(tmp_path) -> CronJobStore:
    return CronJobStore(db_path=str(tmp_path / "cron.db"), reader_pool_size=1)


class TestWeeklyHistoricalDataRefreshSpec:
    """Static checks on the weekly historical-data refresh BuiltinJobSpec."""

    def test_registered_in_builtin_jobs(self) -> None:
        """The refresh job must appear in the BUILTIN_JOBS registry."""
        assert WEEKLY_HISTORICAL_DATA_REFRESH in BUILTIN_JOBS
        assert len(BUILTIN_JOBS) >= 1

    def test_job_id_is_stable_and_unique(self) -> None:
        """Stable job_id is required for idempotent seeding."""
        ids = [spec.job_id for spec in BUILTIN_JOBS]
        assert len(ids) == len(set(ids)), "Duplicate job_id in BUILTIN_JOBS"
        assert WEEKLY_HISTORICAL_DATA_REFRESH.job_id == "builtin-weekly-historical-refresh"

    def test_schedule_is_weekly_cron_on_monday(self) -> None:
        """Schedule is a CRON expression firing weekly (Monday at 03:00)."""
        spec = WEEKLY_HISTORICAL_DATA_REFRESH
        assert spec.schedule_kind == ScheduleKind.CRON
        # 5-field cron: minute hour day_of_month month day_of_week
        fields = spec.schedule_value.split()
        assert len(fields) == 5
        assert fields[0] == "0"  # minute 0
        assert fields[1] == "3"  # hour 3 (03:00 local)
        assert fields[2] == "*"  # every day_of_month
        assert fields[3] == "*"  # every month
        assert fields[4] == "1"  # Monday (cron: Sun=0, Mon=1)

    def test_description_is_imperative_and_mentions_drift_review(self) -> None:
        """Description is imperative and references the drift review dashboard."""
        desc = WEEKLY_HISTORICAL_DATA_REFRESH.description
        assert desc and desc[0].isupper(), "Description should start capitalized"
        assert "drift review dashboard" in desc.casefold()

    def test_priority_is_within_range(self) -> None:
        """Priority must be within the documented 1-100 range."""
        assert 1 <= WEEKLY_HISTORICAL_DATA_REFRESH.priority <= 100

    def test_spec_is_frozen(self) -> None:
        """BuiltinJobSpec instances are frozen so they cannot drift at runtime."""
        with pytest.raises(Exception):  # FrozenInstanceError is a subclass
            WEEKLY_HISTORICAL_DATA_REFRESH.priority = 99  # type: ignore[misc]


class TestWeeklyHistoricalDataRefreshSchedule:
    """Schedule math for the weekly historical-data refresh expression."""

    def test_next_run_is_a_monday_at_3am(self) -> None:
        """The next fire after any reference point lands on a Monday at 03:00."""
        spec = ScheduleSpec(
            kind="cron",
            value=WEEKLY_HISTORICAL_DATA_REFRESH.schedule_value,
            timezone="UTC",
        )
        after = datetime(2026, 8, 17, 14, 30, 0, tzinfo=UTC)  # a Monday
        result = spec.next_after(after)
        assert result is not None
        assert result.minute == 0
        assert result.hour == 3
        # cron Mon=1 -> Python weekday() Mon=0
        assert result.weekday() == 0
        assert result > after

    def test_next_run_skips_non_mondays(self) -> None:
        """A reference on a Sunday yields the immediately following Monday."""
        spec = ScheduleSpec(
            kind="cron",
            value=WEEKLY_HISTORICAL_DATA_REFRESH.schedule_value,
            timezone="UTC",
        )
        after = datetime(2026, 8, 16, 18, 0, 0, tzinfo=UTC)  # a Sunday
        result = spec.next_after(after)
        assert result is not None
        assert result.weekday() == 0  # Monday
        assert result.day == 17
        assert result.hour == 3

    def test_next_run_respects_local_timezone(self) -> None:
        """Wall-clock 03:00 is interpreted in the configured timezone."""
        spec = ScheduleSpec(
            kind="cron",
            value=WEEKLY_HISTORICAL_DATA_REFRESH.schedule_value,
            timezone="Asia/Shanghai",
        )
        after = datetime(2026, 8, 16, 18, 0, 0, tzinfo=UTC)
        result = spec.next_after(after)
        assert result is not None
        local = result.astimezone(ZoneInfo("Asia/Shanghai"))
        assert local.hour == 3
        assert local.minute == 0
        assert local.weekday() == 0  # Monday

    def test_weekly_cadence_is_seven_days(self) -> None:
        """Consecutive fires are exactly one week apart (weekly cadence)."""
        spec = ScheduleSpec(
            kind="cron",
            value=WEEKLY_HISTORICAL_DATA_REFRESH.schedule_value,
            timezone="UTC",
        )
        first = spec.next_after(datetime(2026, 8, 17, 14, 30, 0, tzinfo=UTC))
        assert first is not None
        second = spec.next_after(first + timedelta(seconds=1))
        assert second is not None
        assert (second - first) == timedelta(days=7)


@pytest.mark.asyncio
class TestSeedBuiltinJobs:
    """End-to-end seeding of the weekly historical-data refresh job."""

    async def test_seed_creates_weekly_refresh_job(self, temp_store: CronJobStore) -> None:
        """seed_builtin_jobs() persists the weekly refresh job when enabled."""
        svc = CronService(config=_mock_config(), store=temp_store)
        try:
            created = await svc.seed_builtin_jobs()
            assert created == 1

            job = await temp_store.get(WEEKLY_HISTORICAL_DATA_REFRESH.job_id)
            assert job is not None
            assert job.user_id == DEFAULT_CRON_USER_ID
            assert job.description == WEEKLY_HISTORICAL_DATA_REFRESH.description
            assert job.schedule_kind == ScheduleKind.CRON
            assert job.schedule_value == "0 3 * * 1"
            assert job.priority == WEEKLY_HISTORICAL_DATA_REFRESH.priority
            assert job.status == JobStatus.PENDING
            assert job.next_run is not None
        finally:
            await svc.stop()

    async def test_seed_is_idempotent(self, temp_store: CronJobStore) -> None:
        """A second seed pass must not duplicate the weekly refresh job."""
        svc = CronService(config=_mock_config(), store=temp_store)
        try:
            assert await svc.seed_builtin_jobs() == 1
            assert await svc.seed_builtin_jobs() == 0

            listed = await temp_store.list_pending()
            refresh = [j for j in listed if j.id == WEEKLY_HISTORICAL_DATA_REFRESH.job_id]
            assert len(refresh) == 1
        finally:
            await svc.stop()

    async def test_seed_skipped_when_builtin_disabled(self, temp_store: CronJobStore) -> None:
        """When enable_builtin_jobs is false, no job is seeded."""
        cfg = _mock_config()
        cfg.cron.enable_builtin_jobs = False
        svc = CronService(config=cfg, store=temp_store)
        try:
            assert await svc.seed_builtin_jobs() == 0
            assert (await temp_store.get(WEEKLY_HISTORICAL_DATA_REFRESH.job_id)) is None
        finally:
            await svc.stop()

    async def test_seed_uses_configured_timezone(self, temp_store: CronJobStore) -> None:
        """Seeded next_run reflects the cron timezone, not naive UTC."""
        cfg = _mock_config()
        cfg.cron.timezone = "Asia/Shanghai"
        svc = CronService(config=cfg, store=temp_store)
        try:
            await svc.seed_builtin_jobs()
            job = await temp_store.get(WEEKLY_HISTORICAL_DATA_REFRESH.job_id)
            assert job is not None
            local = job.next_run.astimezone(ZoneInfo("Asia/Shanghai"))
            assert local.hour == 3
            assert local.minute == 0
            assert local.weekday() == 0  # Monday
        finally:
            await svc.stop()
