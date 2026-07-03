"""CognitionStepMessage serialization for message virtualization."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe_cli.tui.binding import message_from_widget, message_to_widget
from soothe_cli.tui.widgets.message_store import MessageType
from soothe_cli.tui.widgets.messages import CognitionStepMessage


def test_step_progress_round_trip_completed() -> None:
    w = CognitionStepMessage("sid-1", "Read files", id="stp-test")
    w.add_tool_call("tc-1", "grep", {"pattern": "foo"})
    w.set_tool_success("tc-1", "ok", duration_ms=5)
    w.set_complete(True, 1500, 2, "all good")
    md = message_from_widget(w)
    assert md.type == MessageType.STEP_PROGRESS
    assert md.step_progress_id == "sid-1"
    assert md.step_progress_phase == "success"
    assert md.step_success is True
    assert md.step_duration_ms == 1500
    assert md.step_tool_call_count == 2
    assert md.step_tool_calls_json is not None
    assert "tc-1" in md.step_tool_calls_json
    w2 = message_to_widget(md)
    assert isinstance(w2, CognitionStepMessage)
    assert w2.has_tool_call_row("tc-1")


def test_step_set_interrupted_hides_footer_when_message_empty() -> None:
    """User cancel (Esc) stops the step without a chat footer line."""
    step = CognitionStepMessage(step_id="s1", description="Run tools", id="stp-silent")
    step._status = "running"
    step._status_widget = MagicMock()

    step.set_interrupted("")

    assert step._status_widget.display is False
    assert step._interrupt_message == ""


def test_step_set_interrupted_shows_message_when_provided() -> None:
    """Stream errors still surface an explicit interrupted label."""
    step = CognitionStepMessage(step_id="s2", description="Run", id="stp-msg")
    step._status_widget = MagicMock()

    step.set_interrupted("Connection lost")

    step._status_widget.update.assert_called_once()
    assert step._status_widget.display is True


def test_step_progress_round_trip_interrupted() -> None:
    w = CognitionStepMessage("sid-2", "Run", id="stp-int")
    w.set_interrupted("Cancelled")
    md = message_from_widget(w)
    assert md.type == MessageType.STEP_PROGRESS
    assert md.step_progress_phase == "interrupted"
    assert md.step_summary == "Cancelled"
