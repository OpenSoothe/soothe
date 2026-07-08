"""Tests for eager TUI teardown when the user interrupts an active turn."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.runtime.state.session_stats import SessionStats
from soothe_cli.tui.app._messages_mixin import _MessagesMixin
from soothe_cli.tui.textual_adapter import TextualUIAdapter, _handle_interrupt_cleanup
from soothe_cli.tui.widgets.messages.cognition_goal_tree import CognitionGoalTreeMessage


@pytest.mark.asyncio
async def test_interrupt_cleanup_marks_goal_tree_interrupted() -> None:
    """Worker-cancel path must stop goal-tree running rows, not only step cards."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=lambda _s: None,
        set_spinner=AsyncMock(),
        set_active_message=MagicMock(),
    )
    tree = CognitionGoalTreeMessage(goal="analyze logs", max_iterations=3)
    tree.set_step_phase("TRA-01", "running", description="scan soothe.log")
    adapter._goal_tree_message = tree

    daemon_session = MagicMock()
    daemon_session.cancel_remote_query = AsyncMock()
    daemon_session.aupdate_loop_state = AsyncMock()

    await _handle_interrupt_cleanup(
        adapter=adapter,
        config={"configurable": {"thread_id": "loop-1"}},
        daemon_session=daemon_session,
        pending_text_by_namespace={},
        captured_input_tokens=0,
        captured_output_tokens=0,
        turn_stats=SessionStats(),
        start_time=0.0,
    )

    assert tree._goal_tree_status() == "error"
    assert "Stream cancelled" in (tree._footer_plain or "")


@pytest.mark.asyncio
async def test_interrupt_daemon_turn_tears_down_ui_before_cancel() -> None:
    """Ctrl+C should stop the thinking UI before awaiting daemon cancel."""

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self._daemon_session = AsyncMock()
            self._agent_worker = MagicMock()
            self._ui_adapter = MagicMock()
            self._ui_adapter._tool_to_step = {}
            self._ui_adapter._tool_display_by_call_id = {}
            self._ui_adapter._current_step_messages = {"s1": MagicMock()}
            self._ui_adapter._goal_tree_message = MagicMock()
            self._set_spinner = AsyncMock()

    app = _AppStub()
    await app._interrupt_daemon_agent_turn(discard_queue=False)

    app._ui_adapter.finalize_pending_steps_with_error.assert_called_once_with("Stream cancelled")
    app._set_spinner.assert_awaited_once_with(None)
    app._daemon_session.cancel_remote_query.assert_awaited_once()
    app._agent_worker.cancel.assert_called_once()
