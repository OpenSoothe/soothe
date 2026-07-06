"""Pass 1 social intent resolves chitchat replies before runner identity finalize."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe.foundation.sloop.intention.classifier import IntentClassifier
from soothe.foundation.sloop.intention.models import IntakePass1Confidence, IntakePass1LLMResult


def _classifier() -> IntentClassifier:
    return IntentClassifier(model=MagicMock(), assistant_name="Soothe")


def test_pass1_to_intent_uses_llm_social_response() -> None:
    classifier = _classifier()
    pass1 = IntakePass1LLMResult(
        is_task=False,
        confidence=IntakePass1Confidence.HIGH,
        social_response="I was invented by Dr. Xiaming Chen.",
        reasoning="creator question",
    )
    intent = classifier.pass1_to_intent(pass1, "who is your daddy")
    assert intent.chitchat_response == "I was invented by Dr. Xiaming Chen."


def test_pass1_to_intent_salvages_reasoning_when_field_missing() -> None:
    classifier = _classifier()
    pass1 = IntakePass1LLMResult(
        is_task=False,
        confidence=IntakePass1Confidence.HIGH,
        social_response=None,
        reasoning=(
            "Casual identity question. Requested social_response: "
            "I'm Soothe, an AI assistant invented by Dr. Xiaming Chen."
        ),
    )
    intent = classifier.pass1_to_intent(pass1, "who are u")
    assert "Soothe" in (intent.chitchat_response or "")
    assert "Dr. Xiaming Chen" in (intent.chitchat_response or "")


def test_pass1_to_intent_passes_through_llm_text_before_runner_finalize() -> None:
    classifier = _classifier()
    pass1 = IntakePass1LLMResult(
        is_task=False,
        confidence=IntakePass1Confidence.HIGH,
        social_response="I'm Claude, an AI assistant made by Anthropic.",
        reasoning="identity question",
    )
    intent = classifier.pass1_to_intent(pass1, "what is your name")
    assert intent.chitchat_response == "I'm Claude, an AI assistant made by Anthropic."


def test_pass1_to_intent_generic_fallback_without_llm_response() -> None:
    classifier = _classifier()
    pass1 = IntakePass1LLMResult(
        is_task=False,
        confidence=IntakePass1Confidence.HIGH,
        social_response=None,
        reasoning="Social question, not a work request.",
    )
    intent = classifier.pass1_to_intent(pass1, "who is your daddy")
    assert intent.chitchat_response == "Hello! How can I help you today?"
