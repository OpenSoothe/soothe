"""Scheduler Service."""

from datetime import UTC, datetime, timedelta

import pytest

from soothe.cognition.scheduler import (
    ScheduledTask,
    SchedulerService,
    ScheduleSpec,
    _parse_cron_field,
    _parse_duration,
)


class TestScheduledTask:
    """Unit tests for ScheduledTask dataclass."""

    def test_default_values(self) -> None:
        spec = ScheduleSpec(kind="delay", value="1h")
        task = ScheduledTask(id="t1", description="Test task", schedule=spec)
        assert task.priority == 50
        assert task.status == "pending"
        assert task.next_run is not None
        assert isinstance(task.created_at, datetime)

    def test_custom_values(self) -> None:
        spec = ScheduleSpec(kind="delay", value="1h")
        task = ScheduledTask(id="t2", description="Custom", schedule=spec, priority=80)
        assert task.priority == 80


class TestScheduleSpec:
    """Unit tests for ScheduleSpec."""

    def test_delay_kind(self) -> None:
        spec = ScheduleSpec(kind="delay", value="1h")
        now = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)
        result = spec.next_after(now)
        assert result == now + timedelta(hours=1)

    def test_at_kind_future(self) -> None:
        spec = ScheduleSpec(kind="at", value="2026-12-25T09:00:00+00:00")
        now = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)
        result = spec.next_after(now)
        assert result is not None
        assert result.year == 2026
        assert result.month == 12

    def test_at_kind_past(self) -> None:
        spec = ScheduleSpec(kind="at", value="2025-01-01T00:00:00+00:00")
        now = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)
        result = spec.next_after(now)
        assert result is None

    def test_once_kind_future(self) -> None:
        spec = ScheduleSpec(kind="once", value="2027-01-01T00:00:00+00:00")
        now = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)
        result = spec.next_after(now)
        assert result is not None

    def test_once_kind_past(self) -> None:
        spec = ScheduleSpec(kind="once", value="2020-01-01T00:00:00+00:00")
        now = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)
        result = spec.next_after(now)
        assert result is None

    def test_every_kind(self) -> None:
        spec = ScheduleSpec(kind="every", value="1h")
        now = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)
        result = spec.next_after(now)
        assert result is not None
        assert result > now

    def test_cron_kind(self) -> None:
        spec = ScheduleSpec(kind="cron", value="0 9 * * *")
        now = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)
        result = spec.next_after(now)
        assert result is not None
        assert result.hour == 9
        assert result.minute == 0


class TestParseDuration:
    """Unit tests for _parse_duration()."""

    def test_hours(self) -> None:
        assert _parse_duration("2h") == timedelta(hours=2)

    def test_minutes(self) -> None:
        assert _parse_duration("30m") == timedelta(minutes=30)

    def test_days(self) -> None:
        assert _parse_duration("1d") == timedelta(days=1)

    def test_weeks_not_supported_directly(self) -> None:
        with pytest.raises(ValueError):
            _parse_duration("1w")

    def test_combined(self) -> None:
        result = _parse_duration("1h30m")
        assert result == timedelta(hours=1, minutes=30)

    def test_seconds(self) -> None:
        assert _parse_duration("45s") == timedelta(seconds=45)

    def test_invalid_empty(self) -> None:
        with pytest.raises(ValueError):
            _parse_duration("")

    def test_invalid_string(self) -> None:
        with pytest.raises(ValueError):
            _parse_duration("abc")


class TestParseCronField:
    """Unit tests for _parse_cron_field()."""

    def test_wildcard(self) -> None:
        result = _parse_cron_field("*", 0, 59)
        assert result == set(range(60))

    def test_range(self) -> None:
        result = _parse_cron_field("1-5", 0, 59)
        assert result == {1, 2, 3, 4, 5}

    def test_list(self) -> None:
        result = _parse_cron_field("1,3,5", 0, 23)
        assert result == {1, 3, 5}

    def test_step(self) -> None:
        result = _parse_cron_field("*/5", 0, 59)
        assert result == set(range(0, 60, 5))

    def test_single_value(self) -> None:
        result = _parse_cron_field("10", 0, 59)
        assert result == {10}

    def test_invalid_value_out_of_range(self) -> None:
        result = _parse_cron_field("60", 0, 59)
        assert result is None

    def test_invalid_text(self) -> None:
        result = _parse_cron_field("abc", 0, 59)
        assert result is None

    def test_invalid_step(self) -> None:
        result = _parse_cron_field("*/abc", 0, 59)
        assert result is None

    def test_invalid_range(self) -> None:
        result = _parse_cron_field("abc-def", 0, 59)
        assert result is None


class TestSchedulerService:
    """Unit tests for SchedulerService."""

    def setup_method(self) -> None:
        self.scheduler = SchedulerService()

    @pytest.mark.asyncio
    async def test_add_task_delay(self) -> None:
        task = await self.scheduler.add_task(
            "Delayed task", schedule_kind="delay", schedule_value="1h"
        )
        assert task.description == "Delayed task"
        assert task.schedule.kind == "delay"
        assert task.schedule.value == "1h"
        assert task.status == "pending"

    @pytest.mark.asyncio
    async def test_add_task_cron(self) -> None:
        task = await self.scheduler.add_task(
            "Cron task", schedule_kind="cron", schedule_value="0 9 * * *"
        )
        assert task.schedule.kind == "cron"
        assert task.next_run is not None

    @pytest.mark.asyncio
    async def test_add_task_custom_id(self) -> None:
        task = await self.scheduler.add_task(
            "Named task", schedule_kind="delay", schedule_value="30m", task_id="my-id"
        )
        assert task.id == "my-id"

    @pytest.mark.asyncio
    async def test_add_task_custom_priority(self) -> None:
        task = await self.scheduler.add_task(
            "Important", schedule_kind="delay", schedule_value="10m", priority=90
        )
        assert task.priority == 90

    @pytest.mark.asyncio
    async def test_get_due_tasks_returns_due(self) -> None:
        await self.scheduler.add_task("Task A", schedule_kind="delay", schedule_value="1m")
        await self.scheduler.add_task("Task B", schedule_kind="delay", schedule_value="10m")
        future = datetime.now(tz=UTC) + timedelta(hours=1)
        due = self.scheduler.get_due_tasks(now=future)
        assert len(due) == 2

    @pytest.mark.asyncio
    async def test_get_due_tasks_excludes_future(self) -> None:
        await self.scheduler.add_task("Future task", schedule_kind="delay", schedule_value="1d")
        past = datetime.now(tz=UTC) - timedelta(hours=1)
        due = self.scheduler.get_due_tasks(now=past)
        assert len(due) == 0

    @pytest.mark.asyncio
    async def test_get_due_tasks_excludes_non_pending(self) -> None:
        await self.scheduler.add_task("Task", schedule_kind="delay", schedule_value="1m")
        for t in self.scheduler._tasks.values():
            t.status = "completed"
        future = datetime.now(tz=UTC) + timedelta(hours=1)
        due = self.scheduler.get_due_tasks(now=future)
        assert len(due) == 0

    @pytest.mark.asyncio
    async def test_get_due_tasks_ordered_by_next_run(self) -> None:
        await self.scheduler.add_task("Later", schedule_kind="delay", schedule_value="2h")
        await self.scheduler.add_task("Sooner", schedule_kind="delay", schedule_value="10m")
        future = datetime.now(tz=UTC) + timedelta(hours=3)
        due = self.scheduler.get_due_tasks(now=future)
        assert len(due) == 2
        assert due[0].description == "Sooner"
        assert due[1].description == "Later"

    @pytest.mark.asyncio
    async def test_mark_running(self) -> None:
        task = await self.scheduler.add_task("Run me", schedule_kind="delay", schedule_value="1m")
        self.scheduler.mark_running(task.id)
        assert task.status == "running"

    def test_mark_running_nonexistent(self) -> None:
        self.scheduler.mark_running("nonexistent")

    @pytest.mark.asyncio
    async def test_mark_completed(self) -> None:
        task = await self.scheduler.add_task("Done", schedule_kind="delay", schedule_value="1m")
        self.scheduler.mark_completed(task.id)
        assert task.status == "completed"

    def test_mark_completed_nonexistent(self) -> None:
        self.scheduler.mark_completed("nonexistent")

    @pytest.mark.asyncio
    async def test_schedule_next_recurring(self) -> None:
        task = await self.scheduler.add_task(
            "Recurring", schedule_kind="every", schedule_value="1h"
        )
        self.scheduler.mark_running(task.id)
        self.scheduler.schedule_next(task.id)
        assert task.status == "pending"
        assert task.next_run is not None

    @pytest.mark.asyncio
    async def test_schedule_next_one_shot(self) -> None:
        task = await self.scheduler.add_task(
            "One-shot", schedule_kind="once", schedule_value="2020-01-01T00:00:00+00:00"
        )
        task.next_run = datetime(2020, 1, 1, tzinfo=UTC)
        self.scheduler.mark_running(task.id)
        self.scheduler.schedule_next(task.id)
        assert task.status == "completed"

    def test_schedule_next_nonexistent(self) -> None:
        self.scheduler.schedule_next("nonexistent")

    @pytest.mark.asyncio
    async def test_cancel_task(self) -> None:
        task = await self.scheduler.add_task(
            "Cancel me", schedule_kind="delay", schedule_value="1h"
        )
        result = self.scheduler.cancel_task(task.id)
        assert result is True
        assert task.status == "cancelled"

    def test_cancel_task_nonexistent(self) -> None:
        result = self.scheduler.cancel_task("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_list_tasks(self) -> None:
        await self.scheduler.add_task("Task A", schedule_kind="delay", schedule_value="1h")
        await self.scheduler.add_task("Task B", schedule_kind="cron", schedule_value="0 9 * * *")
        tasks = self.scheduler.list_tasks()
        assert len(tasks) == 2
        for t in tasks:
            assert "id" in t
            assert "description" in t
            assert "schedule_kind" in t
            assert "schedule_value" in t
            assert "priority" in t
            assert "status" in t
            assert "next_run" in t


class TestSchedulerPersistence:
    """Unit tests for scheduler persistence."""

    @pytest.mark.asyncio
    async def test_save_and_load_survives_restart(self, tmp_path) -> None:
        persist_file = tmp_path / "scheduler.json"
        scheduler1 = SchedulerService(persist_path=str(persist_file))
        await scheduler1.add_task(
            "Persist me", schedule_kind="delay", schedule_value="2h", task_id="p1"
        )
        await scheduler1.add_task(
            "Another", schedule_kind="cron", schedule_value="0 9 * * *", task_id="p2"
        )

        scheduler2 = SchedulerService(persist_path=str(persist_file))
        tasks = scheduler2.list_tasks()
        assert len(tasks) == 2
        ids = {t["id"] for t in tasks}
        assert "p1" in ids
        assert "p2" in ids

    @pytest.mark.asyncio
    async def test_no_persist_path(self) -> None:
        scheduler = SchedulerService(persist_path=None)
        await scheduler.add_task("No persist", schedule_kind="delay", schedule_value="1h")
        assert len(scheduler.list_tasks()) == 1

    def test_missing_persist_file(self, tmp_path) -> None:
        missing = tmp_path / "nonexistent.json"
        scheduler = SchedulerService(persist_path=str(missing))
        assert len(scheduler.list_tasks()) == 0


class TestSameCronConflict:
    """Test multiple tasks with the same cron expression."""

    @pytest.mark.asyncio
    async def test_multiple_tasks_same_cron(self) -> None:
        scheduler = SchedulerService()
        t1 = await scheduler.add_task("Cron A", schedule_kind="cron", schedule_value="0 9 * * *")
        t2 = await scheduler.add_task("Cron B", schedule_kind="cron", schedule_value="0 9 * * *")
        assert t1.next_run is not None
        assert t2.next_run is not None
        assert t1.next_run == t2.next_run
        future = datetime.now(tz=UTC) + timedelta(days=365)
        due = scheduler.get_due_tasks(now=future)
        assert len(due) == 2
