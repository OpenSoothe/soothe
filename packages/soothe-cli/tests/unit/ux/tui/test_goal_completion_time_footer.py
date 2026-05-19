"""Tests for goal completion total-time footer."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.textual_adapter import (
    _finalize_goal_completion_stream,
    _goal_completion_time_footer_if_needed,
)


def test_goal_completion_time_footer_formats_elapsed() -> None:
    start = time.monotonic() - 125.0
    footer = _goal_completion_time_footer_if_needed(
        "Done.",
        goal_loop_start_monotonic=start,
        turn_start_monotonic=None,
    )
    assert footer is not None
    assert "**Total time:**" in footer
    assert "2m" in footer


def test_goal_completion_time_footer_skips_when_already_present() -> None:
    footer = _goal_completion_time_footer_if_needed(
        "Done.\n\n**Total time:** 1s",
        goal_loop_start_monotonic=time.monotonic(),
        turn_start_monotonic=None,
    )
    assert footer is None


@pytest.mark.asyncio
async def test_finalize_goal_completion_stream_appends_time_footer() -> None:
    msg = MagicMock()
    msg._content = "Synthesis result"
    msg.append_content = AsyncMock()
    msg.stop_stream = AsyncMock()

    adapter = MagicMock()
    adapter._sync_message_content = MagicMock()
    adapter._set_active_message = MagicMock()
    adapter._set_spinner = AsyncMock()

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

    assert msg.append_content.await_count == 1
    footer_call = msg.append_content.await_args_list[0].args[0]
    assert "**Total time:**" in footer_call
    msg.stop_stream.assert_awaited_once()
