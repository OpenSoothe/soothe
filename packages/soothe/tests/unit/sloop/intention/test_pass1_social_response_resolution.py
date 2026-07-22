"""Pass 1 social intent resolves chitchat replies for fast-path emit."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe.sloop.chitchat_fallbacks import GENERIC_CHITCHAT_FALLBACKS_EN
from soothe.sloop.intention.classifier import IntentClassifier
from soothe.sloop.intention.models import (
    IntakePass1Confidence,
    IntakePass1LLMResult,
    IntakePass1SocialKind,
)


def _classifier() -> IntentClassifier:
    return IntentClassifier(model=MagicMock(), assistant_name="Soothe")


def test_pass1_to_intent_passthrough_llm_text_verbatim() -> None:
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
    assert intent.social_kind == IntakePass1SocialKind.IDENTITY


def test_pass1_to_intent_leaves_empty_when_llm_omits_social_response() -> None:
    classifier = _classifier()
    pass1 = IntakePass1LLMResult(
        is_task=False,
        confidence=IntakePass1Confidence.HIGH,
        social_response=None,
        social_kind=IntakePass1SocialKind.IDENTITY,
        reasoning="Social question, not a work request.",
    )
    intent = classifier.pass1_to_intent(pass1, "who is your daddy")
    assert intent.chitchat_response == ""


def test_patch_missing_fields_fills_generic_chitchat_fallback() -> None:
    classifier = _classifier()
    intent = classifier._patch_missing_fields(
        classifier.pass1_to_intent(
            IntakePass1LLMResult(
                is_task=False,
                confidence=IntakePass1Confidence.HIGH,
                social_response=None,
                social_kind=IntakePass1SocialKind.IDENTITY,
                reasoning="Social question, not a work request.",
            ),
            "who is your daddy",
        ),
        "who is your daddy",
    )
    assert intent.chitchat_response in GENERIC_CHITCHAT_FALLBACKS_EN
