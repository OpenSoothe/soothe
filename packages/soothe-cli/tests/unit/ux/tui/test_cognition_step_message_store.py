"""CognitionStepMessage serialization for message virtualization."""

from __future__ import annotations

from soothe_cli.tui.widgets.message_store import MessageData, MessageType
from soothe_cli.tui.widgets.messages import CognitionStepMessage


def test_step_progress_round_trip_completed() -> None:
    w = CognitionStepMessage("sid-1", "Read files", id="stp-test")
    w.set_complete(True, 1500, 2, "all good")
    md = MessageData.from_widget(w)
    assert md.type == MessageType.STEP_PROGRESS
    assert md.step_progress_id == "sid-1"
    assert md.step_progress_phase == "success"
    assert md.step_success is True
    assert md.step_duration_ms == 1500
    assert md.step_tool_call_count == 2
    w2 = md.to_widget()
    assert isinstance(w2, CognitionStepMessage)


def test_step_progress_round_trip_interrupted() -> None:
    w = CognitionStepMessage("sid-2", "Run", id="stp-int")
    w.set_interrupted("Cancelled")
    md = MessageData.from_widget(w)
    assert md.type == MessageType.STEP_PROGRESS
    assert md.step_progress_phase == "interrupted"
    assert md.step_summary == "Cancelled"
