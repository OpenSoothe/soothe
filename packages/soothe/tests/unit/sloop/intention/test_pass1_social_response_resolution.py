"""Pass 1 social intent resolves chitchat replies before runner identity finalize."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe.foundation.sloop.chitchat_fallbacks import GENERIC_CHITCHAT_FALLBACKS_EN
from soothe.foundation.sloop.intention.classifier import IntentClassifier
from soothe.foundation.sloop.intention.models import (
    IntakePass1Confidence,
    IntakePass1LLMResult,
    IntakePass1SocialKind,
)


def _classifier() -> IntentClassifier:
    return IntentClassifier(model=MagicMock(), assistant_name="Soothe")


def test_pass1_to_intent_uses_llm_social_response() -> None:
    classifier = _classifier()
    pass1 = IntakePass1LLMResult(
        is_task=False,
        confidence=IntakePass1Confidence.HIGH,
        social_response="I was invented by Dr. Xiaming Chen.",
        social_kind=IntakePass1SocialKind.IDENTITY,
        reasoning="creator question",
    )
    intent = classifier.pass1_to_intent(pass1, "who is your daddy")
    assert intent.chitchat_response == "I was invented by Dr. Xiaming Chen."
    assert intent.social_kind == IntakePass1SocialKind.IDENTITY


def test_pass1_to_intent_generic_fallback_without_llm_response() -> None:
    classifier = _classifier()
    pass1 = IntakePass1LLMResult(
        is_task=False,
        confidence=IntakePass1Confidence.HIGH,
        social_response=None,
        social_kind=IntakePass1SocialKind.IDENTITY,
        reasoning="Social question, not a work request.",
    )
    intent = classifier.pass1_to_intent(pass1, "who is your daddy")
    assert intent.chitchat_response in GENERIC_CHITCHAT_FALLBACKS_EN


def test_pass1_to_intent_passes_through_llm_text_before_runner_finalize() -> None:
    classifier = _classifier()
    pass1 = IntakePass1LLMResult(
        is_task=False,
        confidence=IntakePass1Confidence.HIGH,
        social_response="I'm Claude, an AI assistant made by Anthropic.",
        social_kind=IntakePass1SocialKind.IDENTITY,
        reasoning="identity question",
    )
    intent = classifier.pass1_to_intent(pass1, "what is your name")
    assert intent.chitchat_response == "I'm Claude, an AI assistant made by Anthropic."
