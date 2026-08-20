"""Social intent resolves chitchat replies for fast-path emit."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe.sloop.intention.chitchat_fallbacks import GENERIC_CHITCHAT_FALLBACKS_EN
from soothe.sloop.intention.classifier import IntentClassifier
from soothe.sloop.intention.models import (
    IntakeConfidence,
    IntakeLLMResult,
)


def _classifier() -> IntentClassifier:
    return IntentClassifier(model=MagicMock(), assistant_name="Soothe")


def test_social_to_intent_passthrough_llm_text_verbatim() -> None:
    classifier = _classifier()
    intake = IntakeLLMResult(
        is_task=False,
        confidence=IntakeConfidence.HIGH,
        social_response="I'm Claude, an AI assistant made by Anthropic.",
        reasoning="identity question",
    )
    intent = classifier.social_to_intent(intake, "what is your name")
    assert intent.chitchat_response == "I'm Claude, an AI assistant made by Anthropic."


def test_social_to_intent_leaves_empty_when_llm_omits_social_response() -> None:
    classifier = _classifier()
    intake = IntakeLLMResult(
        is_task=False,
        confidence=IntakeConfidence.HIGH,
        social_response=None,
        reasoning="Social question, not a work request.",
    )
    intent = classifier.social_to_intent(intake, "who is your daddy")
    assert intent.chitchat_response == ""


def test_patch_missing_fields_fills_generic_chitchat_fallback() -> None:
    classifier = _classifier()
    intent = classifier._patch_missing_fields(
        classifier.social_to_intent(
            IntakeLLMResult(
                is_task=False,
                confidence=IntakeConfidence.HIGH,
                social_response=None,
                reasoning="Social question, not a work request.",
            ),
            "who is your daddy",
        ),
        "who is your daddy",
    )
    assert intent.chitchat_response in GENERIC_CHITCHAT_FALLBACKS_EN
