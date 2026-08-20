"""Intake classification schema helpers for LLM-only classification."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .models import (
    IntakeLLMResult,
    ResponseLanguage,
    TaskComplexity,
    normalize_response_language,
)


class SocialReplyResult(BaseModel):
    """Structured output for the dedicated social-reply fallback call."""

    social_response: str = Field(
        description=(
            "Direct friendly reply to the user's social message. "
            "For identity: name the configured assistant and Dr. Xiaming Chen; "
            "never Claude, ChatGPT, Gemini, or other vendor models."
        ),
    )


def intake_json_schema() -> dict[str, Any]:
    """Build the intake classification wire schema (all fields required, nullable where conditional)."""
    schema = dict(IntakeLLMResult.model_json_schema())
    schema["required"] = [
        "confidence",
        "is_task",
        "reasoning",
        "response_language",
        "social_response",
        "task_complexity",
        "task_short_description",
    ]
    return schema


def coalesce_intake_dict(result_dict: dict[str, Any]) -> dict[str, Any]:
    """Normalize intake classification dict fields after structured output parsing."""
    merged = dict(result_dict)
    lang = normalize_response_language(merged.get("response_language"))
    merged["response_language"] = (lang or ResponseLanguage.OTHER).value

    raw_complexity = merged.get("task_complexity")
    if raw_complexity is None or not str(raw_complexity).strip():
        merged["task_complexity"] = None
    else:
        try:
            merged["task_complexity"] = TaskComplexity(str(raw_complexity).strip().lower())
        except ValueError:
            merged["task_complexity"] = TaskComplexity.COMPLEX
    return merged


__all__ = [
    "SocialReplyResult",
    "coalesce_intake_dict",
    "intake_json_schema",
]
