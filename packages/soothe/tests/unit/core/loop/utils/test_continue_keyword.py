"""Tests for single-word loop continuation and interrupt-resume keywords."""

from __future__ import annotations

from soothe.sloop.utils.continue_keyword import (
    is_continue_keyword,
    is_interrupt_resume_keyword,
)


def test_continue_keyword_matches_single_word() -> None:
    assert is_continue_keyword("continue")
    assert is_continue_keyword("Continue")
    assert is_continue_keyword("  continue  ")
    assert is_continue_keyword("resume")
    assert is_continue_keyword("proceed")


def test_continue_keyword_rejects_retry_and_phrases() -> None:
    # retry is interrupt-resume only — not idle-loop continue bootstrap.
    assert not is_continue_keyword("retry")
    assert not is_continue_keyword("continue cleaning")
    assert not is_continue_keyword("")
    assert not is_continue_keyword(None)
    assert not is_continue_keyword("keep going")


def test_interrupt_resume_keyword_includes_retry() -> None:
    assert is_interrupt_resume_keyword("retry")
    assert is_interrupt_resume_keyword("Retry")
    assert is_interrupt_resume_keyword("continue")
    assert is_interrupt_resume_keyword("resume")
    assert is_interrupt_resume_keyword("proceed")
    assert not is_interrupt_resume_keyword("retry the build")
    assert not is_interrupt_resume_keyword("")
