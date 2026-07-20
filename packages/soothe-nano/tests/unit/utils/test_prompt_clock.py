"""Tests for local prompt clock helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from soothe_nano.utils.prompt_clock import (
    build_canonical_datetime_reply,
    format_friendly_local_date,
    local_date_str,
    local_time_str,
    local_timestamp_iso,
    now_local,
    prompt_datetime_context,
    response_includes_current_local_date,
)


def test_now_local_matches_system_offset() -> None:
    """Local prompt clock should match UTC converted to local."""
    utc_now = datetime.now(UTC)
    local_now = now_local()
    assert local_now.utcoffset() is not None
    assert abs((local_now - utc_now.astimezone()).total_seconds()) < 2


def test_prompt_datetime_context_has_local_fields() -> None:
    """Prompt context exposes date, time, and timezone label."""
    ctx = prompt_datetime_context()
    assert ctx["current_date"] == local_date_str()
    assert ctx["current_time"] == local_time_str()
    assert ctx["schedule_timezone"]
    assert "T" in local_timestamp_iso() or "+" in local_timestamp_iso()


def test_build_canonical_datetime_reply_uses_local_date() -> None:
    reply = build_canonical_datetime_reply()
    assert reply == f"Today is {format_friendly_local_date()}."
    assert response_includes_current_local_date(reply)


def test_response_includes_current_local_date_detects_iso_and_friendly() -> None:
    iso = local_date_str()
    friendly = format_friendly_local_date()
    assert response_includes_current_local_date(f"Reference date {iso}.")
    assert response_includes_current_local_date(f"Today is {friendly}.")
    assert not response_includes_current_local_date("Today is June 28, 2025.")
