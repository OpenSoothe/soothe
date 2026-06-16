"""Test workspace reducer handles multiple writes per step (IG-328 fix)."""

from __future__ import annotations

from soothe.subagents.explore.schemas import _last_wins


def test_last_wins_returns_right_when_non_empty() -> None:
    """Last non-empty value wins."""
    assert _last_wins(None, "/new") == "/new"
    assert _last_wins("/old", "/new") == "/new"
    assert _last_wins("", "/new") == "/new"


def test_last_wins_returns_left_when_right_empty() -> None:
    """Left value preserved when right is empty/None."""
    assert _last_wins("/old", None) == "/old"
    assert _last_wins("/old", "") == "/old"
    assert _last_wins("/old", "   ") == "/old"


def test_last_wins_returns_left_when_both_empty() -> None:
    """Left value (empty/None) returned when both are empty."""
    assert _last_wins(None, None) is None
    assert _last_wins("", "") == ""  # left preserved (empty string)
    assert _last_wins(None, "") is None  # left preserved
