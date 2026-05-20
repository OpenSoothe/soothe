"""Tests for soothe_cli.runtime.presentation.duration_format."""

from __future__ import annotations

from soothe_cli.runtime.presentation.duration_format import format_duration_ms


def test_format_duration_ms_subsecond() -> None:
    assert format_duration_ms(0) == "0ms"
    assert format_duration_ms(12) == "12ms"
    assert format_duration_ms(999) == "999ms"


def test_format_duration_ms_seconds_and_longer() -> None:
    assert format_duration_ms(1000) == "1s"
    assert format_duration_ms(1500) == "1.5s"
    assert format_duration_ms(65_000) == "1m 5s"


def test_format_duration_ms_negative_treated_as_zero() -> None:
    assert format_duration_ms(-10) == "0ms"
