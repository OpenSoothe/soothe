"""Tests for TUI clarification prompt visibility by mode."""

from soothe_cli.tui.textual_adapter import _should_show_clarification_prompt


def test_shows_prompt_in_manual_mode() -> None:
    """Manual mode keeps the interactive awaiting-answer card visible."""
    assert _should_show_clarification_prompt(
        event_data={"mode": "manual"},
        fallback_mode="auto",
    )


def test_hides_prompt_in_auto_mode() -> None:
    """Auto mode suppresses the interactive awaiting-answer card."""
    assert not _should_show_clarification_prompt(
        event_data={"mode": "auto"},
        fallback_mode="manual",
    )


def test_fallback_mode_used_when_event_mode_missing() -> None:
    """When event payload omits mode, the turn's configured mode controls visibility."""
    assert not _should_show_clarification_prompt(event_data={}, fallback_mode="auto")
    assert _should_show_clarification_prompt(event_data={}, fallback_mode="manual")
