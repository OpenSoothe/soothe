"""Round-trip tests for CognitionGoalTreeMessage in the message store."""

import json

from soothe_cli.tui.widgets.message_store import MessageData, MessageType
from soothe_cli.tui.widgets.messages import CognitionGoalTreeMessage


def test_cognition_goal_tree_message_store_round_trip() -> None:
    """Serialize and restore a goal→steps tree card."""
    w = CognitionGoalTreeMessage(
        goal="Ship the feature",
        max_iterations=8,
        id="msg-gt-01",
    )
    w.add_step_running("s1", "Read code")
    w.complete_step("s1", True, 1200, 2, "OK")
    w.set_loop_finished(
        status="done",
        goal_progress=1.0,
        completion_summary="All good",
        total_steps=1,
    )

    md = MessageData.from_widget(w)
    assert md.type == MessageType.COGNITION_GOAL_TREE
    assert md.cognition_goal_snapshot_json
    snap = json.loads(md.cognition_goal_snapshot_json or "{}")
    assert snap["goal"] == "Ship the feature"
    assert len(snap["steps"]) == 1
    assert snap["steps"][0]["id"] == "s1"
    assert snap["footer_visible"] is True

    restored = md.to_widget()
    assert isinstance(restored, CognitionGoalTreeMessage)
    assert restored._goal_text == "Ship the feature"
    assert "s1" in restored._steps
