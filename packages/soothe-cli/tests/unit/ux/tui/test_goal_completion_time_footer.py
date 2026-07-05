"""Tests for goal completion elapsed time on the thinking row."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.spinner_labels import SPINNER_LABEL_THINKING
from soothe_cli.tui.textual_adapter import (
    TextualUIAdapter,
    _finalize_goal_completion_stream,
    _goal_loop_elapsed_start,
    _sync_goal_completion_thinking_row_time,
)


def test_goal_loop_elapsed_start_prefers_goal_loop_anchor() -> None:
    turn = time.monotonic()
    goal = turn + 10.0
    assert (
        _goal_loop_elapsed_start(
            goal_loop_start_monotonic=goal,
            turn_start_monotonic=turn,
        )
        == goal
    )


def test_goal_loop_elapsed_start_falls_back_to_turn() -> None:
    turn = time.monotonic()
    assert (
        _goal_loop_elapsed_start(
            goal_loop_start_monotonic=None,
            turn_start_monotonic=turn,
        )
        == turn
    )


@pytest.mark.asyncio
async def test_sync_goal_completion_thinking_row_time_sets_spinner_anchor() -> None:
    adapter = TextualUIAdapter(MagicMock(), MagicMock(), set_spinner=AsyncMock())
    start = time.monotonic() - 5.0
    await _sync_goal_completion_thinking_row_time(
        adapter,
        goal_loop_start_monotonic=start,
        turn_start_monotonic=None,
    )
    adapter._set_spinner.assert_awaited_once_with(
        SPINNER_LABEL_THINKING,
        turn_start_mono=start,
    )


@pytest.mark.asyncio
async def test_finalize_goal_completion_stream_does_not_append_time_footer() -> None:
    msg = MagicMock()
    msg._content = "Synthesis result"
    msg.append_content = AsyncMock()
    msg.stop_stream = AsyncMock()

    adapter = TextualUIAdapter(MagicMock(), MagicMock(), set_spinner=AsyncMock())

    start = time.monotonic() - 3.0
    await _finalize_goal_completion_stream(
        adapter,
        msg,
        ns_key=(),
        goal_completion_stream_by_namespace={(): msg},
        assistant_message_by_namespace={},
        extra_text="",
        goal_loop_start_monotonic=start,
        turn_start_monotonic=None,
    )

    msg.append_content.assert_not_called()
    msg.stop_stream.assert_awaited_once()
    adapter._set_spinner.assert_awaited_once_with(
        SPINNER_LABEL_THINKING,
        turn_start_mono=start,
    )
