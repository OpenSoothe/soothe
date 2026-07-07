"""Schedule math tests for CronService (ScheduleSpec and helpers)."""

from datetime import UTC, datetime, timedelta

import pytest
from soothe.foundation.autopilot.engine import ScheduleSpec
from soothe.foundation.autopilot.engine.scheduled_tasks import _parse_cron_field, _parse_duration


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
