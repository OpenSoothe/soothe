"""Tests for compact id formatting."""

from __future__ import annotations

from soothe_cli.runtime.presentation.id_format import (
    abbreviate_compact_id,
    compact_id_suffix,
)


def test_abbreviate_compact_id_prefix_suffix() -> None:
    assert abbreviate_compact_id("019f17e6-1234-5678-9abc-def012346543") == "019f17e6...6543"


def test_abbreviate_compact_id_keeps_short() -> None:
    assert abbreviate_compact_id("abc123") == "abc123"


def test_abbreviate_compact_id_empty_default() -> None:
    assert abbreviate_compact_id("") == ""
    assert abbreviate_compact_id("[]", empty="unknown") == "unknown"


def test_abbreviate_compact_id_preserves_existing_ellipsis() -> None:
    assert abbreviate_compact_id("019f17e6...6543") == "019f17e6...6543"


def test_compact_id_suffix_takes_trailing_chars() -> None:
    assert compact_id_suffix("019ff5a0-1234-5678-9abc-def012348d26") == "8d26"
    assert compact_id_suffix("019f17e6-1234-5678-9abc-def012346543") == "6543"


def test_compact_id_suffix_empty_and_short() -> None:
    assert compact_id_suffix("") == ""
    assert compact_id_suffix("[]") == ""
    assert compact_id_suffix("ab") == "ab"
    assert compact_id_suffix("abcd", length=2) == "cd"
