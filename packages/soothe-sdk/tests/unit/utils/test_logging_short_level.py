"""Tests for compact log level formatting."""

from __future__ import annotations

import logging
import re
import time

import pytest

from soothe_sdk.utils.logging import (
    ShortLevelFormatter,
    abbreviate_logger_name,
    short_level_letter,
)


@pytest.mark.parametrize(
    ("levelno", "expected"),
    [
        (logging.DEBUG, "D"),
        (logging.INFO, "I"),
        (logging.WARNING, "W"),
        (logging.ERROR, "E"),
        (logging.CRITICAL, "C"),
    ],
)
def test_short_level_letter_standard_levels(levelno: int, expected: str) -> None:
    assert short_level_letter(levelno) == expected


def test_short_level_letter_unknown_level() -> None:
    assert short_level_letter(999) == "?"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("", ""),
        ("httpx", "httpx"),
        ("soothe.core", "soothe.core"),
        (
            "soothe.core.loop.state.state_manager",
            "s.c.l.state.state_manager",
        ),
        ("a.b.c.d", "a.b.c.d"),
    ],
)
def test_abbreviate_logger_name(name: str, expected: str) -> None:
    assert abbreviate_logger_name(name) == expected


def test_short_level_formatter_abbreviates_name_in_output() -> None:
    fmt = ShortLevelFormatter("%(name)s %(message)s")
    record = logging.LogRecord(
        name="soothe.core.loop.state.state_manager",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="x",
        args=(),
        exc_info=None,
    )
    line = fmt.format(record)
    assert line == "s.c.l.state.state_manager x"
    assert record.name == "soothe.core.loop.state.state_manager"


def test_short_level_formatter_inserts_level_short() -> None:
    fmt = ShortLevelFormatter("%(level_short)s %(message)s")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="hello",
        args=(),
        exc_info=None,
    )
    line = fmt.format(record)
    assert line == "I hello"


_COMPACT_TS = re.compile(r"^\d{8}T\d{6}\.\d{3}$")


def test_short_level_formatter_compact_asctime_preserves_precision() -> None:
    """Compact time keeps YMD + HHMMSS + ms (same resolution as default asctime)."""
    fmt = ShortLevelFormatter("%(asctime)s %(message)s")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="ping",
        args=(),
        exc_info=None,
    )
    # Fixed epoch: 2026-05-03 01:17:47.334 local — values follow converter(localtime).
    fixed = time.struct_time((2026, 5, 3, 1, 17, 47, 6, 123, -1))
    record.created = time.mktime(fixed)
    record.msecs = 334

    line = fmt.format(record)
    ts, _, rest = line.partition(" ")
    assert _COMPACT_TS.match(ts), ts
    assert rest == "ping"


def test_short_level_formatter_accepts_float_msecs() -> None:
    """``LogRecord.msecs`` may be float; compact time must not raise."""
    fmt = ShortLevelFormatter("%(asctime)s %(message)s")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="x",
        args=(),
        exc_info=None,
    )
    record.msecs = 333.7  # type: ignore[assignment]
    line = fmt.format(record)
    ts = line.split()[0]
    assert _COMPACT_TS.match(ts), ts


def test_short_level_formatter_respects_custom_datefmt() -> None:
    fmt = ShortLevelFormatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="x",
        args=(),
        exc_info=None,
    )
    fixed = time.struct_time((2026, 5, 3, 1, 17, 47, 6, 123, -1))
    record.created = time.mktime(fixed)

    line = fmt.format(record)
    assert line.startswith("2026-05-03 ")
