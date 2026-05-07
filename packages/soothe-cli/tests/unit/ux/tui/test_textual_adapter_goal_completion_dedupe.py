"""Tests for TUI suppression of duplicate ``goal_completion`` vs prior main output."""

from unittest.mock import AsyncMock, MagicMock

from soothe_cli.tui.textual_adapter import (
    TextualUIAdapter,
    _tui_goal_completion_matches_prior_main_visible_answer,
)


def _make_adapter() -> TextualUIAdapter:
    return TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=MagicMock(),
        request_approval=AsyncMock(),
    )


def test_goal_completion_matches_when_same_as_last_step_prose() -> None:
    adapter = _make_adapter()
    adapter._last_completed_main_step_execute_prose = "Counted 3 README files."
    assert _tui_goal_completion_matches_prior_main_visible_answer(
        adapter,
        ns_key=(),
        output_text="Counted 3 README files.",
    )


def test_goal_completion_matches_when_same_as_last_flushed_assistant() -> None:
    adapter = _make_adapter()
    adapter._last_main_flushed_assistant_prose = "Here is the answer."
    assert _tui_goal_completion_matches_prior_main_visible_answer(
        adapter,
        ns_key=(),
        output_text="Here is the answer.",
    )


def test_goal_completion_matches_when_same_as_pending_execute_buffer() -> None:
    """``goal_completion`` can arrive before flush; pending mirrors streamed assistant text."""
    adapter = _make_adapter()
    assert _tui_goal_completion_matches_prior_main_visible_answer(
        adapter,
        ns_key=(),
        output_text="Already on screen via append_content.",
        pending_execute_text="Already on screen via append_content.",
    )


def test_goal_completion_no_match_for_subagent_namespace() -> None:
    adapter = _make_adapter()
    adapter._last_completed_main_step_execute_prose = "same"
    assert not _tui_goal_completion_matches_prior_main_visible_answer(
        adapter,
        ns_key=("tools", "task:abc"),
        output_text="same",
    )


def test_goal_completion_no_match_when_no_prior() -> None:
    adapter = _make_adapter()
    adapter._last_completed_main_step_execute_prose = ""
    adapter._last_main_flushed_assistant_prose = ""
    assert not _tui_goal_completion_matches_prior_main_visible_answer(
        adapter,
        ns_key=(),
        output_text="Only in goal_completion",
    )
