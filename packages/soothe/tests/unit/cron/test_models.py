"""Unit tests for cron models (RFC-229)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from soothe.foundation.cron.models import (
    DEFAULT_CRON_USER_ID,
    CronJob,
    ExtractionResult,
    JobStatus,
    ScheduleKind,
)


class TestDefaultCronUserId:
    """Basic-mode owner id shared by HTTP REST and RPC."""

    def test_default_user_id(self) -> None:
        assert DEFAULT_CRON_USER_ID == "http_api"


class TestScheduleKind:
    """Tests for ScheduleKind enum."""

    def test_all_values_defined(self) -> None:
        """All schedule kinds are defined."""
        assert ScheduleKind.ONCE == "once"
        assert ScheduleKind.DELAY == "delay"
        assert ScheduleKind.AT == "at"
        assert ScheduleKind.EVERY == "every"
        assert ScheduleKind.CRON == "cron"


class TestJobStatus:
    """Tests for JobStatus enum."""

    def test_all_values_defined(self) -> None:
        """All job statuses are defined."""
        assert JobStatus.PENDING == "pending"
        assert JobStatus.RUNNING == "running"
        assert JobStatus.COMPLETED == "completed"
        assert JobStatus.FAILED == "failed"
        assert JobStatus.CANCELLED == "cancelled"


class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""

    def test_basic_creation(self) -> None:
        """Create extraction result with required fields."""
        result = ExtractionResult(
            description="Check the deploy",
            schedule_kind=ScheduleKind.AT,
            schedule_value="2026-06-25T09:00:00",
        )
        assert result.description == "Check the deploy"
        assert result.schedule_kind == ScheduleKind.AT
        assert result.end_condition is None
        assert result.confidence == 0.0

    def test_is_valid_above_threshold(self) -> None:
        """High confidence is valid."""
        result = ExtractionResult(
            description="Test",
            schedule_kind=ScheduleKind.DELAY,
            schedule_value="2h",
            confidence=0.8,
        )
        assert result.is_valid(0.5) is True

    def test_is_valid_below_threshold(self) -> None:
        """Low confidence is invalid."""
        result = ExtractionResult(
            description="Test",
            schedule_kind=ScheduleKind.DELAY,
            schedule_value="2h",
            confidence=0.3,
        )
        assert result.is_valid(0.5) is False

    def test_to_dict(self) -> None:
        """Convert to dictionary."""
        result = ExtractionResult(
            description="Check deploy",
            schedule_kind=ScheduleKind.EVERY,
            schedule_value="1h",
            end_condition="for 2 weeks",
            confidence=0.9,
            raw_input="remind me every hour for 2 weeks to check deploy",
        )
        d = result.to_dict()
        assert d["description"] == "Check deploy"
        assert d["schedule_kind"] == "every"
        assert d["end_condition"] == "for 2 weeks"
        assert d["confidence"] == 0.9


class TestCronJob:
    """Tests for CronJob dataclass."""

    def test_basic_creation(self) -> None:
        """Create job with required fields."""
        job = CronJob(
            id="abc123",
            user_id="alice",
            description="Check deploy",
            schedule_kind=ScheduleKind.AT,
            schedule_value="2026-06-25T09:00:00",
        )
        assert job.id == "abc123"
        assert job.user_id == "alice"
        assert job.status == JobStatus.PENDING
        assert job.priority == 50
        assert job.run_count == 0

    def test_is_recurring(self) -> None:
        """Every and cron are recurring."""
        job_every = CronJob(
            id="test",
            user_id="u",
            description="Test",
            schedule_kind=ScheduleKind.EVERY,
            schedule_value="1h",
        )
        job_cron = CronJob(
            id="test",
            user_id="u",
            description="Test",
            schedule_kind=ScheduleKind.CRON,
            schedule_value="0 9 * * *",
        )
        job_once = CronJob(
            id="test",
            user_id="u",
            description="Test",
            schedule_kind=ScheduleKind.ONCE,
            schedule_value="",
        )

        assert job_every.is_recurring() is True
        assert job_cron.is_recurring() is True
        assert job_once.is_recurring() is False

    def test_is_one_shot(self) -> None:
        """Once, delay, at are one-shot."""
        job_once = CronJob(
            id="test",
            user_id="u",
            description="Test",
            schedule_kind=ScheduleKind.ONCE,
            schedule_value="",
        )
        job_delay = CronJob(
            id="test",
            user_id="u",
            description="Test",
            schedule_kind=ScheduleKind.DELAY,
            schedule_value="2h",
        )
        job_every = CronJob(
            id="test",
            user_id="u",
            description="Test",
            schedule_kind=ScheduleKind.EVERY,
            schedule_value="1h",
        )

        assert job_once.is_one_shot() is True
        assert job_delay.is_one_shot() is True
        assert job_every.is_one_shot() is False

    def test_is_due(self) -> None:
        """Job is due when pending and next_run <= now."""
        now = datetime.now(tz=UTC)
        past = now - timedelta(hours=1)
        future = now + timedelta(hours=1)

        job_past = CronJob(
            id="past",
            user_id="u",
            description="Past",
            schedule_kind=ScheduleKind.AT,
            schedule_value="",
            next_run=past,
        )
        job_future = CronJob(
            id="future",
            user_id="u",
            description="Future",
            schedule_kind=ScheduleKind.AT,
            schedule_value="",
            next_run=future,
        )
        job_running = CronJob(
            id="running",
            user_id="u",
            description="Running",
            schedule_kind=ScheduleKind.AT,
            schedule_value="",
            next_run=past,
            status=JobStatus.RUNNING,
        )

        assert job_past.is_due(now) is True
        assert job_future.is_due(now) is False
        assert job_running.is_due(now) is False

    def test_to_dict_and_from_dict(self) -> None:
        """Serialize and deserialize."""
        now = datetime.now(tz=UTC)
        original = CronJob(
            id="test123",
            user_id="alice",
            description="Check deploy",
            schedule_kind=ScheduleKind.EVERY,
            schedule_value="1h",
            end_condition="until 2026-07-01",
            priority=75,
            next_run=now + timedelta(hours=1),
            run_count=3,
        )

        d = original.to_dict()
        restored = CronJob.from_dict(d)

        assert restored.id == original.id
        assert restored.user_id == original.user_id
        assert restored.description == original.description
        assert restored.schedule_kind == original.schedule_kind
        assert restored.schedule_value == original.schedule_value
        assert restored.end_condition == original.end_condition
        assert restored.priority == original.priority
        assert restored.run_count == original.run_count
