"""Unit tests for Pass 1 social_response resolution."""

from __future__ import annotations

from soothe.foundation.sloop.chitchat_fallbacks import GENERIC_CHITCHAT_FALLBACKS_EN
from soothe.foundation.sloop.intention.models import IntakePass1Confidence, IntakePass1LLMResult
from soothe.foundation.sloop.intention.pass1_social_response import (
    coalesce_pass1_dict,
    resolve_pass1_chitchat_response,
)


def test_coalesce_pass1_dict_defaults_missing_social_kind() -> None:
    merged = coalesce_pass1_dict(
        {
            "is_task": False,
            "confidence": "high",
            "social_response": "Hi!",
            "reasoning": "greeting",
        }
    )
    assert merged["social_kind"] == "other"


def test_coalesce_pass1_dict_preserves_social_kind() -> None:
    merged = coalesce_pass1_dict(
        {
            "is_task": False,
            "confidence": "high",
            "social_response": "Hi!",
            "social_kind": "greeting",
            "reasoning": "greeting",
        }
    )
    assert merged["social_kind"] == "greeting"


def test_resolve_pass1_chitchat_response_prefers_direct_field() -> None:
    result = IntakePass1LLMResult(
        is_task=False,
        confidence=IntakePass1Confidence.HIGH,
        social_response="Direct reply",
        reasoning="Social greeting",
    )
    assert resolve_pass1_chitchat_response(result) == "Direct reply"


def test_resolve_pass1_chitchat_response_falls_back_to_generic() -> None:
    result = IntakePass1LLMResult(
        is_task=False,
        confidence=IntakePass1Confidence.HIGH,
        social_response=None,
        reasoning="Social greeting",
    )
    reply = resolve_pass1_chitchat_response(result, query="hello")
    assert reply in GENERIC_CHITCHAT_FALLBACKS_EN
