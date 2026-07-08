"""Unit tests for Pass 1 social_response schema helpers."""

from __future__ import annotations

from soothe.foundation.sloop.intention.pass1_social_response import coalesce_pass1_dict


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
