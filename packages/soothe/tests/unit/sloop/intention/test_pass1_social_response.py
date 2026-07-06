"""Unit tests for Pass 1 social_response salvage and resolution."""

from __future__ import annotations

from soothe.foundation.sloop.intention.models import IntakePass1Confidence, IntakePass1LLMResult
from soothe.foundation.sloop.intention.pass1_social_response import (
    coalesce_pass1_dict,
    resolve_pass1_chitchat_response,
    salvage_social_response_from_reasoning,
)


def test_salvage_requested_social_response_from_reasoning() -> None:
    reasoning = (
        "Casual identity question, social chitchat intent clearly detected. "
        "Requested social_response: I'm Soothe, invented by Dr. Xiaming Chen."
    )
    assert salvage_social_response_from_reasoning(reasoning) == (
        "I'm Soothe, invented by Dr. Xiaming Chen."
    )


def test_coalesce_pass1_dict_promotes_salvaged_reply() -> None:
    raw = {
        "is_task": False,
        "confidence": "high",
        "social_response": "",
        "reasoning": "Social question. social_response: Hi there!",
    }
    merged = coalesce_pass1_dict(raw)
    assert merged["social_response"] == "Hi there!"


def test_resolve_pass1_chitchat_response_prefers_direct_field() -> None:
    result = IntakePass1LLMResult(
        is_task=False,
        confidence=IntakePass1Confidence.HIGH,
        social_response="Direct reply",
        reasoning="greeting",
    )
    assert resolve_pass1_chitchat_response(result) == "Direct reply"


def test_resolve_pass1_chitchat_response_falls_back_to_generic() -> None:
    result = IntakePass1LLMResult(
        is_task=False,
        confidence=IntakePass1Confidence.HIGH,
        social_response=None,
        reasoning="Social question, not a work request.",
    )
    assert resolve_pass1_chitchat_response(result) == "Hello! How can I help you today?"
