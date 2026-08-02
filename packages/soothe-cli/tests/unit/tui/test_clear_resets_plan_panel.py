"""Tests that transcript wipe drops live plan-panel state."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.app._messages_mixin import _MessagesMixin
from soothe_cli.tui.textual_adapter import TextualUIAdapter
from soothe_cli.tui.widgets.messages.cognition_goal_tree import CognitionGoalTreeMessage


def test_adapter_clear_live_session_ui_drops_goal_tree_and_clarification() -> None:
    """Live plan/clarification handles must not survive a session wipe."""
    adapter = object.__new__(TextualUIAdapter)
    adapter._goal_tree_message = CognitionGoalTreeMessage(goal="Ship it", id="gt-1")
    adapter._current_step_messages = {"s1": MagicMock()}
    adapter._tool_to_step = {"tc1": MagicMock()}
    adapter._step_by_namespace = {(): MagicMock()}
    adapter._tool_display_by_call_id = {"tc1": MagicMock()}
    adapter._step_router = MagicMock()
    adapter._orphan_cards_by_invocation = {"inv": MagicMock()}
    adapter._file_change_previews_shown = {"tc1"}
    adapter._file_change_widgets = {"tc1": MagicMock()}
    adapter._file_preview_assistant_id = "asst-1"
    adapter._last_completed_main_step_execute_prose = "done"
    adapter._last_main_flushed_assistant_prose = "flushed"
    adapter._goal_completion_mounted_this_turn = True
    adapter._clarification_pending = True
    adapter._clarification_answers_pending = ["yes"]
    adapter._clarification_input_by_step = {"s1": MagicMock()}
    adapter._execute_wave_total = 3
    adapter._execute_wave_completed = 1
    adapter._last_plan_execution_mode = "parallel"
    adapter._plan_step_order = ["s1"]
    adapter._plan_step_ids = {"s1"}
    adapter._plan_step_dependencies = {"s1": ()}
    adapter._set_active_message = MagicMock()

    adapter.clear_live_session_ui()

    assert adapter._goal_tree_message is None
    assert adapter._current_step_messages == {}
    assert adapter._tool_to_step == {}
    assert adapter._clarification_pending is False
    assert adapter._clarification_answers_pending is None
    assert adapter._clarification_input_by_step == {}
    assert adapter._plan_step_order == []
    assert adapter._plan_step_ids == set()
    assert adapter._last_plan_execution_mode is None
    adapter._step_router.reset_turn.assert_called_once()
    adapter._set_active_message.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_clear_messages_resets_plan_panel_and_spinner() -> None:
    """Transcript clear must null the live goal tree and collapse the plan panel."""
    app = object.__new__(_MessagesMixin)
    app._loop_history_loaded_for = "old-loop"
    app._message_store = MagicMock()
    app._deferred_assistant_renders = MagicMock()
    app._deferred_assistant_renders.clear = MagicMock()
    app._assistant_render_drain_scheduled = True

    adapter = MagicMock()
    app._ui_adapter = adapter

    overlay = MagicMock()
    app._get_plan_quick_view_overlay = MagicMock(return_value=overlay)
    app._set_spinner = AsyncMock()

    messages = MagicMock()
    messages.remove_children = AsyncMock()
    app.query_one = MagicMock(return_value=messages)

    await app._clear_messages()

    adapter.clear_live_session_ui.assert_called_once()
    overlay.refresh_content.assert_called_once()
    app._set_spinner.assert_awaited_once_with(None)
    assert app._loop_history_loaded_for is None
    app._message_store.clear.assert_called_once()
