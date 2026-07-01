"""Tests for single-word loop continuation keyword detection."""

from __future__ import annotations

from soothe.foundation.loop.utils.continue_keyword import is_continue_keyword


def test_continue_keyword_matches_single_word() -> None:
    assert is_continue_keyword("continue")
    assert is_continue_keyword("Continue")
    assert is_continue_keyword("  continue  ")


def test_continue_keyword_rejects_phrases() -> None:
    assert not is_continue_keyword("continue cleaning")
    assert not is_continue_keyword("")
    assert not is_continue_keyword(None)
    assert not is_continue_keyword("keep going")
