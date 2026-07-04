"""Tests for intake identity block used in classification prompts."""

from soothe.foundation.sloop.intention.identity_messages import build_intake_identity_message
from soothe.foundation.sloop.intention.models import IntakeClassificationLLMResult, IntakeLabel


def test_build_intake_identity_message_includes_assistant_name() -> None:
    text = build_intake_identity_message("Soothe")
    assert "Soothe" in text
    assert "helpful AI assistant" in text


def test_build_intake_identity_message_includes_self_identify_rule() -> None:
    text = build_intake_identity_message("TestBot")
    assert "TestBot" in text
    assert "do not claim another vendor model" in text


def test_intake_llm_result_has_no_quiz_response_field() -> None:
    result = IntakeClassificationLLMResult(
        intake_label=IntakeLabel.TRIVIAL,
        reasoning="I'll say hello.",
        goal_description="hello",
    )
    assert "quiz_response" not in result.model_dump()
