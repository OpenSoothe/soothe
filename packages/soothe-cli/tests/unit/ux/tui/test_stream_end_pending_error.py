"""Tests for stream-end pending step/tool error messaging and goal-footer safety."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from soothe_cli.tui.textual_adapter import (
    TextualUIAdapter,
    _step_card_is_in_flight,
    _stream_end_pending_error_message,
)
from soothe_cli.tui.widgets.messages.cognition_goal_tree import CognitionGoalTreeMessage


def _adapter_with_step_status(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        _current_step_messages={"step-1": SimpleNamespace(_status=status)},
    )


def test_step_card_is_in_flight_only_running() -> None:
    assert _step_card_is_in_flight(SimpleNamespace(_status="running"))
    assert not _step_card_is_in_flight(SimpleNamespace(_status="success"))
    assert not _step_card_is_in_flight(SimpleNamespace(_status="error"))
    assert not _step_card_is_in_flight(SimpleNamespace(_status="pending"))


def test_stream_end_message_prefers_cancellation_notice() -> None:
    adapter = _adapter_with_step_status("running")
    session = SimpleNamespace(
        last_turn_cancellation_seen=True,
        last_turn_end_state="idle",
    )
    assert _stream_end_pending_error_message(adapter, session) == "Stream cancelled"


def test_stream_end_message_uses_stopped_state() -> None:
    adapter = _adapter_with_step_status("running")
    session = SimpleNamespace(
        last_turn_cancellation_seen=False,
        last_turn_end_state="stopped",
    )
    assert _stream_end_pending_error_message(adapter, session) == "Stream cancelled"


def test_stream_end_message_reports_connection_loss() -> None:
    adapter = _adapter_with_step_status("running")
    session = SimpleNamespace(
        last_turn_cancellation_seen=False,
        last_turn_end_state="connection_lost",
    )
    assert _stream_end_pending_error_message(adapter, session) == "Connection lost during stream"


def test_stream_end_worker_thread_lost_message() -> None:
    adapter = TextualUIAdapter(mount_message=MagicMock(), update_status=MagicMock())
    session = MagicMock()
    session.last_turn_cancellation_seen = False
    session.last_turn_end_state = "idle"
    session.last_turn_error_message = (
        "Worker thread exited unexpectedly during query execution; check daemon logs."
    )
    adapter._current_step_messages = {"s1": MagicMock(_status="running")}

    assert _stream_end_pending_error_message(adapter, session) == "Worker stopped during stream"


def test_stream_end_message_detects_incomplete_running_steps() -> None:
    adapter = _adapter_with_step_status("running")
    session = SimpleNamespace(
        last_turn_cancellation_seen=False,
        last_turn_end_state="idle",
    )
    assert (
        _stream_end_pending_error_message(adapter, session) == "Stream ended before steps completed"
    )


def test_stream_end_message_falls_back_to_unexpected() -> None:
    adapter = SimpleNamespace(_current_step_messages={})
    session = SimpleNamespace(
        last_turn_cancellation_seen=False,
        last_turn_end_state="idle",
    )
    assert _stream_end_pending_error_message(adapter, session) == "Stream ended unexpectedly"


def test_set_interrupted_preserves_success_footer_when_no_open_steps() -> None:
    tree = CognitionGoalTreeMessage(goal="Ship it", id="gt-success-footer")
    tree.sync_plan_steps([{"id": "S-01", "description": "Work"}])
    tree.complete_step("S-01", True, 1_000, 2, "Done [2 tools]")
    tree.set_loop_finished(
        status="done",
        goal_progress="complete",
        completion_summary="All good",
        total_steps=1,
        duration_ms=1_000,
    )
    before = tree._footer_plain
    assert tree._footer_tone == "success"

    tree.set_interrupted("Stream ended unexpectedly")

    assert tree._footer_plain == before
    assert tree._footer_tone == "success"
    assert "Stream ended unexpectedly" not in tree.plan_quick_view_content().plain


def test_finalize_pending_steps_skips_completed_cards_and_success_footer() -> None:
    adapter = TextualUIAdapter(mount_message=MagicMock(), update_status=MagicMock())
    tree = CognitionGoalTreeMessage(goal="Ship it", id="gt-finalize")
    tree.sync_plan_steps([{"id": "S-01", "description": "Work"}])
    tree.complete_step("S-01", True, 1_000, 2, "Done")
    tree.set_loop_finished(
        status="done",
        goal_progress="complete",
        completion_summary="All good",
        total_steps=1,
        duration_ms=1_000,
    )
    adapter._goal_tree_message = tree
    done_card = MagicMock()
    done_card._status = "success"
    adapter._current_step_messages = {"S-01": done_card}

    adapter.finalize_pending_steps_with_error(
        "Stream ended unexpectedly",
        only_in_flight=True,
        interrupt_goal_tree=False,
    )

    done_card.set_interrupted.assert_not_called()
    assert adapter._current_step_messages == {}
    assert tree._footer_tone == "success"
    assert "Stream ended unexpectedly" not in tree._footer_plain


def test_finalize_pending_steps_interrupts_running_when_goal_still_open() -> None:
    adapter = TextualUIAdapter(mount_message=MagicMock(), update_status=MagicMock())
    tree = CognitionGoalTreeMessage(goal="Ship it", id="gt-running")
    tree.mark_loop_started()
    tree.sync_plan_steps([{"id": "S-01", "description": "Work"}])
    tree.set_step_phase("S-01", "running")
    adapter._goal_tree_message = tree
    running = MagicMock()
    running._status = "running"
    adapter._current_step_messages = {"S-01": running}

    adapter.finalize_pending_steps_with_error(
        "Stream ended unexpectedly",
        only_in_flight=True,
        interrupt_goal_tree=True,
    )

    running.set_interrupted.assert_called_once_with("Stream ended unexpectedly")
    assert tree._footer_tone == "error"
    assert "Stream ended unexpectedly" in tree._footer_plain
