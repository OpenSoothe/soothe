"""Round-trip tests for CognitionGoalTreeMessage in the message store."""

import json

from soothe_cli.tui.binding import message_from_widget, message_to_widget
from soothe_cli.tui.widgets.message_store import MessageType
from soothe_cli.tui.widgets.messages import CognitionGoalTreeMessage


def test_cognition_goal_tree_pending_and_queued_phases() -> None:
    """Plan rows show pending and queued phases before execution."""
    w = CognitionGoalTreeMessage(goal="Plan work", id="msg-gt-02")
    w.sync_plan_steps([{"id": "S1", "description": "First", "dependencies": ["S0"]}])
    assert w._steps["S1"].phase == "pending"
    assert w._steps["S1"].dependencies == ("S0",)

    w.set_step_phase("S1", "queued", description="First")
    assert w._steps["S1"].phase == "queued"

    w.set_step_phase("S1", "running", description="First")
    assert w._steps["S1"].phase == "running"

    content = w._assemble_steps_content()
    assert "1:" in content.plain


def test_cognition_goal_tree_message_store_round_trip() -> None:
    """Serialize and restore a goal→steps tree card."""
    w = CognitionGoalTreeMessage(
        goal="Ship the feature",
        max_iterations=8,
        id="msg-gt-01",
    )
    w.set_step_phase("s1", "running", description="Read code")
    w.complete_step("s1", True, 1200, 2, "OK")
    w.set_loop_finished(
        status="done",
        goal_progress="complete",
        completion_summary="All good",
        total_steps=1,
    )

    md = message_from_widget(w)
    assert md.type == MessageType.COGNITION_GOAL_TREE
    assert md.cognition_goal_snapshot_json
    snap = json.loads(md.cognition_goal_snapshot_json or "{}")
    assert snap["goal"] == "Ship the feature"
    assert len(snap["steps"]) == 1
    assert snap["steps"][0]["id"] == "s1"
    assert snap["steps"][0]["dependencies"] == []
    assert snap["footer_visible"] is True
    assert snap.get("footer_tone") == "success"

    restored = message_to_widget(md)
    assert isinstance(restored, CognitionGoalTreeMessage)
    assert restored._goal_text == "Ship the feature"
    assert "s1" in restored._steps
    assert restored._footer_tone == "success"
