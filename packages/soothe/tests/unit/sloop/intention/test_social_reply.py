"""Unit tests for intake schema helpers."""

from __future__ import annotations

from soothe.sloop.intention.social_reply import coalesce_intake_dict


def test_coalesce_intake_dict_defaults_missing_task_complexity() -> None:
    merged = coalesce_intake_dict(
        {
            "is_task": True,
            "confidence": "high",
            "social_response": None,
            "reasoning": "task",
        }
    )
    assert merged["task_complexity"] is None


def test_coalesce_intake_dict_preserves_task_complexity() -> None:
    merged = coalesce_intake_dict(
        {
            "is_task": True,
            "confidence": "high",
            "social_response": None,
            "task_complexity": "complex",
            "reasoning": "task",
        }
    )
    assert merged["task_complexity"].value == "complex"


def test_coalesce_intake_dict_coerces_invalid_task_complexity_to_complex() -> None:
    merged = coalesce_intake_dict(
        {
            "is_task": True,
            "confidence": "high",
            "social_response": None,
            "task_complexity": "bogus",
            "reasoning": "task",
        }
    )
    assert merged["task_complexity"].value == "complex"


def test_coalesce_intake_dict_normalizes_response_language() -> None:
    merged = coalesce_intake_dict(
        {
            "is_task": False,
            "confidence": "high",
            "social_response": "Hi!",
            "response_language": "zh",
            "reasoning": "greeting",
        }
    )
    assert merged["response_language"] == "zh"
