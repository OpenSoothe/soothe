"""Round-trip tests for CognitionReasonMessage in the message store."""

from soothe_cli.tui.binding import message_from_widget, message_to_widget
from soothe_cli.tui.widgets.message_store import MessageType
from soothe_cli.tui.widgets.messages import CognitionReasonMessage


def test_cognition_plan_message_store_round_trip() -> None:
    """Serialize and restore a cognition plan card."""
    w = CognitionReasonMessage(
        next_action="",
        status="continue",
        iteration=2,
        plan_action="new",
        assessment_reasoning="Progress looks good.",
        plan_reasoning="Need to verify imports.",
        id="msg-plan-01",
    )
    md = message_from_widget(w)
    assert md.type == MessageType.COGNITION_REASON
    assert md.cognition_plan_next_action == ""
    assert md.cognition_plan_status == "continue"
    assert md.cognition_plan_iteration == 2
    assert md.cognition_plan_action == "new"
    assert md.cognition_plan_assessment == "Progress looks good."
    assert md.cognition_plan_strategy == "Need to verify imports."

    restored = message_to_widget(md)
    assert isinstance(restored, CognitionReasonMessage)
    assert restored._assessment_reasoning == "Progress looks good."
    assert restored._plan_reasoning == "Need to verify imports."


def test_assess_only_card_round_trip() -> None:
    """Assess-only card stores and restores assessment_reasoning."""
    w = CognitionReasonMessage(
        next_action="",
        status="",
        iteration=1,
        plan_action="",
        assessment_reasoning="Evidence is accumulating.",
        plan_reasoning="",
        id="msg-assess-01",
    )
    md = message_from_widget(w)
    assert md.type == MessageType.COGNITION_REASON
    assert md.cognition_plan_assessment == "Evidence is accumulating."
    assert md.cognition_plan_next_action == ""
    assert md.cognition_plan_action == ""

    restored = message_to_widget(md)
    assert isinstance(restored, CognitionReasonMessage)
    assert restored._assessment_reasoning == "Evidence is accumulating."
    assert restored._next_action == ""
    assert restored._plan_action == ""


def test_intent_only_card_round_trip() -> None:
    """Intent card stores and restores friendly_message via assessment_reasoning."""
    w = CognitionReasonMessage(
        next_action="",
        status="",
        iteration=0,
        plan_action="",
        assessment_reasoning="I'll help you refactor the module.",
        plan_reasoning="",
        id="msg-intent-01",
    )
    md = message_from_widget(w)
    assert md.type == MessageType.COGNITION_REASON
    assert md.cognition_plan_next_action == ""
    assert md.cognition_plan_assessment == "I'll help you refactor the module."
    assert md.cognition_plan_action == ""

    restored = message_to_widget(md)
    assert isinstance(restored, CognitionReasonMessage)
    assert restored._assessment_reasoning == "I'll help you refactor the module."
    assert restored._plan_action == ""
