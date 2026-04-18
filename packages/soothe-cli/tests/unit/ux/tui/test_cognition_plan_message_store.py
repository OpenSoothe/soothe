"""Round-trip tests for CognitionPlanReasonMessage in the message store."""

from soothe_cli.tui.widgets.message_store import MessageData, MessageType
from soothe_cli.tui.widgets.messages import CognitionPlanReasonMessage


def test_cognition_plan_message_store_round_trip() -> None:
    """Serialize and restore a cognition plan card."""
    w = CognitionPlanReasonMessage(
        next_action="Read src/foo.py",
        status="continue",
        iteration=2,
        plan_action="new",
        assessment_reasoning="Progress looks good.",
        plan_reasoning="Need to verify imports.",
        legacy_reasoning="",
        id="msg-plan-01",
    )
    md = MessageData.from_widget(w)
    assert md.type == MessageType.COGNITION_PLAN
    assert md.cognition_plan_next_action == "Read src/foo.py"
    assert md.cognition_plan_status == "continue"
    assert md.cognition_plan_iteration == 2
    assert md.cognition_plan_action == "new"
    assert md.cognition_plan_assessment == "Progress looks good."
    assert md.cognition_plan_strategy == "Need to verify imports."

    restored = md.to_widget()
    assert isinstance(restored, CognitionPlanReasonMessage)
    assert restored._next_action == "Read src/foo.py"
    assert restored._plan_reasoning == "Need to verify imports."
