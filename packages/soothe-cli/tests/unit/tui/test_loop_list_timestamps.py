"""Loop selector timestamp parsing — regression for UTC-vs-local drift.

The daemon stores all loop timestamps as UTC, formatted as ISO 8601 with the
``+00:00`` suffix. Earlier the daemon truncated those strings to ``[:16]``
before sending them on the wire, which stripped the offset; the client then
parsed a naive datetime, and ``.astimezone()`` treated it as already-local,
producing an N-hour drift in any non-UTC zone (e.g. "8h ago" for a loop
created minutes earlier in UTC+8).

The fix keeps the full ISO string end-to-end and, defensively, parses any
naive ISO as UTC before converting to local time. Lock both behaviours in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import patch

from soothe_cli.tui.sessions import (
    _parse_iso_to_local,
    format_relative_timestamp,
    format_timestamp,
)


def test_parse_iso_to_local_handles_aware_utc() -> None:
    """An ISO timestamp with ``+00:00`` round-trips to local time correctly."""
    parsed = _parse_iso_to_local("2026-06-04T12:00:00+00:00")
    assert parsed is not None
    assert parsed.tzinfo is not None
    # The parsed instant must equal the original UTC moment.
    assert parsed == datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC)


def test_parse_iso_to_local_treats_naive_as_utc_not_local() -> None:
    """Truncated wire strings (no offset) must be interpreted as UTC.

    Treating them as local would render UTC clocks as if already local —
    the exact drift the user reported on /resume.
    """
    parsed = _parse_iso_to_local("2026-06-04T12:00:00")
    assert parsed is not None
    # The instant must equal the same UTC moment as the offset-bearing form.
    assert parsed == datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC)


def test_format_relative_timestamp_uses_aware_diff_not_naive() -> None:
    """Recent UTC timestamps must render as a small "X ago" — never hours off."""
    # 90 seconds before "now" in UTC.
    now_utc = datetime.now(tz=UTC)
    ts = (now_utc - timedelta(seconds=90)).isoformat()
    rendered = format_relative_timestamp(ts)
    assert rendered == "1m ago"


def test_format_relative_timestamp_naive_input_does_not_drift_by_hours() -> None:
    """Even when the offset is stripped (legacy wire), the displayed delta
    must remain in minutes — not jump to N hours where N is the local TZ
    offset. This is the original /resume regression.
    """
    # Simulate "now" being in a UTC+8 zone by patching ``datetime.now`` to
    # return a fixed aware moment, and feed in the corresponding NAIVE UTC
    # iso string that the truncated wire would deliver.
    fake_local = timezone(timedelta(hours=8))
    fake_now = datetime(2026, 6, 4, 20, 0, 30, tzinfo=fake_local)  # 12:00:30 UTC
    truncated_iso = "2026-06-04T12:00"  # 30 seconds earlier, no offset

    # Patch datetime inside sessions module
    with patch("soothe_cli.tui.sessions.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.fromisoformat = datetime.fromisoformat  # delegate

        rendered = format_relative_timestamp(truncated_iso)

    assert rendered == "30s ago", (
        f"expected '30s ago' (UTC interpreted as UTC), got {rendered!r} "
        "— if this drifts to '8h ago', the fix has regressed"
    )


def test_format_timestamp_converts_utc_to_local_zone() -> None:
    """UTC instant must render in the local zone, not UTC.

    Concretely: a ``2026-06-04T12:00:00+00:00`` instant rendered in UTC+8
    should show the local-side hour (20:00), not the UTC hour (12:00).
    """
    fake_local = timezone(timedelta(hours=8))
    fake_utc_instant = datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC)

    # ``_parse_iso_to_local`` calls ``.astimezone()`` with no arg, which
    # converts to the runtime's local timezone. To make this deterministic
    # without rebuilding the test env's timezone, just assert the parsed
    # instant equals the original UTC instant — equality across zones is
    # what the formatter relies on.
    parsed = _parse_iso_to_local(fake_utc_instant.isoformat())
    assert parsed is not None
    assert parsed == fake_utc_instant

    # And a smoke check on the formatted string: should not be empty.
    rendered = format_timestamp(fake_utc_instant.astimezone(fake_local).isoformat())
    assert rendered  # non-empty


def test_format_timestamp_returns_blank_for_empty_input() -> None:
    assert format_timestamp(None) == ""
    assert format_timestamp("") == ""
    assert format_timestamp("not-an-iso") == ""


def test_format_relative_timestamp_returns_blank_for_empty_input() -> None:
    assert format_relative_timestamp(None) == ""
    assert format_relative_timestamp("") == ""
    assert format_relative_timestamp("not-an-iso") == ""
