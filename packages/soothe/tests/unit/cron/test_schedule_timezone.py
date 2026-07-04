"""Tests for cron local-time schedule evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from soothe.foundation.autopilot.engine.schedule_timezone import resolve_schedule_timezone
from soothe.foundation.autopilot.engine.scheduled_tasks import ScheduleSpec


def test_cron_uses_local_timezone_not_utc() -> None:
    """Cron wall-clock fields should follow the configured timezone."""
    spec = ScheduleSpec(kind="cron", value="0 3 * * *", timezone="Asia/Shanghai")
    # 2026-07-03 18:00 UTC = 2026-07-04 02:00 CST — next 3am local is later that morning
    after = datetime(2026, 7, 3, 18, 0, 0, tzinfo=UTC)
    result = spec.next_after(after)
    assert result is not None
    local = result.astimezone(ZoneInfo("Asia/Shanghai"))
    assert local.hour == 3
    assert local.minute == 0
    assert local.day == 4
    assert local.month == 7


def test_cron_defaults_to_utc_when_timezone_unset() -> None:
    """SchedulerService callers without timezone keep UTC semantics."""
    spec = ScheduleSpec(kind="cron", value="0 9 * * *")
    after = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)
    result = spec.next_after(after)
    assert result is not None
    assert result.hour == 9
    assert result.minute == 0
    assert result.tzinfo == UTC


def test_at_kind_interprets_naive_datetime_as_local() -> None:
    """Naive at/once datetimes are wall-clock times in the schedule timezone."""
    spec = ScheduleSpec(kind="at", value="2026-07-04T03:00:00", timezone="Asia/Shanghai")
    after = datetime(2026, 7, 3, 12, 0, 0, tzinfo=UTC)
    result = spec.next_after(after)
    assert result == datetime(2026, 7, 3, 19, 0, 0, tzinfo=UTC)


def test_resolve_schedule_timezone_local_and_utc() -> None:
    """Timezone resolver accepts local and UTC sentinels."""
    assert resolve_schedule_timezone("UTC") == UTC
    local = resolve_schedule_timezone("local")
    assert local is not None
    assert resolve_schedule_timezone("Asia/Shanghai").key == "Asia/Shanghai"
